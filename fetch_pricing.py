"""LLM Pricing Pipeline.

On-demand single source of truth for LLM pricing. Fetches pricing from OpenRouter
and LiteLLM, merges it with a local overrides truth layer (highest precedence), and
emits cache/pricing.json with freshness metadata (fetched_at, ttl_hours, freshness).

Stdlib-only (Python 3.9+). Implements tasks T-001..T-008 from .specs/llm-pricing-pipeline.
"""

import argparse
import contextlib
import json
import os
import re
import sys
from datetime import datetime, timezone

# How long fetched data -- pricing, discovery, endpoint snapshots -- counts as
# fresh. One week. A consumer needing tighter passes --ttl-hours, which is a
# read-time gate for that caller only and is never stamped into the shared
# envelope (see _refresh_cache_if_stale).
DEFAULT_TTL_HOURS = 168

# Relative divergence between an override and its catalog baseline above which
# the override is flagged as drifted.
DRIFT_TOLERANCE = 0.05

# How long an override's `verified_at` attestation is trusted before it is
# reported for re-confirmation. Without expiry, `negotiated: true` is a
# permanent mute button and hand-typed prices rot exactly as before.
ATTESTATION_MAX_AGE_DAYS = 90

# Assumed input:output token mix when ranking providers for `query cheapest`.
# Which host is cheapest depends on the workload's mix, so any single number is
# an assumption -- it is named in the answer (`ranked_by`) rather than hidden.
CHEAPEST_IO_RATIO = 3

# What one unit of a price buys, and which fields carry it. This is the whole
# vocabulary: any other `unit` fails validation, and a unit's fields are never
# reused for another unit -- a per-page price must never land in `in`/`out`,
# where a consumer would multiply it by a token count. Rendered into the
# governed documents by tests/test_contract_drift.py; do not restate it.
UNITS = {
    "per_1m_tokens": {"fields": ("in", "out"),
                      "buys": "one million input / output tokens"},
    "per_page":      {"fields": ("price",),
                      "buys": "one page processed"},
    "per_run":       {"fields": ("price",),
                      "buys": "one request / invocation"},
    "per_gpu_hour":  {"fields": ("usd_per_hour",),
                      "buys": "one hour of the named GPU"},
    "per_month":     {"fields": ("price",),
                      "buys": "one month, flat -- cost per unit of work needs a volume"},
}
DEFAULT_UNIT = "per_1m_tokens"
_ALL_PRICE_FIELDS = frozenset(f for spec in UNITS.values() for f in spec["fields"])

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INVOCATION_SCRIPT_DIR = _SCRIPT_DIR

# Anchor paths to this file so the script is CWD-independent (safe to invoke
# from any directory, e.g. as a subprocess from a consumer repo).
OVERRIDES_PATH = os.path.join(_SCRIPT_DIR, "overrides.json")
CACHE_PATH = os.path.join(_SCRIPT_DIR, "cache", "pricing.json")
DISCOVERY_PATH = os.path.join(_SCRIPT_DIR, "cache", "discovery.json")
ENDPOINTS_CACHE_DIR = os.path.join(_SCRIPT_DIR, "cache", "endpoints")
OPENROUTER_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{slug}/endpoints"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
LITELLM_PRICES_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
# Public, unauthenticated, documented (huggingface.co/docs/inference-providers/hub-api):
# per-provider prices in USD per 1M tokens for every chat model HF routes.
HF_ROUTER_URL = "https://router.huggingface.co/v1/models"


def parse_args(argv=None):
    """Parse CLI arguments, returning an argparse.Namespace.

    Defaults: --force off, --ttl-hours = DEFAULT_TTL_HOURS.
    """
    parser = argparse.ArgumentParser(
        prog="fetch_pricing",
        description="Fetch and merge LLM pricing into cache/pricing.json.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the TTL gate and refetch regardless of cache freshness.",
    )
    parser.add_argument(
        "--ttl-hours",
        type=int,
        default=DEFAULT_TTL_HOURS,
        help="Override the freshness TTL in hours (default: %(default)s).",
    )
    sub = parser.add_subparsers(dest="command")
    q = sub.add_parser("query", help="run pricing queries (price, cheapest, list, fresh, "
                                     "review, deployments)")
    q.add_argument("action", choices=["price", "cheapest", "list", "fresh", "review",
                                      "deployments"],
                   help="query action")
    q.add_argument("model", nargs="?", default=None, help="model id (for price/cheapest)")
    q.add_argument(
        "--offline",
        action="store_true",
        help="never hit the network: serve cached/stale data or report not found",
    )
    return parser.parse_args(argv)


def load_overrides(path=OVERRIDES_PATH):
    """Load the overrides truth layer (FR-001, FR-009).

    Returns a dict keyed by model_id. A missing, empty, or non-dict file
    yields an empty layer so the pipeline can proceed with external sources alone.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Tag overrides as the winning layer so merge records source correctly.
    # Underscore-prefixed keys are file documentation, not models.
    return {
        mid: {**entry, "source": "override"} if isinstance(entry, dict) else entry
        for mid, entry in data.items()
        if not mid.startswith("_")
    }


def _default_fetcher(url):
    """Default HTTP GET via stdlib urllib. Returns decoded text (NFR-001)."""
    import urllib.request  # deferred: 14ms import tree, unused on offline read path
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _to_price_per_1m(value):
    """Convert a per-token price to USD per 1M tokens, or None if invalid."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return round(price * 1_000_000, 6)


def _normalize_openrouter(data):
    """Tolerant extraction of OpenRouter catalog entries (layer 3).

    Captures plain in/out plus, when present, input-cache read/write pricing
    and a flag for conditional pricing overrides (additive baseline fields).
    """
    models = {}
    for item in data.get("data", []) if isinstance(data, dict) else []:
        mid = item.get("id")
        if not mid:
            continue
        pricing = item.get("pricing") or {}
        inp = _to_price_per_1m(pricing.get("prompt"))
        out = _to_price_per_1m(pricing.get("completion"))
        if inp is None and out is None:
            continue
        entry = {"source": "openrouter"}
        if inp is not None:
            entry["in"] = inp
        if out is not None:
            entry["out"] = out
        cache_read = _to_price_per_1m(pricing.get("input_cache_read"))
        if cache_read is not None:
            entry["in_cache_read"] = cache_read
        cache_write = _to_price_per_1m(pricing.get("input_cache_write"))
        if cache_write is not None:
            entry["in_cache_write"] = cache_write
        if pricing.get("overrides"):
            entry["has_pricing_overrides"] = True
        models[mid] = entry
    return models


def _normalize_litellm(data):
    """Tolerant extraction of LiteLLM pricing entries (layer 2)."""
    models = {}
    if not isinstance(data, dict):
        return models
    for mid, info in data.items():
        if not isinstance(info, dict):
            continue
        inp = _to_price_per_1m(info.get("input_cost_per_token"))
        out = _to_price_per_1m(info.get("output_cost_per_token"))
        if inp is None and out is None:
            continue
        entry = {"source": "litellm"}
        if inp is not None:
            entry["in"] = inp
        if out is not None:
            entry["out"] = out
        models[mid] = entry
    return models


def _fetch_json(url, fetcher):
    """GET url and parse JSON. Raises on network/parse errors (caller handles)."""
    return json.loads(fetcher(url))


def fetch_openrouter(url=OPENROUTER_MODELS_URL, fetcher=_default_fetcher):
    """Fetch and normalize the OpenRouter catalog (FR-003, NFR-002)."""
    return _normalize_openrouter(_fetch_json(url, fetcher))


def fetch_litellm(url=LITELLM_PRICES_URL, fetcher=_default_fetcher):
    """Fetch and normalize LiteLLM prices (FR-003, NFR-002)."""
    return _normalize_litellm(_fetch_json(url, fetcher))


def _normalize_hf_router(data):
    """Tolerant extraction of the Hugging Face router's per-provider prices.

    Documented shape: {"data": [{"id": "org/Model", "providers": [{"provider",
    "status", "context_length", "pricing": {"input", "output"}, ...}]}]}, with
    prices already in USD per 1M tokens. A provider with no `pricing` (Featherless
    is flat-rate) is kept with its status so `hosts` can list it, and is never
    ranked. Host names are canonicalised at read time so the two catalogs agree
    on who is who. Result: {hf_id: {host: {in, out, context_length, status}}}.
    """
    layer = {}
    items = data.get("data", []) if isinstance(data, dict) else []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        providers = item.get("providers")
        hosts = {}
        for p in providers if isinstance(providers, list) else []:
            if not isinstance(p, dict):
                continue
            host = canonical_host(p.get("provider"))
            if not host:
                continue
            row = {"status": p.get("status")}
            if p.get("context_length") is not None:
                row["context_length"] = p["context_length"]
            pricing = p.get("pricing") or {}
            for src, dst in (("input", "in"), ("output", "out")):
                value = pricing.get(src) if isinstance(pricing, dict) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    row[dst] = round(float(value), 6)
            hosts[host] = row
        if hosts:
            layer[item["id"]] = hosts
    return layer


def fetch_hf_router(url=HF_ROUTER_URL, fetcher=_default_fetcher):
    """Fetch and normalize the Hugging Face router model list (spec 005, US3)."""
    return _normalize_hf_router(_fetch_json(url, fetcher))


def merge(layers):
    """Per-field deep merge of layers, ascending precedence (lowest first).

    Layers are ordered lowest to highest precedence: OpenRouter, LiteLLM,
    overrides. For each model_id, later (higher-precedence) layers win per
    field; fields a higher-precedence entry omits are inherited from below.
    `source` reflects the highest-precedence layer that contributed (FR-007).
    """
    merged = {}
    for layer in layers:
        for mid, entry in layer.items():
            if not isinstance(entry, dict):
                continue
            current = merged.setdefault(mid, {})
            for key, val in entry.items():
                if key == "source":
                    continue
                current[key] = val
            current["source"] = entry.get("source", current.get("source"))
    return merged


def _relative_drift(ours, theirs):
    """Normalized divergence in [0, 1] between two prices, or None if incomparable.

    Symmetric (divides by the larger value) so the result stays finite and
    JSON-safe even when one side is zero.
    """
    if not _is_non_negative_num(ours) or not _is_non_negative_num(theirs):
        return None
    largest = max(ours, theirs)
    if largest == 0:
        return None
    return abs(theirs - ours) / largest


def attestation_state(entry, now=None):
    """Classify an override's price attestation: valid / expired / missing.

    A hand-typed price is trusted only when the entry attests to it with
    `negotiated: true`, a non-empty `note`, and a parseable `verified_at`. A
    future-dated or unparseable `verified_at` is treated as missing.
    """
    if entry.get("negotiated") is not True:
        return "missing"
    return _note_and_date_state(entry, now)


def _note_and_date_state(entry, now=None):
    """valid / expired / missing, judged from `note` + `verified_at` alone.

    The claim half of every attestation in the repo -- overrides add `negotiated`
    on top; deployments and GPU rates use exactly this. A future-dated or
    unparseable `verified_at` is missing, not valid: a date nobody could have
    written on purpose is not a claim.
    """
    note = entry.get("note")
    if not isinstance(note, str) or not note.strip():
        return "missing"
    verified_at = _parse_iso_utc(entry.get("verified_at"))
    if verified_at is None:
        return "missing"
    if now is None:
        now = datetime.now(timezone.utc)
    age_days = (now - verified_at).total_seconds() / 86400
    if age_days < 0:
        return "missing"
    return "expired" if age_days > ATTESTATION_MAX_AGE_DAYS else "valid"


def attach_catalog_baseline(overrides, openrouter_layer, litellm_layer, now=None):
    """Resolve each override against the catalog: inherit price, or honour an attested one.

    An override always owns the tokenizer mapping (no source supplies one). Its
    price is optional, and unattested prices are not trusted:

    - **No `in`/`out`** -> inherit the catalog price; `source` names that layer.
    - **Hand-typed price WITH a valid attestation** -> honoured as authoritative.
      Divergence from catalog is expected here, so it is recorded as `drift` for
      information only.
    - **Hand-typed price WITHOUT one** -> the price is *discarded* and the catalog
      price inherited, flagged `review: unattested-price-ignored`. This is what
      stops a stale transcription from surviving a refresh.

    The catalog row is attached as `catalog`, not `baseline`: the query surface
    already uses a boolean `baseline` flag to mark discovery-sourced answers.
    """
    catalog = openrouter_layer or {}
    litellm = litellm_layer or {}
    catalog_ids = set(catalog)
    linked = {}
    for mid, entry in overrides.items():
        if not isinstance(entry, dict):
            linked[mid] = entry
            continue
        entry = {k: v for k, v in entry.items() if k != "openrouter_slug"}
        prices_its_own = all(_is_non_negative_num(entry.get(f)) for f in ("in", "out"))
        attestation = attestation_state(entry, now) if prices_its_own else "missing"

        slug = _resolve_slug(catalog_ids, mid, overrides)
        if slug is not None:
            base, base_source = catalog[slug], "openrouter"
        elif mid in litellm:
            base, base_source, slug = litellm[mid], "litellm", mid
        else:
            base, base_source = None, None
        inheritable = base is not None and all(base.get(f) is not None for f in ("in", "out"))

        # An unattested price can only be dropped if the catalog can replace it.
        honour = prices_its_own and (attestation != "missing" or not inheritable)

        if base is None:
            if prices_its_own and attestation != "valid":
                entry["review"] = "unverifiable-price"
            linked[mid] = entry
            continue

        catalog_row = {"slug": slug, "source": base_source}
        drift = {}
        for field in ("in", "out"):
            if base.get(field) is None:
                continue
            catalog_row[field] = base[field]
            if honour:
                divergence = _relative_drift(entry.get(field), base[field])
                if divergence is not None and divergence > DRIFT_TOLERANCE:
                    drift[field] = round(divergence, 4)
            else:
                entry[field] = base[field]
        entry["catalog"] = catalog_row
        entry["source"] = "override" if honour else base_source
        if drift:
            entry["drift"] = drift
        if prices_its_own and not honour:
            entry["review"] = "unattested-price-ignored"
        elif honour and attestation == "expired":
            entry["review"] = "attestation-expired"
        elif honour and attestation == "missing":
            entry["review"] = "unverifiable-price"
        linked[mid] = entry
    return linked


def _is_non_negative_num(value):
    """True if value is a number >= 0 (bool, None and non-numerics are invalid)."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return value >= 0


def _unit_fields_valid(entry, unit):
    """True if `entry` carries exactly `unit`'s price fields, all non-negative.

    A field belonging to a different unit is rejected even when the unit's own
    fields are fine: the presence of `price` on a per-token entry means someone
    put a per-page number where a token multiplier will find it.
    """
    spec = UNITS.get(unit)
    if spec is None:
        return False
    if not all(_is_non_negative_num(entry.get(f)) for f in spec["fields"]):
        return False
    foreign = _ALL_PRICE_FIELDS - set(spec["fields"])
    return not any(f in entry for f in foreign)


def validate_entry(entry):
    """Return True if an emitted *model* entry is valid (NFR-005).

    Model entries are per-token by definition: `unit` must be `per_1m_tokens`
    (absent means the same -- entries written before units existed), with a
    non-empty `tokenizer` and non-negative `in`/`out`. Other units live under
    `deployments`, never here. Each `alternatives[]` entry must itself have
    non-negative `in`/`out`.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("unit", DEFAULT_UNIT) != DEFAULT_UNIT:
        return False
    if not _unit_fields_valid(entry, DEFAULT_UNIT):
        return False
    tokenizer = entry.get("tokenizer")
    if not isinstance(tokenizer, str) or not tokenizer:
        return False
    catalog_row = entry.get("catalog")
    if catalog_row is not None:
        if not isinstance(catalog_row, dict):
            return False
        for field in ("in", "out"):
            if field in catalog_row and not _is_non_negative_num(catalog_row[field]):
                return False
    for alt in entry.get("alternatives", []) or []:
        if not isinstance(alt, dict):
            return False
        if not _is_non_negative_num(alt.get("in")) or not _is_non_negative_num(alt.get("out")):
            return False
    return True


def filter_valid(models):
    """Return the subset of merged models that pass validate_entry (FR-005)."""
    return {mid: entry for mid, entry in models.items() if validate_entry(entry)}


def _parse_iso_utc(value):
    """Parse an ISO-8601 UTC timestamp to aware datetime, or None if invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_fresh(cache, ttl_hours=DEFAULT_TTL_HOURS, now=None):
    """Return True if cache.fetched_at is younger than ttl_hours (FR-002, FR-008).

    Age is computed from fetched_at to `now`. Exactly at the TTL boundary is
    stale; a missing, unparseable, or future-dated fetched_at is also stale.
    """
    if not isinstance(cache, dict):
        return False
    fetched_at = _parse_iso_utc(cache.get("fetched_at"))
    if fetched_at is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    age_seconds = (now - fetched_at).total_seconds()
    if age_seconds < 0:
        return False
    return age_seconds < ttl_hours * 3600


def build_cache(models, ttl_hours, fetched_at, freshness, needs_review=None,
                deployments=None):
    """Build the cache/pricing.json payload (FR-001, FR-006, FR-008).

    `needs_review` is a top-level roll-up so a consumer can spot an entry a human
    must look at without walking every model. `freshness` stays purely about age.
    `deployments` is the second truth layer -- what we actually run, in its native
    unit -- kept apart from `models`, which stay per-token.
    """
    return {
        "fetched_at": fetched_at,
        "ttl_hours": ttl_hours,
        "freshness": freshness,
        "needs_review": sorted(needs_review or []),
        "models": models,
        "deployments": deployments or {},
    }


def _write_json_atomic(path, payload, **dump_kwargs):
    """Write JSON via a temp file in the same directory, then rename.

    Hermes, Pi and the estimator all read these files concurrently; a plain
    truncate-and-write lets a reader observe a half-written file. os.replace is
    atomic within a filesystem, so a reader sees either the old or the new file.
    """
    import tempfile  # deferred: 6.3ms import tree, only needed when writing
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, **dump_kwargs)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def emit(payload, out_path=CACHE_PATH):
    """Write a cache payload to out_path, creating parent directories."""
    _write_json_atomic(out_path, payload, indent=2, sort_keys=True)


def _last_known_layer(discovery_path, layer_name):
    """Return a previously fetched discovery layer, or None if unavailable."""
    if not discovery_path:
        return None
    disc = _load_discovery(discovery_path)
    return (disc or {}).get(layer_name) or None


def _load_cache(path=CACHE_PATH):
    """Load the cache dict, or None if missing/corrupt (treated as stale)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _now_iso(now=None):
    """ISO-8601 UTC timestamp string (RFC 3339 style, ends in Z)."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- deployments: what we actually run ----------------

DEPLOYMENTS_PATH = os.path.join(_SCRIPT_DIR, "deployments.json")
GPU_RATES_PATH = os.path.join(_SCRIPT_DIR, "gpu_rates.json")

# The same host is named differently by different catalogs (`BaseTen` / `baseten`,
# `Fireworks` / `fireworks-ai`, `Z.AI` / `zai-org` / `z-ai`). Aliases are declared,
# never inferred: a fuzzy merge would silently price one host as another, which is
# the failure _resolve_slug was fixed for. Unknown names stay distinct.
HOST_ALIASES = {
    "fireworksai": "fireworks",
    "featherlessai": "featherless",
    "zaiorg": "zai",
    "moonshotai": "moonshot",
    "selfhost": "self-host",
}


def canonical_host(name):
    """Canonical host id: lowercase, alphanumerics only, then declared aliases."""
    if not isinstance(name, str):
        return None
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return HOST_ALIASES.get(key, key) or None


def _load_truth_file(path):
    """Load a hand-held JSON object; `_`-prefixed keys are documentation."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load_deployments(path=DEPLOYMENTS_PATH):
    """deployments.json: what we actually run, each in its native unit."""
    return _load_truth_file(path)


def load_gpu_rates(path=GPU_RATES_PATH):
    """gpu_rates.json: attested USD per hour, keyed <gpu>@<provider>."""
    return _load_truth_file(path)


deployment_attestation_state = _note_and_date_state


def validate_deployment(entry):
    """True if a deployments.json entry has a usable shape (spec 005 data-model).

    Quoted entries carry exactly their unit's price fields. Derived entries carry
    a `derive` block naming a GPU rate, no price fields, and a single-field unit:
    a seconds-per-unit measurement yields one number, and `per_1m_tokens` needs
    two. `per_month` cannot be derived from GPU time at all.
    """
    if not isinstance(entry, dict):
        return False
    if not all(isinstance(entry.get(k), str) and entry[k] for k in ("model", "host")):
        return False
    spec = UNITS.get(entry.get("unit"))
    if spec is None:
        return False
    derive = entry.get("derive")
    has_price = any(f in entry for f in _ALL_PRICE_FIELDS)
    if derive is not None:
        if not isinstance(derive, dict) or has_price:
            return False
        gpu = derive.get("gpu")
        return (len(spec["fields"]) == 1 and entry["unit"] != "per_month"
                and isinstance(gpu, str) and bool(gpu))
    return _unit_fields_valid(entry, entry["unit"])


def derive_deployment_price(entry, gpu_rates, now=None):
    """Price a self-hosted deployment from an attested GPU rate and a measurement.

    Returns (review_reason_or_None, fields). `fields` is empty when an input is
    missing -- a derived price is never guessed. Otherwise it holds the unit's
    price field (usd_per_hour * seconds_per_unit / 3600) and `rate`, naming
    exactly which USD/hour was used, so the answer carries its own provenance.
    """
    derive = entry.get("derive") or {}
    key = derive.get("gpu")
    rate = gpu_rates.get(key) if isinstance(key, str) else None
    if not isinstance(rate, dict) or not _is_non_negative_num(rate.get("usd_per_hour")):
        return "gpu-rate-missing", {}
    spu = derive.get("seconds_per_unit")
    if isinstance(spu, bool) or not isinstance(spu, (int, float)) or spu <= 0:
        return "bench-missing", {}
    field = UNITS[entry["unit"]]["fields"][0]
    fields = {field: round(rate["usd_per_hour"] * spu / 3600, 8),
              "rate": {"key": key, "usd_per_hour": rate["usd_per_hour"],
                       "provider": rate.get("provider")}}
    state = _note_and_date_state(rate, now)
    reason = {"expired": "gpu-rate-expired", "missing": "gpu-rate-unattested"}.get(state)
    return reason, fields


def host_rows(model, overrides, endpoints_dir=ENDPOINTS_CACHE_DIR, discovery=None):
    """Every (host, sku) price for a model from the per-host catalogs (spec 005, US4).

    Rows come from the OpenRouter endpoint snapshot for the model's pinned slug
    and, when the model declares `hf_id`, from the Hugging Face router layer of
    the discovery sidecar. Host names are canonicalised so the two catalogs agree
    on who is who. Rows are catalog data -- `baseline: true`, verifiers rather
    than truth -- sorted cheapest first by blended cost; a row with no per-token
    price sorts last and is never ranked.
    """
    rows = []
    entry = (overrides or {}).get(model)
    entry = entry if isinstance(entry, dict) else {}
    slug = entry.get("openrouter_slug")
    if slug:
        snap = _load_endpoint_snapshot(_endpoint_snapshot_path(slug, endpoints_dir))
        for e in (snap or {}).get("endpoints", []):
            host = canonical_host(e.get("provider_name"))
            if not host:
                continue
            row = {"host": host, "source": "openrouter-endpoints", "baseline": True,
                   "unit": DEFAULT_UNIT, "quantization": e.get("quantization"),
                   "context_length": e.get("context_length")}
            for f in ("in", "out", "in_cache_read"):
                if e.get(f) is not None:
                    row[f] = e[f]
            rows.append(row)
    hf_id = entry.get("hf_id")
    hf_layer = ((discovery or {}).get("hf_router") or {}).get(hf_id) if hf_id else None
    for host, e in (hf_layer or {}).items():
        if not isinstance(e, dict):
            continue
        row = {"host": canonical_host(host), "source": "hf-router", "baseline": True,
               "unit": DEFAULT_UNIT, "context_length": e.get("context_length"),
               "status": e.get("status")}
        for f in ("in", "out"):
            if e.get(f) is not None:
                row[f] = e[f]
        rows.append(row)
    rows.sort(key=_blended_cost)
    return rows


def _catalog_row_at_host(rows, host):
    """Cheapest *priced* catalog row at a host, or None. Rows arrive cheapest-first."""
    want = canonical_host(host)
    for row in rows:
        if row.get("host") == want and "in" in row and "out" in row:
            return row
    return None


def resolve_deployments(deployments, gpu_rates, rows_for, now=None):
    """Resolve deployments.json into the emitted `deployments` layer (spec 005, US2).

    `rows_for(model)` returns the per-host catalog rows for a model. The rules
    are the overrides rules, applied verbatim: an attested price stands and is
    cross-checked where a catalog row exists at that host (`catalog`, `drift`);
    an unattested one yields to the catalog price when there is one and is
    kept-and-flagged when there is not; an expired one keeps its price and asks
    a human. A derived price names every input and is absent when one is missing
    -- and a missing input outranks a stale claim in `review`, because it is the
    more urgent thing. Nothing is silently dropped: an invalid entry is emitted
    with no price so it is reported.
    """
    resolved = {}
    for did, entry in deployments.items():
        if not isinstance(entry, dict) or not validate_deployment(entry):
            out = {k: v for k, v in entry.items() if k not in _ALL_PRICE_FIELDS} \
                if isinstance(entry, dict) else {}
            out.update({"source": "deployment", "baseline": False,
                        "review": "invalid-deployment"})
            resolved[did] = out
            continue

        unit = entry["unit"]
        out = {k: v for k, v in entry.items() if k not in _ALL_PRICE_FIELDS}
        out.update({"source": "deployment", "baseline": False,
                    "host": canonical_host(entry["host"])})
        attestation = _note_and_date_state(entry, now)
        out["attestation"] = attestation
        if attestation == "expired":
            out["review"] = "attestation-expired"
        elif attestation == "missing":
            out["review"] = "unattested-deployment"

        if "derive" in entry:
            reason, fields = derive_deployment_price(entry, gpu_rates, now)
            out.update(fields)
            if reason:
                out["review"] = reason
            resolved[did] = out
            continue

        for f in UNITS[unit]["fields"]:
            out[f] = entry[f]
        catalog = None
        if unit == DEFAULT_UNIT:
            catalog = _catalog_row_at_host(rows_for(entry["model"]), entry["host"])
        if attestation == "missing" and catalog is not None:
            # Same rule as overrides: an unclaimed number yields to the catalog.
            out["in"], out["out"] = catalog["in"], catalog["out"]
            out["source"] = catalog["source"]
        if catalog is not None:
            out["catalog"] = {"host": catalog["host"], "in": catalog["in"],
                              "out": catalog["out"], "source": catalog["source"]}
            if out["source"] == "deployment":
                drift = {}
                for f in ("in", "out"):
                    divergence = _relative_drift(out[f], catalog[f])
                    if divergence is not None and divergence > DRIFT_TOLERANCE:
                        drift[f] = round(divergence, 4)
                if drift:
                    out["drift"] = drift
        resolved[did] = out
    return resolved


def run(ttl_hours=DEFAULT_TTL_HOURS, force=False,
        cache_path=CACHE_PATH, overrides_path=OVERRIDES_PATH,
        discovery_path=None,
        openrouter_url=OPENROUTER_MODELS_URL, litellm_url=LITELLM_PRICES_URL,
        hf_url=HF_ROUTER_URL, hf_fetcher=None,
        openrouter_fetcher=_default_fetcher, litellm_fetcher=_default_fetcher,
        now=None, endpoints_dir=ENDPOINTS_CACHE_DIR,
        deployments_path=None, gpu_rates_path=None):
    """Orchestrate fetch -> merge -> emit, returning an exit code.

    Exit codes (FR-004/FR-005, NFR-003/NFR-004) follow `_exit_for`, the single
    source for the whole vocabulary -- including the degraded case this function
    returns for flagged entries. The mapping is deliberately NOT restated here:
    the copy that used to live in this docstring described only the age-based
    outcome, long after this function also began signalling degradation.
    """
    # Resolved at call time rather than bound as defaults: a default captures
    # the module constant at import, and the hermetic suite must be able to
    # point every call away from the shipped truth files in one place.
    deployments_path = deployments_path or DEPLOYMENTS_PATH
    gpu_rates_path = gpu_rates_path or GPU_RATES_PATH
    cache = _load_cache(cache_path)

    # Cache-hit path (FR-002): fresh cache and not forced -> zero network I/O.
    if cache is not None and not force and is_fresh(cache, ttl_hours, now=now):
        print(f"cache fresh: served {len(cache.get('models', {}))} models")
        # Recorded at write time; re-report it, or it stays silent for the whole
        # TTL window and only the refreshing caller ever hears about it.
        flagged = cache.get("needs_review") or []
        if flagged:
            print(f"warning: {len(flagged)} override(s) need review: "
                  + ", ".join(sorted(flagged)), file=sys.stderr)
            return 1
        return 0

    # Refresh path (FR-003): fetch both sources independently.
    #
    # The two are not equally load-bearing. Slug resolution and price inheritance
    # both read the OpenRouter catalog, so losing it means we cannot build a good
    # cache and must fall back to stale. LiteLLM is a demoted fallback: reuse its
    # last known layer rather than discarding an otherwise healthy refresh.
    try:
        openrouter_layer = fetch_openrouter(openrouter_url, openrouter_fetcher)
    except Exception:
        openrouter_layer = None
    try:
        litellm_layer = fetch_litellm(litellm_url, litellm_fetcher)
    except Exception:
        litellm_layer = _last_known_layer(discovery_path, "litellm")
        reused = f"reusing {len(litellm_layer)} cached entries" if litellm_layer else "no cached layer"
        print(f"warning: litellm unavailable; {reused}", file=sys.stderr)
    # The Hugging Face router is a demoted per-host catalog, like LiteLLM. It is
    # fetched only when a fetcher is supplied -- the CLI passes one; a caller
    # that supplies none reuses the last known layer. That keeps a hermetic
    # caller's network guard from being swallowed into the fallback path.
    if hf_fetcher is None:
        hf_layer = _last_known_layer(discovery_path, "hf_router")
    else:
        try:
            hf_layer = fetch_hf_router(hf_url, hf_fetcher)
        except Exception:
            hf_layer = _last_known_layer(discovery_path, "hf_router")
            reused = f"reusing {len(hf_layer)} cached entries" if hf_layer else "no cached layer"
            print(f"warning: hf router unavailable; {reused}", file=sys.stderr)
    catalog_unavailable = openrouter_layer is None

    raw_overrides = load_overrides(overrides_path)
    overrides = attach_catalog_baseline(raw_overrides, openrouter_layer, litellm_layer, now=now)
    layers = [layer for layer in (openrouter_layer, litellm_layer, overrides) if layer]
    merged = merge(layers) if layers else {}
    # Every emitted price names what one unit of it buys (FR-001). Model entries
    # are per-token by definition; the stamp is what lets validation reject a
    # non-token price that strays into this layer.
    for entry in merged.values():
        if isinstance(entry, dict):
            entry.setdefault("unit", DEFAULT_UNIT)

    if not catalog_unavailable:
        valid = filter_valid(merged)
        if valid:
            flagged = {mid: e["review"] for mid, e in valid.items() if e.get("review")}
            # An override that survives with neither its own price nor an inherited
            # one is absent from the emitted cache. Inheritance is the default and
            # catalog slugs get renamed, so this must not vanish silently.
            for mid in set(overrides) - set(valid):
                flagged[mid] = "dropped-unpriceable"
            # The second truth layer. Cross-checks read the per-host catalogs from
            # this refresh's layers and the endpoint snapshots on disk -- no fetch.
            layers_view = {"openrouter": openrouter_layer or {}, "litellm": litellm_layer or {},
                           "hf_router": hf_layer or {}}
            deployments = resolve_deployments(
                load_deployments(deployments_path), load_gpu_rates(gpu_rates_path),
                lambda model: host_rows(model, raw_overrides, endpoints_dir, layers_view),
                now)
            for did, entry in deployments.items():
                if entry.get("review"):
                    flagged[did] = entry["review"]
            payload = build_cache(valid, ttl_hours, _now_iso(now), "fresh", flagged,
                                  deployments)
            emit(payload, cache_path)
            if discovery_path:
                _emit_discovery(discovery_path, _now_iso(now),
                                openrouter_layer or {}, litellm_layer or {}, ttl_hours,
                                hf_layer or {})
            print(f"fetched fresh: {len(valid)} models")
            if flagged:
                # Exit 1 ("served, but degraded") so a consumer that already
                # handles the stale path cannot ignore a reviewable entry.
                for mid in sorted(flagged):
                    print(f"warning: {mid}: {flagged[mid]}", file=sys.stderr)
                return 1
            return 0
        # Refresh succeeded but nothing survived validation -> hard failure.
        # Name the overrides so the cause is actionable (a retired slug pin
        # looks identical to a total outage from the exit code alone).
        dropped = sorted(overrides)
        detail = f" (no override survived validation: {', '.join(dropped)})" if dropped else ""
        print(f"error: refresh produced no valid models{detail}", file=sys.stderr)
        return 2

    # The catalog is unreachable (FR-004/FR-005): serve stale if available, else fail.
    stale_cache = cache if (isinstance(cache, dict) and cache.get("models")) else None
    if stale_cache is not None:
        stale_cache = dict(stale_cache)
        stale_cache["freshness"] = "stale"
        emit(stale_cache, cache_path)
        print("stale served (refresh failed)", file=sys.stderr)
        return 1

    print("error: no usable cache", file=sys.stderr)
    return 2


# ---------------- query interface ----------------

def _emit_discovery(path, fetched_at, openrouter_layer, litellm_layer,
                    ttl_hours=DEFAULT_TTL_HOURS, hf_router_layer=None):
    """Persist normalized discovery layers so fallback queries stay TTL-gated.

    `hf_router` is additive: `_load_discovery` tolerates its absence so a
    sidecar written before spec 005 still loads.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        "fetched_at": fetched_at,
        "ttl_hours": ttl_hours,
        "openrouter": openrouter_layer or {},
        "litellm": litellm_layer or {},
        "hf_router": hf_router_layer or {},
    }
    _write_json_atomic(path, payload, sort_keys=True)


def _load_discovery(path=DISCOVERY_PATH):
    """Load the discovery sidecar, or None if missing/corrupt/wrong shape."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("openrouter"), dict) or not isinstance(data.get("litellm"), dict):
        return None
    return data


def ensure_discovery(offline, ttl_hours=DEFAULT_TTL_HOURS, now=None,
                     openrouter_fetcher=_default_fetcher, litellm_fetcher=_default_fetcher,
                     path=DISCOVERY_PATH, hf_fetcher=None):
    """Return the discovery sidecar, refreshing it when stale unless offline.

    Offline (or a failed fetch) returns the existing sidecar as-is, possibly None.
    The Hugging Face layer is demoted and opt-in: fetched only when `hf_fetcher`
    is supplied, and on failure the sidecar's last known layer is kept.
    """
    disc = _load_discovery(path)
    if disc is not None and is_fresh(disc, ttl_hours, now=now):
        return disc
    if offline:
        return disc
    try:
        openrouter_layer = fetch_openrouter(OPENROUTER_MODELS_URL, openrouter_fetcher)
    except Exception:
        openrouter_layer = None
    try:
        litellm_layer = fetch_litellm(LITELLM_PRICES_URL, litellm_fetcher)
    except Exception:
        litellm_layer = None
    if openrouter_layer is None and litellm_layer is None:
        return disc
    hf_layer = (disc or {}).get("hf_router")
    if hf_fetcher is not None:
        try:
            hf_layer = fetch_hf_router(HF_ROUTER_URL, hf_fetcher)
        except Exception:
            pass  # demoted: the last known layer stands
    _emit_discovery(path, _now_iso(now), openrouter_layer, litellm_layer, ttl_hours, hf_layer)
    return _load_discovery(path)


def _endpoint_snapshot_path(slug, endpoints_dir=ENDPOINTS_CACHE_DIR):
    """Path for one model's endpoint snapshot (slugs contain '/'; flatten)."""
    return os.path.join(endpoints_dir, slug.replace("/", "__") + ".json")


def _emit_endpoint_snapshot(path, payload):
    """Write an endpoint snapshot envelope."""
    _write_json_atomic(path, payload, sort_keys=True)


def _load_endpoint_snapshot(path):
    """Load an endpoint snapshot envelope, or None if missing/corrupt/wrong shape."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("endpoints"), list):
        return None
    return data


def fetch_endpoints(slug, fetcher=_default_fetcher):
    """Fetch and normalize OpenRouter per-provider endpoints for a slug (FR-001).

    Tolerant extraction: provider name/tag, quantization, context length, and
    prompt/completion/input-cache-read prices (USD per 1M tokens).
    """
    url = OPENROUTER_ENDPOINTS_URL.format(slug=slug)
    data = json.loads(fetcher(url))
    eps = data.get("data", {})
    items = eps.get("endpoints", []) if isinstance(eps, dict) else (eps if isinstance(eps, list) else [])
    out = []
    for e in items:
        if not isinstance(e, dict):
            continue
        pricing = e.get("pricing") or {}
        inp = _to_price_per_1m(pricing.get("prompt"))
        outp = _to_price_per_1m(pricing.get("completion"))
        if inp is None and outp is None:
            continue
        entry = {"provider_name": e.get("provider_name"), "provider_tag": e.get("tag"),
                 "quantization": e.get("quantization"), "context_length": e.get("context_length")}
        if inp is not None:
            entry["in"] = inp
        if outp is not None:
            entry["out"] = outp
        cache_read = _to_price_per_1m(pricing.get("input_cache_read"))
        if cache_read is not None:
            entry["in_cache_read"] = cache_read
        out.append(entry)
    return out


def _resolve_slug(catalog_ids, model, overrides):
    """Resolve a model id to an OpenRouter slug (FR-002).

    Order: exact catalog id match, overrides-declared `openrouter_slug`, then a
    catalog last-segment match. Returns None when unresolvable (caller falls back
    to the variant scan, or reports the override as unpriceable).

    A declared `openrouter_slug` is authoritative: if the pin no longer resolves
    the answer is None, never a last-segment guess. Prices are inherited from the
    resolved row, so guessing after a retired pin would silently price a model
    from a different one.
    """
    if model in catalog_ids:
        return model
    entry = (overrides or {}).get(model)
    if isinstance(entry, dict) and entry.get("openrouter_slug"):
        pin = entry["openrouter_slug"]
        return pin if pin in catalog_ids else None
    for mid in catalog_ids:
        if mid.rsplit("/", 1)[-1] == model:
            return mid
    return None


def ensure_endpoints(model, slug, offline, ttl_hours=DEFAULT_TTL_HOURS, now=None,
                     fetcher=_default_fetcher, endpoints_dir=ENDPOINTS_CACHE_DIR):
    """Serve or fetch the endpoint snapshot for a slug (FR-003, FR-008).

    Returns (snapshot_or_None, freshness). Fresh snapshot -> zero network;
    stale/missing + online -> fetch and persist; offline or fetch failure ->
    serve the existing snapshot as-is (possibly None).
    """
    path = _endpoint_snapshot_path(slug, endpoints_dir)
    snap = _load_endpoint_snapshot(path)
    if snap is not None and is_fresh(snap, ttl_hours, now=now):
        return snap, "fresh"
    if offline:
        return snap, ("stale" if snap is not None else "no-data")
    try:
        endpoints = fetch_endpoints(slug, fetcher)
    except Exception:
        return snap, ("stale" if snap is not None else "no-data")
    snap = {"fetched_at": _now_iso(now), "ttl_hours": ttl_hours, "slug": slug,
            "endpoints": endpoints}
    _emit_endpoint_snapshot(path, snap)
    return snap, "fresh"


def _blended_cost(entry, ratio=CHEAPEST_IO_RATIO):
    """Cost of one blended token at `ratio` input tokens per output token.

    Ranking on input price alone lets a host with cheap input and expensive
    output win, which is the wrong answer for any real workload.
    """
    price_in, price_out = entry.get("in"), entry.get("out")
    if price_in is None or price_out is None:
        return float("inf")
    return (ratio * price_in + price_out) / (ratio + 1)


def _normalize_model(name):
    """Normalize a model id for variant matching.

    Lowercases, strips provider prefixes (everything before the last '/'), and
    unifies version dashes (gemini-3-7 -> gemini-3.7). Batch suffixes (:batch)
    are intentionally preserved so batch prices never match interactive prices.
    """
    text = name.lower().strip()
    text = re.sub(r"(?<=\d)-(\d+)(?=$|[-.])", r".\1", text)
    return text.rsplit("/", 1)[-1]


def _variant_matches(model, entry_name):
    """True if entry_name is a provider variant of model (normalized suffix match)."""
    return _normalize_model(entry_name).endswith(_normalize_model(model))


def _freshness_status(cache, ttl_hours, now):
    if cache is None:
        return "no-data"
    return "fresh" if is_fresh(cache, ttl_hours, now=now) else "stale"


def _exit_for(freshness, degraded=False):
    """Map an answer's age and its degradation to an exit code.

    Degradation is independent of age: an entry can need review in a perfectly
    fresh cache, and a consumer must not see success while using it.
    """
    if freshness == "no-data":
        return 2
    if degraded or freshness == "stale":
        return 1
    return 0


class _QueryContext:
    """Request-scoped state shared by the query actions.

    Built once by `query_main` so each action reads the same cache view rather
    than re-deriving it. `discovery`/`discovery_freshness` stay None until
    `load_discovery()` runs: `fresh` and `review` answer from the cache alone.
    """

    def __init__(self, cache, freshness, offline, ttl_hours, now,
                 overrides_path, discovery_path, endpoints_dir,
                 openrouter_fetcher, litellm_fetcher, hf_fetcher=None):
        self.cache = cache
        self.hf_fetcher = hf_fetcher
        self.freshness = freshness
        self.offline = offline
        self.ttl_hours = ttl_hours
        self.now = now
        self.overrides_path = overrides_path
        self.discovery_path = discovery_path
        self.endpoints_dir = endpoints_dir
        self.openrouter_fetcher = openrouter_fetcher
        self.litellm_fetcher = litellm_fetcher
        self.models = cache.get("models", {}) if isinstance(cache, dict) else {}
        self.flagged = (cache.get("needs_review") or []) if isinstance(cache, dict) else []
        self.discovery = None
        self.discovery_freshness = "no-data"

    def load_discovery(self):
        """Load (or refresh) the discovery layer and record its freshness."""
        self.discovery = ensure_discovery(self.offline, self.ttl_hours, self.now,
                                          self.openrouter_fetcher, self.litellm_fetcher,
                                          self.discovery_path, hf_fetcher=self.hf_fetcher)
        if self.discovery is None:
            self.discovery_freshness = "no-data"
        else:
            self.discovery_freshness = ("fresh" if is_fresh(self.discovery, self.ttl_hours,
                                                            now=self.now) else "stale")
        return self.discovery

    def layers(self):
        """Discovery layers in answer-preference order."""
        disc = self.discovery or {}
        for layer_name in ("litellm", "openrouter"):
            yield layer_name, (disc.get(layer_name) or {})

    def out(self, payload, freshness, degraded=False):
        """Print the JSON answer on stdout and return its exit code."""
        print(json.dumps(dict(payload, degraded=bool(degraded)), sort_keys=True))
        return _exit_for(freshness, degraded)


def _refresh_cache_if_stale(cache, offline, ttl_hours, now, cache_path, overrides_path,
                            discovery_path, openrouter_fetcher, litellm_fetcher,
                            endpoints_dir=ENDPOINTS_CACHE_DIR,
                            deployments_path=None, gpu_rates_path=None, hf_fetcher=None):
    """Refresh a stale cache before answering, unless offline. Returns the cache."""
    if offline or (cache is not None and is_fresh(cache, ttl_hours, now=now)):
        return cache
    # A query's --ttl-hours is a read-time gate for *this* caller. Stamping it
    # into the shared envelope would change every other consumer's refresh
    # cadence, so the cache keeps its own declared TTL.
    declared = cache.get("ttl_hours") if isinstance(cache, dict) else None
    if isinstance(declared, bool) or not isinstance(declared, int) or declared <= 0:
        declared = DEFAULT_TTL_HOURS
    # Keep stdout clean for the JSON answer: refresh notes go to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        run(ttl_hours=declared, force=True, cache_path=cache_path,
            overrides_path=overrides_path, discovery_path=discovery_path,
            openrouter_fetcher=openrouter_fetcher, litellm_fetcher=litellm_fetcher,
            now=now, endpoints_dir=endpoints_dir,
            deployments_path=deployments_path, gpu_rates_path=gpu_rates_path,
            hf_fetcher=hf_fetcher)
    return _load_cache(cache_path)


def _query_fresh(ctx):
    """`query fresh` -- report cache age and how many entries need review."""
    fetched_at = ctx.cache.get("fetched_at") if isinstance(ctx.cache, dict) else None
    return ctx.out({"freshness": ctx.freshness, "fetched_at": fetched_at,
                    "ttl_hours": ctx.ttl_hours, "needs_review": len(ctx.flagged)},
                   ctx.freshness, bool(ctx.flagged))


def _print_review_table(rows, stream=None):
    """Render the review work list. stderr, so stdout stays pure JSON."""
    stream = stream or sys.stderr  # resolved at call time, not bound at import

    def _pair(a, b):
        return f"{a}/{b}" if a is not None else "—"
    width = max(len(r["model"]) for r in rows)
    print(f"{'model'.ljust(width)}  {'you declared':>14}  {'now serving':>14}  reason",
          file=stream)
    for r in rows:
        print(f"{r['model'].ljust(width)}  "
              f"{_pair(r['declared_in'], r['declared_out']):>14}  "
              f"{_pair(r['serving_in'], r['serving_out']):>14}  {r['reason']}",
              file=stream)


def _query_review(ctx):
    """`query review` -- the work list for `needs_review`, declared vs serving."""
    if ctx.cache is None:
        return ctx.out({"needs_review": [], "freshness": ctx.freshness}, "no-data")
    declared = load_overrides(ctx.overrides_path)
    rows = []
    for mid in ctx.cache.get("needs_review") or []:
        entry = ctx.models.get(mid) or {}
        own = declared.get(mid) or {}
        # An id in needs_review but absent from models can only have been
        # dropped: nothing could price it, so no entry carries the reason.
        rows.append({"model": mid,
                     "reason": entry.get("review", "dropped-unpriceable"),
                     "declared_in": own.get("in"), "declared_out": own.get("out"),
                     "serving_in": entry.get("in"), "serving_out": entry.get("out"),
                     "serving_source": entry.get("source"),
                     "slug": (entry.get("catalog") or {}).get("slug")})
    if rows:
        _print_review_table(rows)
    return ctx.out({"needs_review": rows, "freshness": ctx.freshness},
                   ctx.freshness, bool(rows))


def _query_list(ctx):
    """`query list` -- tracked models first, then discovery as baseline rows."""
    models = [{"model": mid, "in": e.get("in"), "out": e.get("out"),
               "unit": e.get("unit", DEFAULT_UNIT),
               "source": e.get("source"), "baseline": False}
              for mid, e in ctx.models.items()]
    if ctx.discovery is not None:
        for layer_name, layer in ctx.layers():
            for mid, e in layer.items():
                if mid in ctx.models:
                    continue
                models.append({"model": mid, "in": e.get("in"), "out": e.get("out"),
                               "unit": DEFAULT_UNIT,
                               "source": layer_name, "baseline": True})
    status = ctx.freshness if ctx.freshness != "no-data" else ctx.discovery_freshness
    return ctx.out({"freshness": ctx.freshness, "models": models}, status, bool(ctx.flagged))


def _query_price(ctx, model):
    """`query price` -- the tracked price, else a discovery baseline, else not found."""
    if model in ctx.models:
        entry = dict(ctx.models[model])
        entry.update({"model": model, "baseline": False, "freshness": ctx.freshness})
        return ctx.out(entry, ctx.freshness, bool(entry.get("review")))
    if ctx.discovery is not None:
        # Prefer an exact id match over a provider variant.
        for _, layer in ctx.layers():
            if model in layer:
                entry = dict(layer[model])
                entry.update({"model": model, "baseline": True, "unit": DEFAULT_UNIT,
                              "freshness": ctx.discovery_freshness})
                return ctx.out(entry, ctx.discovery_freshness)
        for _, layer in ctx.layers():
            for mid, e in layer.items():
                if _variant_matches(model, mid):
                    entry = dict(e)
                    entry.update({"model": mid, "baseline": True, "unit": DEFAULT_UNIT,
                                  "freshness": ctx.discovery_freshness})
                    return ctx.out(entry, ctx.discovery_freshness)
    return ctx.out({"model": model, "found": False, "freshness": ctx.freshness}, "no-data")


def _cheapest_by_endpoint(ctx, model, authoritative, degraded):
    """US1 (primary): rank OpenRouter's per-provider endpoints for the slug.

    Returns an exit code, or None when there is no usable endpoint snapshot and
    the caller should fall back to the variant scan.
    """
    catalog_ids = set((ctx.discovery or {}).get("openrouter", {}).keys())
    if not catalog_ids:
        return None
    slug = _resolve_slug(catalog_ids, model, load_overrides(ctx.overrides_path))
    if slug is None:
        return None
    snap, ep_freshness = ensure_endpoints(model, slug, ctx.offline, ctx.ttl_hours, ctx.now,
                                          fetcher=ctx.openrouter_fetcher,
                                          endpoints_dir=ctx.endpoints_dir)
    eps = (snap or {}).get("endpoints", [])
    if not eps:
        return None
    cheapest = min(eps, key=_blended_cost)
    payload = {"model": model, "slug": slug,
               "ranked_by": f"blended-{CHEAPEST_IO_RATIO}:1",
               "provider": cheapest.get("provider_name"),
               "provider_tag": cheapest.get("provider_tag"),
               "quantization": cheapest.get("quantization"),
               "in": cheapest.get("in"), "out": cheapest.get("out"),
               "source": "openrouter-endpoints", "baseline": True, "unit": DEFAULT_UNIT,
               "authoritative": authoritative, "variants": len(eps),
               "freshness": ep_freshness}
    if "in_cache_read" in cheapest:
        payload["in_cache_read"] = cheapest["in_cache_read"]
    return ctx.out(payload, ep_freshness, degraded)


def _query_cheapest(ctx, model):
    """`query cheapest` -- cheapest host by blended cost, endpoints then variants."""
    authoritative = dict(ctx.models[model]) if model in ctx.models else None
    degraded = bool((authoritative or {}).get("review"))

    code = _cheapest_by_endpoint(ctx, model, authoritative, degraded)
    if code is not None:
        return code

    # Fallback: LiteLLM/OpenRouter variant scan for vendor-direct models (FR-004).
    variants = []
    if ctx.discovery is not None:
        for layer_name, layer in ctx.layers():
            for mid, e in layer.items():
                if (mid == model or _variant_matches(model, mid)) and "in" in e and "out" in e:
                    variants.append({"provider": mid, "in": e["in"], "out": e["out"],
                                     "source": layer_name})
    if not variants:
        return ctx.out({"model": model, "found": False, "freshness": ctx.freshness}, "no-data")
    cheapest = min(variants, key=_blended_cost)
    return ctx.out({"model": model, "provider": cheapest["provider"], "in": cheapest["in"],
                    "out": cheapest["out"], "source": cheapest["source"], "baseline": True,
                    "unit": DEFAULT_UNIT, "fallback": True, "authoritative": authoritative,
                    "ranked_by": f"blended-{CHEAPEST_IO_RATIO}:1",
                    "variants": len(variants), "freshness": ctx.discovery_freshness},
                   ctx.discovery_freshness, degraded)


def _print_deployments_table(rows, stream=None):
    """Human view of the deployments layer. stderr, so stdout stays pure JSON."""
    # Resolved at call time: a `stream=sys.stderr` default binds the stream that
    # existed at import, so a redirected stderr would never see the table.
    stream = stream or sys.stderr

    def _price(r):
        fields = UNITS.get(r.get("unit"), {}).get("fields", ())
        vals = [r.get(f) for f in fields]
        return "/".join(str(v) for v in vals) if vals and all(v is not None for v in vals) else "—"
    width = max(len(r["id"]) for r in rows)
    print(f"{'deployment'.ljust(width)}  {'unit':14}  {'price':>14}  {'attest':8}  review",
          file=stream)
    for r in rows:
        print(f"{r['id'].ljust(width)}  {str(r.get('unit')):14}  {_price(r):>14}  "
              f"{str(r.get('attestation', '')):8}  {r.get('review', '')}", file=stream)


def _query_deployments(ctx):
    """`query deployments` -- what we actually run, each priced in its native unit."""
    if ctx.cache is None:
        return ctx.out({"deployments": [], "freshness": ctx.freshness}, "no-data")
    rows = [dict(e, id=did) for did, e in sorted((ctx.cache.get("deployments") or {}).items())]
    if rows:
        _print_deployments_table(rows)
    return ctx.out({"deployments": rows, "freshness": ctx.freshness},
                   ctx.freshness, any(r.get("review") for r in rows))


def query_main(args, openrouter_fetcher=_default_fetcher, litellm_fetcher=_default_fetcher,
               now=None, cache_path=CACHE_PATH, overrides_path=OVERRIDES_PATH,
               discovery_path=DISCOVERY_PATH, endpoints_dir=ENDPOINTS_CACHE_DIR,
               deployments_path=None, gpu_rates_path=None, hf_fetcher=None):
    """Dispatch a `query` subcommand. Prints JSON to stdout; returns an exit code.

    Exit codes (FR-008) follow `_exit_for`, which maps freshness *and*
    degradation. Deliberately not restated here -- see `tests/test_contract_drift.py`.
    """
    offline = bool(getattr(args, "offline", False))
    action = args.action
    model = getattr(args, "model", None)
    ttl_hours = getattr(args, "ttl_hours", None) or DEFAULT_TTL_HOURS

    cache = _refresh_cache_if_stale(_load_cache(cache_path), offline, ttl_hours, now,
                                    cache_path, overrides_path, discovery_path,
                                    openrouter_fetcher, litellm_fetcher, endpoints_dir,
                                    deployments_path, gpu_rates_path, hf_fetcher)
    ctx = _QueryContext(cache, _freshness_status(cache, ttl_hours, now), offline,
                        ttl_hours, now, overrides_path, discovery_path, endpoints_dir,
                        openrouter_fetcher, litellm_fetcher, hf_fetcher)

    if action == "fresh":
        return _query_fresh(ctx)
    if action == "review":
        return _query_review(ctx)
    if action == "deployments":
        return _query_deployments(ctx)

    # Every remaining action consults discovery; the two above never do.
    ctx.load_discovery()

    if action == "list":
        return _query_list(ctx)
    if model is None:
        print(json.dumps({"error": "model argument required for %s" % action}), file=sys.stderr)
        return 2
    if action == "price":
        return _query_price(ctx, model)
    if action == "cheapest":
        return _query_cheapest(ctx, model)

    print(json.dumps({"error": "unknown action %r" % action}), file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entrypoint (pipeline run, or `query` subcommands)."""
    args = parse_args(argv)
    # The CLI is the one caller that always wants the demoted HF layer fetched.
    if getattr(args, "command", None) == "query":
        return query_main(args, hf_fetcher=_default_fetcher)
    return run(ttl_hours=args.ttl_hours, force=args.force,
               discovery_path=DISCOVERY_PATH, hf_fetcher=_default_fetcher)


if __name__ == "__main__":
    raise SystemExit(main())

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
import urllib.request
from datetime import datetime, timezone

DEFAULT_TTL_HOURS = 24

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
    q = sub.add_parser("query", help="run pricing queries (price, cheapest, list, fresh)")
    q.add_argument("action", choices=["price", "cheapest", "list", "fresh"], help="query action")
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
    return {
        mid: {**entry, "source": "override"} if isinstance(entry, dict) else entry
        for mid, entry in data.items()
    }


def _default_fetcher(url):
    """Default HTTP GET via stdlib urllib. Returns decoded text (NFR-001)."""
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


def _is_non_negative_num(value):
    """True if value is a number >= 0 (bool, None and non-numerics are invalid)."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return value >= 0


def validate_entry(entry):
    """Return True if an emitted entry is valid (NFR-005).

    Requires a non-empty `tokenizer` and non-negative numeric `in`/`out`.
    Each `alternatives[]` entry must itself have non-negative `in`/`out`.
    """
    if not isinstance(entry, dict):
        return False
    tokenizer = entry.get("tokenizer")
    if not isinstance(tokenizer, str) or not tokenizer:
        return False
    if not _is_non_negative_num(entry.get("in")) or not _is_non_negative_num(entry.get("out")):
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


def build_cache(models, ttl_hours, fetched_at, freshness):
    """Build the cache/pricing.json payload (FR-001, FR-006, FR-008)."""
    return {
        "fetched_at": fetched_at,
        "ttl_hours": ttl_hours,
        "freshness": freshness,
        "models": models,
    }


def emit(payload, out_path=CACHE_PATH):
    """Write a cache payload to out_path, creating parent directories."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


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


def run(ttl_hours=DEFAULT_TTL_HOURS, force=False,
        cache_path=CACHE_PATH, overrides_path=OVERRIDES_PATH,
        discovery_path=None,
        openrouter_url=OPENROUTER_MODELS_URL, litellm_url=LITELLM_PRICES_URL,
        openrouter_fetcher=_default_fetcher, litellm_fetcher=_default_fetcher,
        now=None):
    """Orchestrate fetch -> merge -> emit, returning an exit code.

    Exit codes (FR-004/FR-005, NFR-003/NFR-004): 0 fresh (cache-hit or refresh),
    1 stale cache served, 2 no usable cache.
    """
    cache = _load_cache(cache_path)

    # Cache-hit path (FR-002): fresh cache and not forced -> zero network I/O.
    if cache is not None and not force and is_fresh(cache, ttl_hours, now=now):
        print(f"cache fresh: served {len(cache.get('models', {}))} models")
        return 0

    # Refresh path (FR-003): fetch both sources independently.
    failed = False
    try:
        openrouter_layer = fetch_openrouter(openrouter_url, openrouter_fetcher)
    except Exception:
        openrouter_layer = None
        failed = True
    try:
        litellm_layer = fetch_litellm(litellm_url, litellm_fetcher)
    except Exception:
        litellm_layer = None
        failed = True

    overrides = load_overrides(overrides_path)
    layers = [layer for layer in (openrouter_layer, litellm_layer, overrides) if layer]
    merged = merge(layers) if layers else {}

    if not failed:
        valid = filter_valid(merged)
        if valid:
            payload = build_cache(valid, ttl_hours, _now_iso(now), "fresh")
            emit(payload, cache_path)
            if discovery_path:
                _emit_discovery(discovery_path, _now_iso(now),
                                openrouter_layer or {}, litellm_layer or {}, ttl_hours)
            print(f"fetched fresh: {len(valid)} models")
            return 0
        # Refresh succeeded but nothing survived validation -> hard failure.
        print("error: refresh produced no valid models", file=sys.stderr)
        return 2

    # A source failed (FR-004/FR-005): serve stale if available, else fail.
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
                    ttl_hours=DEFAULT_TTL_HOURS):
    """Persist normalized discovery layers so fallback queries stay TTL-gated."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        "fetched_at": fetched_at,
        "ttl_hours": ttl_hours,
        "openrouter": openrouter_layer or {},
        "litellm": litellm_layer or {},
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)


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
                     path=DISCOVERY_PATH):
    """Return the discovery sidecar, refreshing it when stale unless offline.

    Offline (or a failed fetch) returns the existing sidecar as-is, possibly None.
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
    _emit_discovery(path, _now_iso(now), openrouter_layer, litellm_layer, ttl_hours)
    return _load_discovery(path)


def _endpoint_snapshot_path(slug, endpoints_dir=ENDPOINTS_CACHE_DIR):
    """Path for one model's endpoint snapshot (slugs contain '/'; flatten)."""
    return os.path.join(endpoints_dir, slug.replace("/", "__") + ".json")


def _emit_endpoint_snapshot(path, payload):
    """Write an endpoint snapshot envelope."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)


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

    Order: exact catalog id match, overrides-declared `openrouter_slug`
    (when present in the catalog), then a catalog last-segment match. Returns
    None when unresolvable (caller falls back to the variant scan).
    """
    if model in catalog_ids:
        return model
    entry = (overrides or {}).get(model)
    if isinstance(entry, dict) and entry.get("openrouter_slug") in catalog_ids:
        return entry["openrouter_slug"]
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


def _exit_for(freshness):
    return {"fresh": 0, "stale": 1, "no-data": 2}[freshness]


def query_main(args, openrouter_fetcher=_default_fetcher, litellm_fetcher=_default_fetcher,
               now=None, cache_path=CACHE_PATH, overrides_path=OVERRIDES_PATH,
               discovery_path=DISCOVERY_PATH, endpoints_dir=ENDPOINTS_CACHE_DIR):
    """Run a `query` subcommand. Prints JSON to stdout; returns an exit code.

    Exit codes (FR-008): 0 fresh answer, 1 stale answer, 2 no data / not found.
    """
    offline = bool(getattr(args, "offline", False))
    action = args.action
    model = getattr(args, "model", None)
    ttl_hours = DEFAULT_TTL_HOURS

    def _refresh_cache_if_stale(cache):
        if (cache is None or not is_fresh(cache, ttl_hours, now=now)) and not offline:
            # Keep stdout clean for the JSON answer: refresh notes go to stderr.
            with contextlib.redirect_stdout(sys.stderr):
                run(ttl_hours=ttl_hours, force=True, cache_path=cache_path,
                    overrides_path=overrides_path, discovery_path=discovery_path,
                    openrouter_fetcher=openrouter_fetcher, litellm_fetcher=litellm_fetcher,
                    now=now)
            return _load_cache(cache_path)
        return cache

    def _out(payload, freshness):
        print(json.dumps(payload, sort_keys=True))
        return _exit_for(freshness)

    cache = _load_cache(cache_path)
    cache = _refresh_cache_if_stale(cache)
    freshness = _freshness_status(cache, ttl_hours, now)
    cache_models = (cache or {}).get("models", {}) if isinstance(cache, dict) else {}

    if action == "fresh":
        fetched_at = cache.get("fetched_at") if isinstance(cache, dict) else None
        return _out({"freshness": freshness, "fetched_at": fetched_at,
                     "ttl_hours": ttl_hours}, freshness)

    disc = ensure_discovery(offline, ttl_hours, now,
                            openrouter_fetcher, litellm_fetcher, discovery_path)
    disc_freshness = ("fresh" if (disc is not None and is_fresh(disc, ttl_hours, now=now))
                      else ("stale" if disc is not None else "no-data"))

    if action == "list":
        models = []
        for mid, e in cache_models.items():
            models.append({"model": mid, "in": e.get("in"), "out": e.get("out"),
                           "source": e.get("source"), "baseline": False})
        if disc is not None:
            for layer_name in ("litellm", "openrouter"):
                for mid, e in (disc.get(layer_name) or {}).items():
                    if mid in cache_models:
                        continue
                    models.append({"model": mid, "in": e.get("in"), "out": e.get("out"),
                                   "source": layer_name, "baseline": True})
        status = freshness if freshness != "no-data" else disc_freshness
        return _out({"freshness": freshness, "models": models}, status)

    if model is None:
        print(json.dumps({"error": "model argument required for %s" % action}), file=sys.stderr)
        return 2

    if action == "price":
        if model in cache_models:
            entry = dict(cache_models[model])
            entry.update({"model": model, "baseline": False, "freshness": freshness})
            return _out(entry, freshness)
        if disc is not None:
            # Prefer an exact id match over a provider variant.
            for layer_name in ("litellm", "openrouter"):
                layer = disc.get(layer_name) or {}
                if model in layer:
                    entry = dict(layer[model])
                    entry.update({"model": model, "baseline": True, "freshness": disc_freshness})
                    return _out(entry, disc_freshness)
            for layer_name in ("litellm", "openrouter"):
                for mid, e in (disc.get(layer_name) or {}).items():
                    if _variant_matches(model, mid):
                        entry = dict(e)
                        entry.update({"model": mid, "baseline": True, "freshness": disc_freshness})
                        return _out(entry, disc_freshness)
        return _out({"model": model, "found": False, "freshness": freshness}, "no-data")

    if action == "cheapest":
        authoritative = dict(cache_models[model]) if model in cache_models else None
        # US1: OpenRouter per-provider endpoints path (primary).
        catalog_ids = set((disc or {}).get("openrouter", {}).keys())
        overrides = load_overrides(overrides_path)
        slug = _resolve_slug(catalog_ids, model, overrides) if catalog_ids else None
        if slug is not None:
            snap, ep_freshness = ensure_endpoints(model, slug, offline, ttl_hours, now,
                                                  fetcher=openrouter_fetcher,
                                                  endpoints_dir=endpoints_dir)
            eps = (snap or {}).get("endpoints", [])
            if eps:
                cheapest = min(eps, key=lambda e: (e.get("in", float("inf")),
                                                   e.get("out", float("inf"))))
                payload = {"model": model, "slug": slug,
                           "provider": cheapest.get("provider_name"),
                           "provider_tag": cheapest.get("provider_tag"),
                           "quantization": cheapest.get("quantization"),
                           "in": cheapest.get("in"), "out": cheapest.get("out"),
                           "source": "openrouter-endpoints", "baseline": True,
                           "authoritative": authoritative, "variants": len(eps),
                           "freshness": ep_freshness}
                if "in_cache_read" in cheapest:
                    payload["in_cache_read"] = cheapest["in_cache_read"]
                return _out(payload, ep_freshness)
        # Fallback: LiteLLM/OpenRouter variant scan for vendor-direct models (FR-004).
        variants = []
        if disc is not None:
            for layer_name in ("litellm", "openrouter"):
                for mid, e in (disc.get(layer_name) or {}).items():
                    if (mid == model or _variant_matches(model, mid)) and "in" in e and "out" in e:
                        variants.append({"provider": mid, "in": e["in"], "out": e["out"],
                                         "source": layer_name})
        if not variants:
            return _out({"model": model, "found": False, "freshness": freshness}, "no-data")
        cheapest = min(variants, key=lambda v: (v["in"], v["out"]))
        return _out({"model": model, "provider": cheapest["provider"], "in": cheapest["in"],
                     "out": cheapest["out"], "source": cheapest["source"], "baseline": True,
                     "fallback": True, "authoritative": authoritative,
                     "variants": len(variants), "freshness": disc_freshness}, disc_freshness)

    print(json.dumps({"error": "unknown action %r" % action}), file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entrypoint (pipeline run, or `query` subcommands)."""
    args = parse_args(argv)
    if getattr(args, "command", None) == "query":
        return query_main(args)
    return run(ttl_hours=args.ttl_hours, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

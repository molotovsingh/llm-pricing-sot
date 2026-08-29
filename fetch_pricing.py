"""LLM Pricing Pipeline.

On-demand single source of truth for LLM pricing. Fetches pricing from OpenRouter
and LiteLLM, merges it with a local overrides truth layer (highest precedence), and
emits cache/pricing.json with freshness metadata (fetched_at, ttl_hours, freshness).

Stdlib-only (Python 3.9+). Implements tasks T-001..T-008 from .specs/llm-pricing-pipeline.
"""

import argparse
import json
import os
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
    """Tolerant extraction of OpenRouter catalog entries (layer 3)."""
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


def main(argv=None):
    """CLI entrypoint (resolves args, orchestrates, returns the exit code)."""
    args = parse_args(argv)
    return run(ttl_hours=args.ttl_hours, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

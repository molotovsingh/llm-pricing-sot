"""Unit tests for the fetch_pricing CLI argument parsing (T-001)."""

import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import urllib.request

from fetch_pricing import (
    DEFAULT_TTL_HOURS,
    ATTESTATION_MAX_AGE_DAYS,
    DRIFT_TOLERANCE,
    attestation_state,
    attach_catalog_baseline,
    DISCOVERY_PATH,
    build_cache,
    main,
    emit,
    fetch_litellm,
    fetch_openrouter,
    filter_valid,
    is_fresh,
    load_overrides,
    merge,
    parse_args,
    _now_iso,
    query_main,
    run,
    validate_entry,
    _endpoint_snapshot_path,
    _normalize_model,
    _normalize_openrouter,
)


class TestParseArgs(unittest.TestCase):
    def test_defaults(self):
        args = parse_args([])
        self.assertEqual(args.ttl_hours, DEFAULT_TTL_HOURS)
        self.assertFalse(args.force)

    def test_force_flag(self):
        args = parse_args(["--force"])
        self.assertTrue(args.force)
        self.assertEqual(args.ttl_hours, DEFAULT_TTL_HOURS)

    def test_ttl_hours_override(self):
        args = parse_args(["--ttl-hours", "12"])
        self.assertEqual(args.ttl_hours, 12)
        self.assertFalse(args.force)

    def test_force_and_ttl_override(self):
        args = parse_args(["--force", "--ttl-hours", "48"])
        self.assertTrue(args.force)
        self.assertEqual(args.ttl_hours, 48)


class TestLoadOverrides(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(load_overrides("/no/such/file.json"), {})

    def test_empty_file_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("")
            path = fh.name
        try:
            self.assertEqual(load_overrides(path), {})
        finally:
            os.unlink(path)

    def test_happy_path_injects_override_source(self):
        payload = {"model-a": {"in": 1.0, "out": 2.0, "tokenizer": "tok"}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            path = fh.name
        try:
            loaded = load_overrides(path)
            # The loaded entry is tagged as the winning layer.
            self.assertEqual(loaded["model-a"]["source"], "override")
            self.assertEqual(loaded["model-a"]["in"], 1.0)
        finally:
            os.unlink(path)

    def test_non_dict_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([1, 2, 3], fh)
            path = fh.name
        try:
            self.assertEqual(load_overrides(path), {})
        finally:
            os.unlink(path)


class TestFetchers(unittest.TestCase):
    """T-003: source fetchers use an injectable fetcher; never the real network."""

    def test_openrouter_normalizes_pricing(self):
        def fake(url):
            return json.dumps({
                "data": [
                    {"id": "openai/gpt-4o", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
                    {"id": "free/model", "pricing": {"prompt": "", "completion": ""}},
                ]
            })

        layers = fetch_openrouter("http://fake", fetcher=fake)
        self.assertIn("openai/gpt-4o", layers)
        self.assertEqual(layers["openai/gpt-4o"]["in"], 2.5)
        self.assertEqual(layers["openai/gpt-4o"]["out"], 10.0)
        self.assertEqual(layers["openai/gpt-4o"]["source"], "openrouter")
        # Empty-price model is skipped (no usable pricing).
        self.assertNotIn("free/model", layers)

    def test_litellm_normalizes_pricing(self):
        def fake(url):
            return json.dumps({
                "model-a": {"input_cost_per_token": 0.000003, "output_cost_per_token": 0.000012},
                "model-b": {"input_cost_per_token": "bad", "output_cost_per_token": 0.000002},
            })

        layers = fetch_litellm("http://fake", fetcher=fake)
        self.assertEqual(layers["model-a"]["in"], 3.0)
        self.assertEqual(layers["model-a"]["out"], 12.0)
        self.assertEqual(layers["model-a"]["source"], "litellm")
        # Invalid price for a field falls back to none, not a crash.
        self.assertNotIn("in", layers["model-b"])
        self.assertEqual(layers["model-b"]["out"], 2.0)

    def test_fetcher_error_propagates(self):
        def boom(url):
            raise OSError("network down")

        with self.assertRaises(OSError):
            fetch_openrouter("http://fake", fetcher=boom)


class TestMerge(unittest.TestCase):
    """T-004: per-field deep merge, precedence overrides > litellm > openrouter."""

    def test_precedence_wins_per_field(self):
        openrouter = {"m": {"in": 30.0, "out": 60.0, "source": "openrouter"}}
        litellm = {"m": {"in": 10.0, "out": 20.0, "source": "litellm"}}
        overrides = {"m": {"in": 3.0, "out": 15.0, "source": "override"}}
        result = merge([openrouter, litellm, overrides])
        self.assertEqual(result["m"]["in"], 3.0)
        self.assertEqual(result["m"]["out"], 15.0)
        self.assertEqual(result["m"]["source"], "override")

    def test_partial_override_inherits(self):
        openrouter = {"m": {"in": 30.0, "out": 60.0, "source": "openrouter"}}
        overrides = {"m": {"tokenizer": "tok", "source": "override"}}
        result = merge([openrouter, overrides])
        self.assertEqual(result["m"]["tokenizer"], "tok")
        # in/out inherited from the lower layer.
        self.assertEqual(result["m"]["in"], 30.0)
        self.assertEqual(result["m"]["out"], 60.0)
        self.assertEqual(result["m"]["source"], "override")

    def test_litellm_beats_openrouter(self):
        openrouter = {"m": {"in": 30.0, "out": 60.0, "source": "openrouter"}}
        litellm = {"m": {"in": 10.0, "source": "litellm"}}
        result = merge([openrouter, litellm])
        self.assertEqual(result["m"]["in"], 10.0)
        self.assertEqual(result["m"]["out"], 60.0)
        self.assertEqual(result["m"]["source"], "litellm")

    def test_model_only_in_one_layer(self):
        openrouter = {"a": {"in": 1.0, "out": 2.0, "source": "openrouter"}}
        litellm = {"b": {"in": 3.0, "source": "litellm"}}
        result = merge([openrouter, litellm])
        self.assertIn("a", result)
        self.assertIn("b", result)
        self.assertNotIn("b", result["a"])


def _attested(price_in, price_out, verified_at="2026-08-01"):
    """An override price with a complete attestation, so it is honoured."""
    return {"in": price_in, "out": price_out, "negotiated": True,
            "note": "direct vendor rate", "verified_at": verified_at}


class TestAttachCatalogBaseline(unittest.TestCase):
    """Overrides inherit the catalog price unless they attest to their own."""

    CATALOG = {"openai/gpt-5.2": {"in": 1.75, "out": 14.0, "source": "openrouter"}}

    def test_resolves_by_last_segment(self):
        result = attach_catalog_baseline({"gpt-5.2": _attested(0.4, 1.6)}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["catalog"]["slug"], "openai/gpt-5.2")
        self.assertEqual(result["gpt-5.2"]["catalog"]["in"], 1.75)

    def test_resolves_by_declared_slug(self):
        catalog = {"anthropic/claude-haiku-4.5": {"in": 1.0, "out": 5.0}}
        overrides = {"claude-haiku": {"tokenizer": "tok",
                                      "openrouter_slug": "anthropic/claude-haiku-4.5"}}
        result = attach_catalog_baseline(overrides, catalog, {})
        self.assertEqual(result["claude-haiku"]["catalog"]["slug"],
                         "anthropic/claude-haiku-4.5")

    def test_falls_back_to_litellm_exact_id(self):
        litellm = {"vendor-only": {"in": 2.0, "out": 4.0, "source": "litellm"}}
        result = attach_catalog_baseline({"vendor-only": {"tokenizer": "tok"}}, {}, litellm)
        self.assertEqual(result["vendor-only"]["catalog"]["source"], "litellm")
        self.assertEqual(result["vendor-only"]["in"], 2.0)

    # ---- inheritance is the default ----

    def test_priceless_override_inherits_catalog_price(self):
        result = attach_catalog_baseline({"gpt-5.2": {"tokenizer": "tok"}}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["in"], 1.75)
        self.assertEqual(result["gpt-5.2"]["out"], 14.0)
        self.assertEqual(result["gpt-5.2"]["source"], "openrouter")
        self.assertNotIn("review", result["gpt-5.2"])

    def test_partial_price_is_treated_as_priceless(self):
        result = attach_catalog_baseline({"gpt-5.2": {"in": 0.4}}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["out"], 14.0)
        self.assertEqual(result["gpt-5.2"]["source"], "openrouter")

    # ---- an unattested price is not trusted ----

    def test_unattested_price_is_discarded_for_catalog(self):
        result = attach_catalog_baseline({"gpt-5.2": {"in": 0.4, "out": 1.6}}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["in"], 1.75)
        self.assertEqual(result["gpt-5.2"]["source"], "openrouter")
        self.assertEqual(result["gpt-5.2"]["review"], "unattested-price-ignored")

    def test_incomplete_attestation_is_not_trusted(self):
        for missing in ("note", "verified_at", "negotiated"):
            entry = _attested(0.4, 1.6)
            del entry[missing]
            result = attach_catalog_baseline({"gpt-5.2": entry}, self.CATALOG, {})
            self.assertEqual(result["gpt-5.2"]["in"], 1.75, f"missing {missing}")

    def test_future_verified_at_is_not_trusted(self):
        entry = _attested(0.4, 1.6, verified_at="2099-01-01")
        result = attach_catalog_baseline({"gpt-5.2": entry}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["review"], "unattested-price-ignored")

    def test_unattested_price_kept_when_catalog_cannot_replace_it(self):
        # Nothing to inherit from, so the price survives but is flagged.
        result = attach_catalog_baseline({"private": {"in": 1.0, "out": 2.0}}, self.CATALOG, {})
        self.assertEqual(result["private"]["in"], 1.0)
        self.assertNotIn("catalog", result["private"])
        self.assertEqual(result["private"]["review"], "unverifiable-price")

    # ---- an attested price is authoritative ----

    def test_attested_price_stays_authoritative(self):
        result = attach_catalog_baseline({"gpt-5.2": _attested(0.4, 1.6)}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["in"], 0.4)
        self.assertEqual(result["gpt-5.2"]["out"], 1.6)
        self.assertEqual(result["gpt-5.2"]["source"], "override")
        self.assertNotIn("review", result["gpt-5.2"])

    def test_expired_attestation_is_honoured_but_flagged(self):
        # Reverting to catalog would silently change the price we believe we pay,
        # so the number stands and the attestation is what gets reported.
        entry = _attested(0.4, 1.6, verified_at="2020-01-01")
        result = attach_catalog_baseline({"gpt-5.2": entry}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["in"], 0.4)
        self.assertEqual(result["gpt-5.2"]["review"], "attestation-expired")

    # ---- drift is informational on an attested price ----

    def test_drift_recorded_beyond_tolerance(self):
        result = attach_catalog_baseline({"gpt-5.2": _attested(0.4, 1.6)}, self.CATALOG, {})
        self.assertIn("in", result["gpt-5.2"]["drift"])
        self.assertIn("out", result["gpt-5.2"]["drift"])

    def test_no_drift_when_prices_agree(self):
        result = attach_catalog_baseline({"gpt-5.2": _attested(1.75, 14.0)}, self.CATALOG, {})
        self.assertNotIn("drift", result["gpt-5.2"])

    def test_no_drift_within_tolerance(self):
        nudge = 1.75 * (1 + DRIFT_TOLERANCE / 2)
        result = attach_catalog_baseline({"gpt-5.2": _attested(nudge, 14.0)}, self.CATALOG, {})
        self.assertNotIn("drift", result["gpt-5.2"])

    def test_zero_price_drift_stays_json_safe(self):
        result = attach_catalog_baseline({"gpt-5.2": _attested(0.0, 0.0)}, self.CATALOG, {})
        self.assertEqual(result["gpt-5.2"]["drift"]["in"], 1.0)
        self.assertNotIn("Infinity", json.dumps(result))


class TestAttestationState(unittest.TestCase):
    NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)

    def test_complete_and_recent_is_valid(self):
        self.assertEqual(attestation_state(_attested(1.0, 2.0), self.NOW), "valid")

    def test_old_is_expired(self):
        entry = _attested(1.0, 2.0, verified_at="2020-01-01")
        self.assertEqual(attestation_state(entry, self.NOW), "expired")

    def test_boundary_day_is_still_valid(self):
        edge = self.NOW - timedelta(days=ATTESTATION_MAX_AGE_DAYS)
        entry = _attested(1.0, 2.0, verified_at=edge.strftime("%Y-%m-%d"))
        self.assertEqual(attestation_state(entry, self.NOW), "valid")

    def test_blank_note_is_missing(self):
        entry = _attested(1.0, 2.0)
        entry["note"] = "   "
        self.assertEqual(attestation_state(entry, self.NOW), "missing")

    def test_unparseable_date_is_missing(self):
        entry = _attested(1.0, 2.0, verified_at="last tuesday")
        self.assertEqual(attestation_state(entry, self.NOW), "missing")


class TestValidateEntry(unittest.TestCase):
    """T-005: validation of emitted entries (NFR-005) and batch filter."""

    def test_accepts_valid_entry(self):
        self.assertTrue(validate_entry({"in": 3.0, "out": 15.0, "tokenizer": "tok"}))

    def test_rejects_negative_price(self):
        self.assertFalse(validate_entry({"in": -1.0, "out": 15.0, "tokenizer": "tok"}))
        self.assertFalse(validate_entry({"in": 3.0, "out": -1.0, "tokenizer": "tok"}))

    def test_rejects_missing_tokenizer(self):
        self.assertFalse(validate_entry({"in": 3.0, "out": 15.0}))
        self.assertFalse(validate_entry({"in": 3.0, "out": 15.0, "tokenizer": ""}))

    def test_rejects_non_numeric_or_missing_price(self):
        self.assertFalse(validate_entry({"in": "3", "out": 15.0, "tokenizer": "tok"}))
        self.assertFalse(validate_entry({"in": 3.0, "tokenizer": "tok"}))
        self.assertFalse(validate_entry({"out": 15.0, "tokenizer": "tok"}))

    def test_rejects_negative_catalog_price(self):
        entry = {"in": 3.0, "out": 15.0, "tokenizer": "tok",
                 "catalog": {"slug": "a/b", "source": "openrouter", "in": -1.0}}
        self.assertFalse(validate_entry(entry))

    def test_accepts_catalog_row_without_prices(self):
        entry = {"in": 3.0, "out": 15.0, "tokenizer": "tok",
                 "catalog": {"slug": "a/b", "source": "openrouter"}}
        self.assertTrue(validate_entry(entry))

    def test_alternatives_must_be_valid(self):
        # R3: alternatives with a negative price are rejected.
        bad_alt = {"in": 3.0, "out": 15.0, "tokenizer": "tok", "alternatives": [{"provider": "x", "in": -1.0, "out": 2.0}]}
        self.assertFalse(validate_entry(bad_alt))

    def test_filter_valid_keeps_only_valid(self):
        models = {
            "ok": {"in": 1.0, "out": 2.0, "tokenizer": "tok"},
            "no_tok": {"in": 1.0, "out": 2.0},
            "bad": {"in": -1.0, "out": 2.0, "tokenizer": "tok"},
        }
        result = filter_valid(models)
        self.assertEqual(list(result.keys()), ["ok"])


class TestIsFresh(unittest.TestCase):
    """T-006: TTL/freshness logic (FR-002, FR-008)."""

    def setUp(self):
        self.now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _cache_at(self, hours_ago):
        fetched = (self.now - timedelta(hours=hours_ago)).isoformat()
        return {"fetched_at": fetched}

    def test_within_ttl_is_fresh(self):
        self.assertTrue(is_fresh(self._cache_at(1), 24, now=self.now))

    def test_at_boundary_is_stale(self):
        self.assertFalse(is_fresh(self._cache_at(24), 24, now=self.now))

    def test_beyond_ttl_is_stale(self):
        self.assertFalse(is_fresh(self._cache_at(25), 24, now=self.now))

    def test_missing_fetched_at_is_stale(self):
        self.assertFalse(is_fresh({}, 24, now=self.now))
        self.assertFalse(is_fresh({"fetched_at": ""}, 24, now=self.now))

    def test_unparseable_is_stale(self):
        self.assertFalse(is_fresh({"fetched_at": "not-a-date"}, 24, now=self.now))

    def test_future_fetched_at_is_stale(self):
        self.assertFalse(is_fresh(self._cache_at(-5), 24, now=self.now))


class TestEmit(unittest.TestCase):
    """T-007: emit writes the cache payload (FR-001, FR-006, FR-008, NFR-005)."""

    def test_build_cache_and_emit_roundtrip(self):
        fetched_at = "2026-08-29T00:00:00Z"
        models = {"kimi-k3": {"in": 3.0, "out": 15.0, "tokenizer": "hf:tok", "source": "override"}}
        payload = build_cache(models, 24, fetched_at, "fresh")
        self.assertEqual(payload["fetched_at"], fetched_at)
        self.assertEqual(payload["ttl_hours"], 24)
        self.assertEqual(payload["freshness"], "fresh")
        self.assertIn("kimi-k3", payload["models"])

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "cache", "pricing.json")
            emit(payload, out)
            self.assertTrue(os.path.exists(out))
            with open(out, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
        self.assertEqual(loaded["freshness"], "fresh")
        self.assertEqual(loaded["models"]["kimi-k3"]["in"], 3.0)


class TestRunOrchestration(unittest.TestCase):
    """T-008: end-to-end orchestration and exit-code mapping (FR-002..FR-005)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_path = os.path.join(self.tmp.name, "cache", "pricing.json")
        self.overrides_path = os.path.join(self.tmp.name, "overrides.json")
        self.now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _write_cache(self, hours_ago, freshness="fresh", models=None):
        payload = build_cache(
            models or {"m": {"in": 1.0, "out": 2.0, "tokenizer": "tok"}},
            24,
            (self.now - timedelta(hours=hours_ago)).isoformat(),
            freshness,
        )
        emit(payload, self.cache_path)

    def _ok_fetcher(self, doc):
        def fetcher(url):
            return json.dumps(doc)
        return fetcher

    def _raising_fetcher(self, url):
        raise OSError("network down")

    def test_cache_hit_zero_network_exit0(self):
        self._write_cache(1)
        called = []
        def fetcher(url):
            called.append(url)
            raise AssertionError("network should not be called on cache hit")
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=fetcher, litellm_fetcher=fetcher, now=self.now,
        )
        self.assertEqual(code, 0)
        self.assertEqual(called, [])

    def test_refresh_writes_fresh_exit0(self):
        # overrides supplies tokenizer; external layers supply prices.
        with open(self.overrides_path, "w", encoding="utf-8") as fh:
            json.dump({"model-a": {"tokenizer": "hf:tok"}}, fh)
        openrouter = {"data": [{"id": "model-a", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]}
        litellm = {"model-a": {"input_cost_per_token": 0.000003, "output_cost_per_token": 0.000015}}
        or_calls, ll_calls = [], []
        def or_fetcher(url):
            or_calls.append(url)
            return json.dumps(openrouter)
        def ll_fetcher(url):
            ll_calls.append(url)
            return json.dumps(litellm)
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=or_fetcher, litellm_fetcher=ll_fetcher, now=self.now,
        )
        self.assertEqual(code, 0)
        # T-010: both sources were fetched (FR-003).
        self.assertEqual(len(or_calls), 1)
        self.assertEqual(len(ll_calls), 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            cache = json.load(fh)
        self.assertEqual(cache["freshness"], "fresh")
        # A price-less override inherits from the catalog row it resolved to, so
        # `source` names that layer rather than claiming to be authoritative.
        self.assertEqual(cache["models"]["model-a"]["in"], 3.0)
        self.assertEqual(cache["models"]["model-a"]["tokenizer"], "hf:tok")
        self.assertEqual(cache["models"]["model-a"]["source"], "openrouter")

    OPENROUTER_GPT52 = {"data": [{"id": "openai/gpt-5.2",
                                  "pricing": {"prompt": "0.00000175", "completion": "0.000014"}}]}

    def _run_with_override(self, override):
        with open(self.overrides_path, "w", encoding="utf-8") as fh:
            json.dump({"gpt-5.2": override}, fh)
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=self._ok_fetcher(self.OPENROUTER_GPT52),
            litellm_fetcher=self._ok_fetcher({}), now=self.now,
        )
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            return code, json.load(fh)

    def test_review_ids_rolled_up_in_payload(self):
        _, cache = self._run_with_override({"tokenizer": "tok", "in": 0.4, "out": 1.6})
        self.assertEqual(cache["needs_review"], ["gpt-5.2"])

    def test_unattested_price_is_replaced_by_catalog(self):
        # The whole point: a stale transcription cannot survive a refresh.
        code, cache = self._run_with_override({"tokenizer": "tok", "in": 0.4, "out": 1.6})
        self.assertEqual(code, 1)
        entry = cache["models"]["gpt-5.2"]
        self.assertEqual(entry["in"], 1.75)
        self.assertEqual(entry["source"], "openrouter")
        self.assertEqual(entry["review"], "unattested-price-ignored")

    def test_emitted_attested_override_carries_catalog_and_drift(self):
        code, cache = self._run_with_override({
            "tokenizer": "tok", "in": 0.4, "out": 1.6, "negotiated": True,
            "note": "direct vendor rate", "verified_at": "2025-12-01"})
        self.assertEqual(code, 0)
        entry = cache["models"]["gpt-5.2"]
        self.assertEqual(entry["in"], 0.4)
        self.assertEqual(entry["source"], "override")
        self.assertEqual(entry["catalog"]["slug"], "openai/gpt-5.2")
        self.assertEqual(entry["catalog"]["out"], 14.0)
        self.assertIn("out", entry["drift"])

    def _run_catalogless(self, override):
        with open(self.overrides_path, "w", encoding="utf-8") as fh:
            json.dump({"only": override}, fh)
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=self._ok_fetcher({"data": []}),
            litellm_fetcher=self._ok_fetcher({}), now=self.now,
        )
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            return code, json.load(fh)

    def test_attested_override_only_model_source_is_override(self):
        code, cache = self._run_catalogless({
            "in": 1.0, "out": 2.0, "tokenizer": "tok", "negotiated": True,
            "note": "private deployment", "verified_at": "2025-12-01"})
        self.assertEqual(code, 0)
        self.assertEqual(cache["models"]["only"]["source"], "override")

    def test_unverifiable_price_survives_but_is_flagged(self):
        # No catalog row to fall back to, so the price stands — but a number
        # nothing can check is exactly what needs a human to attest it.
        code, cache = self._run_catalogless({"in": 1.0, "out": 2.0, "tokenizer": "tok"})
        self.assertEqual(code, 1)
        self.assertEqual(cache["models"]["only"]["in"], 1.0)
        self.assertEqual(cache["models"]["only"]["review"], "unverifiable-price")

    def test_source_failure_serves_stale_exit1(self):
        self._write_cache(48, freshness="fresh")
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=self._raising_fetcher,
            litellm_fetcher=self._ok_fetcher({"data": []}), now=self.now,
        )
        self.assertEqual(code, 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            cache = json.load(fh)
        self.assertEqual(cache["freshness"], "stale")

    def test_source_failure_no_cache_exit2(self):
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=self._raising_fetcher,
            litellm_fetcher=self._ok_fetcher({"data": []}), now=self.now,
        )
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_all_invalid_entries_exit2_no_write(self):
        # Sources succeed but produce no tokenizer-bearing models -> nothing valid.
        openrouter = {"data": [{"id": "m", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]}
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=self._ok_fetcher(openrouter),
            litellm_fetcher=self._ok_fetcher({}), now=self.now,
        )
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.cache_path))


_network_guard = None


def setUpModule():
    # Hermeticity (NFR-002): fail loudly if any test reaches the real HTTP fetcher.
    global _network_guard
    _network_guard = mock.patch(
        "urllib.request.urlopen",
        side_effect=AssertionError("network access forbidden in tests"),
    )
    _network_guard.start()


def tearDownModule():
    if _network_guard is not None:
        _network_guard.stop()


class QueryTestBase(unittest.TestCase):
    """Shared fixtures for query tests: temp paths, fake fetchers, fixed clock."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_path = os.path.join(self.tmp.name, "cache", "pricing.json")
        self.overrides_path = os.path.join(self.tmp.name, "overrides.json")
        self.discovery_path = os.path.join(self.tmp.name, "cache", "discovery.json")
        self.now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _args(self, action, model=None, offline=False):
        return argparse.Namespace(command="query", action=action, model=model, offline=offline)

    def _write_cache(self, hours_ago, models=None, ttl=24):
        payload = build_cache(
            models or {"kimi-k3": {"in": 3.0, "out": 15.0, "tokenizer": "hf:x", "source": "override"}},
            ttl,
            (self.now - timedelta(hours=hours_ago)).isoformat(),
            "fresh",
        )
        emit(payload, self.cache_path)

    def _write_discovery(self, hours_ago, litellm=None, openrouter=None, ttl=24):
        payload = {
            "fetched_at": (self.now - timedelta(hours=hours_ago)).isoformat(),
            "ttl_hours": ttl,
            "litellm": litellm or {},
            "openrouter": openrouter or {},
        }
        os.makedirs(os.path.dirname(self.discovery_path), exist_ok=True)
        with open(self.discovery_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _run(self, action, model=None, offline=False, or_fetcher=None, ll_fetcher=None):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = query_main(
                self._args(action, model, offline),
                openrouter_fetcher=or_fetcher or self._raising,
                litellm_fetcher=ll_fetcher or self._raising,
                now=self.now,
                cache_path=self.cache_path,
                overrides_path=self.overrides_path,
                discovery_path=self.discovery_path,
            )
        return code, json.loads(out.getvalue())

    @staticmethod
    def _raising(url):
        raise AssertionError("network forbidden")


class TestNormalizeModel(unittest.TestCase):
    def test_provider_prefix_stripped(self):
        self.assertEqual(_normalize_model("databricks/databricks-gemini-3-1-pro"), "databricks-gemini-3.1-pro")

    def test_version_dash_unified(self):
        self.assertEqual(_normalize_model("gemini-3-7-flash"), "gemini-3.7-flash")

    def test_batch_suffix_preserved(self):
        self.assertNotEqual(_normalize_model("google/gemini-3.7-flash:batch"),
                            _normalize_model("google/gemini-3.7-flash"))


class TestQueryPrice(QueryTestBase):
    def test_cached_authoritative(self):
        self._write_cache(1)
        code, data = self._run("price", "kimi-k3", offline=True)
        self.assertEqual(code, 0)
        self.assertEqual(data["in"], 3.0)
        self.assertFalse(data["baseline"])
        self.assertEqual(data["source"], "override")
        self.assertEqual(data["freshness"], "fresh")

    def test_discovery_fallback_labeled_baseline(self):
        self._write_cache(1)
        self._write_discovery(1, litellm={"google/gemini-3.7-flash": {"in": 0.75, "out": 3.75, "source": "litellm"}})
        code, data = self._run("price", "gemini-3.7-flash", offline=True)
        self.assertEqual(code, 0)
        self.assertTrue(data["baseline"])
        self.assertEqual(data["source"], "litellm")
        self.assertNotIn("tokenizer", data)

    def test_not_found_offline(self):
        self._write_cache(1)
        code, data = self._run("price", "no-such-model", offline=True)
        self.assertEqual(code, 2)
        self.assertFalse(data["found"])

    def test_stale_cache_served_offline_exit1(self):
        self._write_cache(48)
        code, data = self._run("price", "kimi-k3", offline=True)
        self.assertEqual(code, 1)
        self.assertEqual(data["freshness"], "stale")

    def test_auto_refresh_when_stale(self):
        # No cache; online query with fake fetchers -> refresh writes the cache,
        # then the answer comes back authoritative + fresh.
        with open(self.overrides_path, "w", encoding="utf-8") as fh:
            json.dump({"gpt-4o": {"tokenizer": "tiktoken:o200k_base"}}, fh)
        or_fetcher = lambda u: json.dumps({"data": [{"id": "gpt-4o", "pricing": {"prompt": "0.000003", "completion": "0.00001"}}]})
        ll_fetcher = lambda u: json.dumps({"gpt-4o": {"input_cost_per_token": 0.0000025, "output_cost_per_token": 0.00001}})
        code, data = self._run("price", "gpt-4o", or_fetcher=or_fetcher, ll_fetcher=ll_fetcher)
        self.assertEqual(code, 0)
        # Inherited from the resolved OpenRouter row (3.0), not LiteLLM's 2.5:
        # the price and the `catalog` row it is compared against must agree.
        self.assertEqual(data["in"], 3.0)
        self.assertFalse(data["baseline"])
        self.assertTrue(os.path.exists(self.cache_path))
        self.assertTrue(os.path.exists(self.discovery_path))


class TestQueryCheapest(QueryTestBase):
    def test_variants_and_dash_naming(self):
        self._write_cache(1)
        self._write_discovery(1, litellm={
            "databricks/databricks-gemini-3-1-pro": {"in": 2.5, "out": 15.0, "source": "litellm"},
            "deepinfra/google/gemini-3.1-pro": {"in": 2.0, "out": 12.0, "source": "litellm"},
            "google/gemini-3.1-pro": {"in": 2.0, "out": 12.0, "source": "litellm"},
        })
        code, data = self._run("cheapest", "gemini-3.1-pro", offline=True)
        self.assertEqual(code, 0)
        self.assertEqual(data["in"], 2.0)
        self.assertIn(data["provider"], ("deepinfra/google/gemini-3.1-pro", "google/gemini-3.1-pro"))
        self.assertEqual(data["variants"], 3)

    def test_no_variants_exit2(self):
        self._write_cache(1)
        code, data = self._run("cheapest", "no-such-model", offline=True)
        self.assertEqual(code, 2)
        self.assertFalse(data["found"])


class TestQueryListFresh(QueryTestBase):
    def test_list_labels_authoritative_and_baseline(self):
        self._write_cache(1, models={"kimi-k3": {"in": 3.0, "out": 15.0, "tokenizer": "hf:x", "source": "override"}})
        self._write_discovery(1, litellm={"google/gemini-3.7-flash": {"in": 0.75, "out": 3.75, "source": "litellm"}})
        code, data = self._run("list", offline=True)
        self.assertEqual(code, 0)
        by_model = {m["model"]: m for m in data["models"]}
        self.assertFalse(by_model["kimi-k3"]["baseline"])
        self.assertTrue(by_model["google/gemini-3.7-flash"]["baseline"])

    def test_fresh_action(self):
        self._write_cache(1)
        code, data = self._run("fresh", offline=True)
        self.assertEqual(code, 0)
        self.assertEqual(data["freshness"], "fresh")
        self.assertEqual(data["ttl_hours"], 24)

    def test_fresh_stale_exit1(self):
        self._write_cache(48)
        code, data = self._run("fresh", offline=True)
        self.assertEqual(code, 1)
        self.assertEqual(data["freshness"], "stale")

    def test_fresh_no_data_exit2(self):
        code, data = self._run("fresh", offline=True)
        self.assertEqual(code, 2)
        self.assertEqual(data["freshness"], "no-data")


class TestQueryOffline(QueryTestBase):
    def test_offline_never_calls_fetchers(self):
        # Raising fetchers: any network attempt would fail the test.
        self._write_cache(1)
        code, _ = self._run("price", "kimi-k3", offline=True)
        self.assertEqual(code, 0)
        code, _ = self._run("list", offline=True)
        self.assertEqual(code, 0)
        code, _ = self._run("fresh", offline=True)
        self.assertEqual(code, 0)
        code, _ = self._run("cheapest", "kimi-k3", offline=True)
        self.assertIn(code, (0, 1, 2))

    def test_online_unknown_model_fetches_discovery(self):
        # Online query for an uncached model fetches discovery layers (fakes).
        self._write_cache(1)
        or_fetcher = lambda u: json.dumps({"data": []})
        ll_fetcher = lambda u: json.dumps({"model-x": {"input_cost_per_token": 0.000001, "output_cost_per_token": 0.000002}})
        code, data = self._run("price", "model-x", or_fetcher=or_fetcher, ll_fetcher=ll_fetcher)
        self.assertEqual(code, 0)
        self.assertTrue(data["baseline"])
        self.assertTrue(os.path.exists(self.discovery_path))


class TestEndpointsCheapest(QueryTestBase):
    """US1 (002): OpenRouter per-provider endpoints as primary cheapest source."""

    def setUp(self):
        super().setUp()
        self.endpoints_dir = os.path.join(self.tmp.name, "cache", "endpoints")

    def _k3_catalog_sidecar(self):
        self._write_discovery(1, openrouter={"moonshotai/kimi-k3": {"in": 3.0, "out": 15.0, "source": "openrouter"}})

    def _k3_endpoints_doc(self):
        return json.dumps({"data": {"endpoints": [
            {"provider_name": "Makora", "tag": "makora", "quantization": "unknown",
             "pricing": {"prompt": "0.00000255", "completion": "0.00001275", "input_cache_read": "0.0000005"}},
            {"provider_name": "DeepInfra", "tag": "deepinfra", "quantization": "bf16",
             "pricing": {"prompt": "0.00000285", "completion": "0.00001425"}},
        ]}})

    def _run(self, action, model=None, offline=False, or_fetcher=None, ll_fetcher=None):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = query_main(
                self._args(action, model, offline),
                openrouter_fetcher=or_fetcher or self._raising,
                litellm_fetcher=ll_fetcher or self._raising,
                now=self.now,
                cache_path=self.cache_path,
                overrides_path=self.overrides_path,
                discovery_path=self.discovery_path,
                endpoints_dir=self.endpoints_dir,
            )
        return code, json.loads(out.getvalue())

    def test_endpoints_primary_with_quantization(self):
        self._write_cache(1)
        self._k3_catalog_sidecar()
        code, data = self._run("cheapest", "kimi-k3", or_fetcher=lambda u: self._k3_endpoints_doc())
        self.assertEqual(code, 0)
        self.assertEqual(data["source"], "openrouter-endpoints")
        self.assertEqual(data["slug"], "moonshotai/kimi-k3")
        self.assertEqual(data["provider"], "Makora")
        self.assertEqual(data["in"], 2.55)
        self.assertEqual(data["quantization"], "unknown")
        self.assertEqual(data["in_cache_read"], 0.5)
        self.assertEqual(data["variants"], 2)
        self.assertTrue(data["baseline"])

    def test_snapshot_cache_hit_zero_network(self):
        self._write_cache(1)
        self._k3_catalog_sidecar()
        path = _endpoint_snapshot_path("moonshotai/kimi-k3", self.endpoints_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        snap = {"fetched_at": self.now.isoformat(), "ttl_hours": 24, "slug": "moonshotai/kimi-k3",
                "endpoints": [{"provider_name": "Makora", "tag": "makora", "quantization": "unknown",
                                "in": 2.55, "out": 12.75}]}
        json.dump(snap, open(path, "w"))
        code, data = self._run("cheapest", "kimi-k3", offline=False)
        self.assertEqual(code, 0)
        self.assertEqual(data["provider"], "Makora")

    def test_stale_snapshot_offline_served_exit1(self):
        self._write_cache(1)
        self._k3_catalog_sidecar()
        path = _endpoint_snapshot_path("moonshotai/kimi-k3", self.endpoints_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        snap = {"fetched_at": (self.now - timedelta(hours=48)).isoformat(), "ttl_hours": 24,
                "slug": "moonshotai/kimi-k3",
                "endpoints": [{"provider_name": "Makora", "tag": "makora", "quantization": "unknown",
                                "in": 2.55, "out": 12.75}]}
        json.dump(snap, open(path, "w"))
        code, data = self._run("cheapest", "kimi-k3", offline=True)
        self.assertEqual(code, 1)
        self.assertEqual(data["provider"], "Makora")
        self.assertEqual(data["freshness"], "stale")

    def test_no_slug_falls_back_to_variant_scan(self):
        self._write_cache(1)
        self._write_discovery(1, litellm={"zai/glm-5.2": {"in": 0.46, "out": 1.45, "source": "litellm"}},
                              openrouter={})
        code, data = self._run("cheapest", "glm-5.2", offline=True)
        self.assertEqual(code, 0)
        self.assertTrue(data["fallback"])
        self.assertEqual(data["source"], "litellm")

    def test_endpoints_fetch_failure_falls_back(self):
        self._write_cache(1)
        self._k3_catalog_sidecar()
        self._write_discovery(1, litellm={"moonshotai/kimi-k3": {"in": 3.0, "out": 15.0, "source": "litellm"}},
                              openrouter={"moonshotai/kimi-k3": {"in": 3.0, "out": 15.0, "source": "openrouter"}})
        code, data = self._run("cheapest", "kimi-k3", or_fetcher=self._raising)
        self.assertEqual(code, 0)
        self.assertTrue(data["fallback"])

    def test_override_slug_resolution(self):
        self._write_cache(1)
        self._write_discovery(1, openrouter={"moonshotai/kimi-k3-special": {"in": 3.0, "out": 15.0, "source": "openrouter"}})
        with open(self.overrides_path, "w", encoding="utf-8") as fh:
            json.dump({"kimi-k3": {"openrouter_slug": "moonshotai/kimi-k3-special"}}, fh)
        code, data = self._run("cheapest", "kimi-k3", or_fetcher=lambda u: self._k3_endpoints_doc())
        self.assertEqual(code, 0)
        self.assertEqual(data["slug"], "moonshotai/kimi-k3-special")


class TestBaselineCacheFields(unittest.TestCase):
    """US2 (002): richer OpenRouter baseline fields."""

    def test_cache_fields_captured(self):
        doc = {"data": [{"id": "openai/gpt-4o",
                         "pricing": {"prompt": "0.0000025", "completion": "0.00001",
                                     "input_cache_read": "0.000001", "input_cache_write": "0.000003",
                                     "overrides": {"some": "policy"}}}]}
        layer = _normalize_openrouter(doc)
        entry = layer["openai/gpt-4o"]
        self.assertEqual(entry["in_cache_read"], 1.0)
        self.assertEqual(entry["in_cache_write"], 3.0)
        self.assertTrue(entry["has_pricing_overrides"])

    def test_no_cache_fields_when_absent(self):
        doc = {"data": [{"id": "openai/gpt-4o",
                         "pricing": {"prompt": "0.0000025", "completion": "0.00001"}}]}
        entry = _normalize_openrouter(doc)["openai/gpt-4o"]
        self.assertNotIn("in_cache_read", entry)
        self.assertNotIn("has_pricing_overrides", entry)


if __name__ == "__main__":
    unittest.main()


class TestOverridesFileDocumentation(unittest.TestCase):
    def test_underscore_keys_are_not_models(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "overrides.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"_comment": "docs", "m": {"tokenizer": "tok"}}, fh)
            self.assertEqual(list(load_overrides(path)), ["m"])


class TestReviewSurvivesCacheHit(unittest.TestCase):
    """A review flag must not go silent for the whole TTL window on a cache hit."""

    def test_fresh_cached_review_still_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            cache_path = os.path.join(d, "pricing.json")
            emit(build_cache({"m": {"in": 1.0, "out": 2.0, "tokenizer": "tok"}},
                             24, _now_iso(), "fresh", ["m"]), cache_path)
            def boom(url):
                raise AssertionError("cache-hit path must not touch the network")
            code = run(cache_path=cache_path, openrouter_fetcher=boom, litellm_fetcher=boom)
            self.assertEqual(code, 1)

    def test_fresh_cached_without_review_exits_0(self):
        with tempfile.TemporaryDirectory() as d:
            cache_path = os.path.join(d, "pricing.json")
            emit(build_cache({"m": {"in": 1.0, "out": 2.0, "tokenizer": "tok"}},
                             24, _now_iso(), "fresh"), cache_path)
            self.assertEqual(run(cache_path=cache_path), 0)


class TestPartialSourceOutage(unittest.TestCase):
    """LiteLLM is a demoted fallback; losing it must not void a healthy refresh."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cache_path = os.path.join(self.dir.name, "pricing.json")
        self.discovery_path = os.path.join(self.dir.name, "discovery.json")
        self.overrides_path = os.path.join(self.dir.name, "overrides.json")
        with open(self.overrides_path, "w", encoding="utf-8") as fh:
            json.dump({"m": {"tokenizer": "tok", "openrouter_slug": "x/m"}}, fh)
        self.openrouter = json.dumps(
            {"data": [{"id": "x/m", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]})

    @staticmethod
    def _down(url):
        raise OSError("source unavailable")

    def test_litellm_outage_still_refreshes(self):
        code = run(cache_path=self.cache_path, overrides_path=self.overrides_path,
                   discovery_path=self.discovery_path,
                   openrouter_fetcher=lambda u: self.openrouter, litellm_fetcher=self._down)
        self.assertEqual(code, 0)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["models"]["m"]["in"], 3.0)

    def test_litellm_outage_reuses_last_known_layer(self):
        with open(self.discovery_path, "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": _now_iso(), "openrouter": {},
                       "litellm": {"legacy": {"in": 9.0, "out": 9.0}}}, fh)
        run(cache_path=self.cache_path, overrides_path=self.overrides_path,
            discovery_path=self.discovery_path,
            openrouter_fetcher=lambda u: self.openrouter, litellm_fetcher=self._down)
        with open(self.discovery_path, "r", encoding="utf-8") as fh:
            self.assertIn("legacy", json.load(fh)["litellm"])

    def test_openrouter_outage_still_falls_back_to_stale(self):
        # The catalog is load-bearing for slug resolution and price inheritance.
        code = run(cache_path=self.cache_path, overrides_path=self.overrides_path,
                   openrouter_fetcher=self._down, litellm_fetcher=lambda u: json.dumps({}))
        self.assertEqual(code, 2)


class TestAtomicWrite(unittest.TestCase):
    def test_emit_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache", "pricing.json")
            emit(build_cache({}, 24, _now_iso(), "fresh"), path)
            self.assertEqual(os.listdir(os.path.dirname(path)), ["pricing.json"])

    def test_failed_write_does_not_clobber_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pricing.json")
            emit(build_cache({"a": {"in": 1.0}}, 24, _now_iso(), "fresh"), path)
            unserializable = {"models": {"x": object()}}
            with self.assertRaises(TypeError):
                emit(unserializable, path)
            with open(path, "r", encoding="utf-8") as fh:
                self.assertIn("a", json.load(fh)["models"])
            self.assertEqual(os.listdir(d), ["pricing.json"])


class TestCliWiring(unittest.TestCase):
    def test_plain_run_refreshes_the_discovery_sidecar(self):
        with mock.patch("fetch_pricing.run", return_value=0) as fake_run:
            main(["--force"])
        self.assertEqual(fake_run.call_args.kwargs["discovery_path"], DISCOVERY_PATH)

    def test_query_honours_ttl_hours(self):
        with tempfile.TemporaryDirectory() as d:
            cache_path = os.path.join(d, "pricing.json")
            now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            two_hours_old = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            emit(build_cache({}, 24, two_hours_old, "fresh"), cache_path)

            def freshness_with(ttl):
                args = argparse.Namespace(action="fresh", model=None, offline=True,
                                          ttl_hours=ttl)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    query_main(args, now=now, cache_path=cache_path,
                               discovery_path=os.path.join(d, "discovery.json"))
                return json.loads(buf.getvalue())["freshness"]

            self.assertEqual(freshness_with(24), "fresh")
            self.assertEqual(freshness_with(1), "stale")

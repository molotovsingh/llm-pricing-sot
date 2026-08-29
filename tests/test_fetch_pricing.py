"""Unit tests for the fetch_pricing CLI argument parsing (T-001)."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import urllib.request

from fetch_pricing import (
    DEFAULT_TTL_HOURS,
    build_cache,
    emit,
    fetch_litellm,
    fetch_openrouter,
    filter_valid,
    is_fresh,
    load_overrides,
    merge,
    parse_args,
    run,
    validate_entry,
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
        self.assertEqual(cache["models"]["model-a"]["in"], 3.0)  # from litellm
        self.assertEqual(cache["models"]["model-a"]["tokenizer"], "hf:tok")
        self.assertEqual(cache["models"]["model-a"]["source"], "override")

    def test_override_only_model_source_is_override(self):
        # A model present only in overrides gets source=override (not null).
        with open(self.overrides_path, "w", encoding="utf-8") as fh:
            json.dump({"only": {"in": 1.0, "out": 2.0, "tokenizer": "tok"}}, fh)
        code = run(
            cache_path=self.cache_path, overrides_path=self.overrides_path,
            openrouter_fetcher=self._ok_fetcher({"data": []}),
            litellm_fetcher=self._ok_fetcher({}), now=self.now,
        )
        self.assertEqual(code, 0)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            cache = json.load(fh)
        self.assertEqual(cache["models"]["only"]["source"], "override")

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


if __name__ == "__main__":
    unittest.main()

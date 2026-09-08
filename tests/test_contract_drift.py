"""Contract drift gate, and the generator that repairs it.

Three normative facts -- exit-code meanings, the cache envelope schema, and the
trust rule -- are restated across several documents. They are derived here from
the running code and compared against a marked block in each governed document,
so a behaviour change cannot leave a reader silently wrong.

Gate:      python -m unittest discover -s tests
Generator: python tests/test_contract_drift.py --fix

The generator never runs during the test run: a gate that repairs itself would
hide the drift it exists to report.
"""

import argparse
import ast
import contextlib
import fnmatch
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import fetch_pricing  # noqa: E402  (path must be set first)


# --------------------------------------------------------------------------
# Facts: derived from the running code, never from a document.
# --------------------------------------------------------------------------

def derive_exit_codes():
    """Enumerate _exit_for over its whole domain."""
    return [(freshness, degraded, fetch_pricing._exit_for(freshness, degraded))
            for freshness in ("fresh", "stale", "no-data")
            for degraded in (False, True)]


def render_exit_codes():
    lines = ["| freshness | degraded | exit |", "|---|---|---|"]
    for freshness, degraded, code in derive_exit_codes():
        lines.append(f"| `{freshness}` | {'yes' if degraded else 'no'} | `{code}` |")
    lines.append("")
    lines.append("`0` clean · `1` served but degraded (stale **or** the answer's entry "
                 "is in `needs_review`) · `2` no usable data.")
    return "\n".join(lines)


def derive_envelope():
    return sorted(fetch_pricing.build_cache({}, 24, fetch_pricing._now_iso(), "fresh"))


def render_envelope():
    keys = ", ".join(f"`{k}`" for k in derive_envelope())
    return f"Cache envelope keys: {keys}."


def derive_units():
    """The unit vocabulary, straight from the code that validates against it."""
    return [(unit, spec["fields"], spec["buys"]) for unit, spec in fetch_pricing.UNITS.items()]


def render_units():
    lines = ["| unit | price fields | one unit buys |", "|---|---|---|"]
    for unit, fields, buys in derive_units():
        lines.append(f"| `{unit}` | {', '.join(f'`{f}`' for f in fields)} | {buys} |")
    lines.append("")
    lines.append("Per-token prices are USD per 1M tokens. A unit's fields are never reused "
                 "for another unit, so a consumer that multiplies `in`/`out` by a token "
                 "count cannot pick up a per-page price by mistake.")
    return "\n".join(lines)


def render_trust_rule():
    return "\n".join([
        "- `baseline: false` → the model is tracked by the SOT; use this price.",
        "- `source` explains provenance only — `override` is an attested rate,",
        "  `openrouter`/`litellm` is the live catalog price. **`source` does not gate trust.**",
        "- `baseline: true` → discovery data, not a tracked model; informational only.",
        "- `degraded: true` → usable but stale or in `needs_review`.",
    ])


FACTS = {
    "exit-codes": render_exit_codes,
    "envelope": render_envelope,
    "trust-rule": render_trust_rule,
    "units": render_units,
}


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

GOVERNED = {
    "skills/llm-pricing/SKILL.md": ("exit-codes", "trust-rule", "units"),
    "README.md": ("exit-codes", "envelope", "trust-rule", "units"),
    ".specify/memory/constitution.md": ("exit-codes", "envelope", "units"),
    "specs/001-pricing-query/contracts/query-cli.md": ("exit-codes",),
    "specs/001-pricing-query/quickstart.md": ("exit-codes", "trust-rule"),
    "specs/002-pricing-endpoints/contracts/cheapest-query.md": ("exit-codes",),
    "specs/005-cost-per-unit/contracts/deployments-and-hosts.md": ("units",),
}

# Exempt by declared path rule, never by inference from content (FR-006).
HISTORICAL_PATTERNS = ("specs/*/research.md", "specs/*/spec.md")


def is_historical(rel_path):
    return any(fnmatch.fnmatch(rel_path, pat) for pat in HISTORICAL_PATTERNS)


# --------------------------------------------------------------------------
# Block recognition (research.md R5)
# --------------------------------------------------------------------------

# CommonMark allows both fence characters. Matching only ``` would let a
# ~~~-fenced example toggle nothing, so a marker inside it would count as real.
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")

BEGIN_RE = re.compile(r"^<!-- contract:begin ([A-Za-z0-9_-]+) -->$")
END_RE = re.compile(r"^<!-- contract:end ([A-Za-z0-9_-]+) -->$")


class BlockError(Exception):
    """A malformed or unknown contract block -- always a hard failure."""


def find_blocks(text):
    """Return {fact_id: body} for real blocks only.

    A marker is real when it sits at column 0 and outside any fenced code block.
    The `<fact-id>` placeholder used in documentation fails the marker regex
    (angle brackets), so examples are excluded twice over.

    A recognised marker carrying an unknown fact id is a typo, not an example,
    and raises -- otherwise a misspelling would silently disable a check.
    """
    blocks, fenced, open_id, body = {}, False, None, []
    for lineno, line in enumerate(text.splitlines(), 1):
        if _FENCE_RE.match(line):
            fenced = not fenced
            if open_id is not None:
                body.append(line)
            continue
        if fenced:
            if open_id is not None:
                body.append(line)
            continue

        begin = BEGIN_RE.match(line)
        if begin:
            fact_id = begin.group(1)
            if fact_id not in FACTS:
                raise BlockError(f"line {lineno}: unknown fact id {fact_id!r}")
            if open_id is not None:
                raise BlockError(f"line {lineno}: block {fact_id!r} nested inside {open_id!r}")
            if fact_id in blocks:
                raise BlockError(f"line {lineno}: duplicate block {fact_id!r}")
            open_id, body = fact_id, []
            continue

        end = END_RE.match(line)
        if end:
            fact_id = end.group(1)
            if fact_id not in FACTS:
                raise BlockError(f"line {lineno}: unknown fact id {fact_id!r}")
            if open_id != fact_id:
                raise BlockError(f"line {lineno}: end {fact_id!r} without matching begin")
            blocks[open_id], open_id = "\n".join(body), None
            continue

        if open_id is not None:
            body.append(line)

    if open_id is not None:
        raise BlockError(f"unterminated block {open_id!r}")
    return blocks


def normalize(body):
    """Collapse line endings and trailing whitespace. Nothing else."""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


# --------------------------------------------------------------------------
# Generator (never invoked from a test)
# --------------------------------------------------------------------------

def rewrite_blocks(text):
    """Return text with every recognised block replaced by its canonical body."""
    out, fenced, open_id = [], False, None
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            fenced = not fenced
            if open_id is None:
                out.append(line)
            continue
        if fenced:
            if open_id is None:
                out.append(line)
            continue

        begin = BEGIN_RE.match(line)
        if begin and begin.group(1) in FACTS:
            open_id = begin.group(1)
            out.append(line)
            out.extend(FACTS[open_id]().split("\n"))
            continue

        end = END_RE.match(line)
        if end and end.group(1) in FACTS and open_id == end.group(1):
            open_id = None
            out.append(line)
            continue

        if open_id is None:
            out.append(line)

    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + trailing


def fix(repo_root=REPO_ROOT, stream=sys.stdout):
    """Write canonical blocks into every registered live document."""
    changed, missing = [], []
    for rel, required in sorted(GOVERNED.items()):
        path = repo_root / rel
        if not path.exists():
            print(f"missing file: {rel}", file=stream)
            continue
        original = path.read_text(encoding="utf-8")
        present = set(find_blocks(original))
        absent = [f for f in required if f not in present]
        if absent:
            missing.append((rel, absent))
        updated = rewrite_blocks(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(rel)
    for rel in changed:
        print(f"updated: {rel}", file=stream)
    for rel, absent in missing:
        print(f"missing block(s) in {rel}: {', '.join(absent)} "
              f"-- placement is an editorial choice, insert the markers by hand",
              file=stream)
    if not changed and not missing:
        print("all governed documents already current", file=stream)
    return 1 if missing else 0


# --------------------------------------------------------------------------
# Gate
# --------------------------------------------------------------------------

class TestGovernedDocuments(unittest.TestCase):
    """Every live document's blocks must match the derived facts."""

    def test_registered_documents_exist(self):
        for rel in GOVERNED:
            with self.subTest(document=rel):
                self.assertTrue((REPO_ROOT / rel).exists(),
                                f"{rel} is registered but missing -- a rename must not "
                                f"silently drop coverage")

    def test_required_blocks_are_present(self):
        for rel, required in GOVERNED.items():
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            present = set(find_blocks(path.read_text(encoding="utf-8")))
            for fact_id in required:
                with self.subTest(document=rel, fact=fact_id):
                    self.assertIn(fact_id, present,
                                  f"{rel} is missing its {fact_id} block -- deleting a "
                                  f"block must not be a way to opt out")

    def test_blocks_match_derived_facts(self):
        for rel, required in GOVERNED.items():
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            blocks = find_blocks(path.read_text(encoding="utf-8"))
            for fact_id in required:
                if fact_id not in blocks:
                    continue
                with self.subTest(document=rel, fact=fact_id):
                    canonical = FACTS[fact_id]()
                    self.assertEqual(
                        normalize(blocks[fact_id]), normalize(canonical),
                        f"\n\n{rel} [{fact_id}] is stale. Run "
                        f"`python tests/test_contract_drift.py --fix`, or replace the "
                        f"block with:\n\n{canonical}\n")

    def test_governed_document_count_is_reported(self):
        # Coverage should be visible in the run output, not inferred.
        print(f"\n[contract] {len(GOVERNED)} governed documents, "
              f"{len(FACTS)} facts", file=sys.stderr)


class TestUnregisteredMarkers(unittest.TestCase):
    """A real block outside the registry is how copy-paste propagation is caught."""

    @staticmethod
    def _markdown_files():
        # os.walk with descent-time pruning: never enters .git at all, and
        # constructs a Path only for actual .md hits. rglob post-filtering
        # walks the whole object tree first.
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            # Never descend into .git or autoresearch/ session worktrees: the
            # harness clones the whole repo inside autoresearch/<id>/, and those
            # copies of governed documents are enforced at their canonical
            # (registered) locations, not as separate unregistered files.
            dirnames[:] = [d for d in dirnames if d not in (".git", "autoresearch")]
            for name in filenames:
                if name.endswith(".md"):
                    yield pathlib.Path(dirpath, name)

    def test_no_real_block_in_an_unregistered_file(self):
        for path in self._markdown_files():
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in GOVERNED:
                continue
            with self.subTest(document=rel):
                self.assertEqual(
                    find_blocks(path.read_text(encoding="utf-8")), {},
                    f"{rel} carries a contract block but is not registered in GOVERNED")

    def test_feature_documentation_does_not_trip_the_guard(self):
        # The feature's own documents show the syntax in prose and code fences.
        # Recognition rules must exclude them, or the guard fails on the very
        # documents that define it. Discovered rather than listed, so the test
        # cannot go vacuous when a document stops mentioning the marker.
        feature_docs = [p for p in (REPO_ROOT / "specs" / "003-contract-single-source").rglob("*.md")
                        if "contract:begin" in p.read_text(encoding="utf-8")]
        self.assertTrue(feature_docs, "no feature document mentions the marker literal")
        for path in feature_docs:
            with self.subTest(document=path.relative_to(REPO_ROOT).as_posix()):
                self.assertEqual(find_blocks(path.read_text(encoding="utf-8")), {})

    def test_historical_documents_are_exempt(self):
        research = REPO_ROOT / "specs/001-pricing-query/research.md"
        self.assertTrue(is_historical("specs/001-pricing-query/research.md"))
        self.assertTrue(is_historical("specs/002-pricing-endpoints/spec.md"))
        self.assertFalse(is_historical("README.md"))
        if research.exists():
            # Still states a superseded rule, and must pass unchanged.
            self.assertIn("`0` fresh / `1` stale", research.read_text(encoding="utf-8"))


class TestGateFailsOnDrift(unittest.TestCase):
    """Spec acceptance US1-2 and US1-3, proved against a copy of the real skill."""

    SKILL = "skills/llm-pricing/SKILL.md"

    def setUp(self):
        path = REPO_ROOT / self.SKILL
        if not path.exists():
            self.skipTest(f"{self.SKILL} not present")
        self.original = path.read_text(encoding="utf-8")

    @staticmethod
    def _stale(text, fact_id):
        """Return text with one block's body replaced by something wrong."""
        out, inside = [], False
        for line in text.splitlines():
            if BEGIN_RE.match(line) and BEGIN_RE.match(line).group(1) == fact_id:
                out.extend([line, "WRONG"])
                inside = True
                continue
            if END_RE.match(line) and END_RE.match(line).group(1) == fact_id:
                inside = False
            if not inside:
                out.append(line)
        return "\n".join(out)

    def test_corrupted_block_is_detected(self):
        drifted = self._stale(self.original, "exit-codes")
        self.assertNotEqual(drifted, self.original, "fixture did not actually change anything")
        blocks = find_blocks(drifted)
        self.assertNotEqual(normalize(blocks["exit-codes"]),
                            normalize(render_exit_codes()),
                            "a corrupted block must not compare equal")

    def test_prose_outside_markers_may_be_reworded(self):
        reworded = self.original.replace(
            "Single source of truth repo", "Single source-of-truth repository")
        self.assertNotEqual(reworded, self.original, "fixture did not actually change anything")
        for fact_id, body in find_blocks(reworded).items():
            with self.subTest(fact=fact_id):
                self.assertEqual(normalize(body), normalize(FACTS[fact_id]()))

    def test_deleting_a_block_is_detected(self):
        stripped = "\n".join(line for line in self.original.splitlines()
                             if not BEGIN_RE.match(line) and not END_RE.match(line))
        self.assertNotIn("exit-codes", find_blocks(stripped),
                         "deleting the markers must not look like a passing document")


class TestBlockRecognition(unittest.TestCase):
    """The three R5 rules, each tested in isolation."""

    CANON = "<!-- contract:begin envelope -->\nbody\n<!-- contract:end envelope -->"

    def test_recognises_a_well_formed_block(self):
        self.assertEqual(find_blocks(self.CANON), {"envelope": "body"})

    def test_ignores_indented_marker(self):
        indented = "\n".join("  " + line for line in self.CANON.split("\n"))
        self.assertEqual(find_blocks(indented), {})

    def test_ignores_marker_inside_code_fence(self):
        self.assertEqual(find_blocks("```markdown\n" + self.CANON + "\n```"), {})

    def test_ignores_marker_inside_tilde_fence(self):
        # CommonMark allows ~~~ as well; a doc using it must not smuggle a
        # marker past the gate (or swallow a real one by never toggling).
        self.assertEqual(find_blocks("~~~markdown\n" + self.CANON + "\n~~~"), {})

    def test_tilde_fence_does_not_swallow_a_later_real_block(self):
        text = "~~~\nexample\n~~~\n\n" + self.CANON
        self.assertEqual(find_blocks(text), {"envelope": "body"})

    def test_placeholder_id_is_not_a_marker(self):
        self.assertEqual(find_blocks("<!-- contract:begin <fact-id> -->"), {})

    def test_unknown_but_well_formed_id_is_a_typo_and_raises(self):
        with self.assertRaises(BlockError):
            find_blocks("<!-- contract:begin exit-code -->\nx\n<!-- contract:end exit-code -->")

    def test_unterminated_block_raises(self):
        with self.assertRaises(BlockError):
            find_blocks("<!-- contract:begin envelope -->\nbody")

    def test_duplicate_block_raises(self):
        with self.assertRaises(BlockError):
            find_blocks(self.CANON + "\n" + self.CANON)

    def test_normalize_only_touches_whitespace(self):
        self.assertEqual(normalize("a  \r\nb\t \n"), "a\nb")
        self.assertNotEqual(normalize("a b"), normalize("a  b"))


class TestFactsDerivedFromCode(unittest.TestCase):
    def test_exit_codes_cover_the_whole_domain(self):
        self.assertEqual(len(derive_exit_codes()), 6)
        self.assertIn(("fresh", True, 1), derive_exit_codes())
        self.assertIn(("fresh", False, 0), derive_exit_codes())

    def test_envelope_matches_build_cache(self):
        self.assertEqual(derive_envelope(),
                         ["deployments", "fetched_at", "freshness", "models",
                          "needs_review", "truth_hash", "ttl_hours"])

    def test_units_fact_is_derived_from_code(self):
        rendered = render_units()
        for unit in fetch_pricing.UNITS:
            self.assertIn(f"`{unit}`", rendered)
        self.assertEqual(render_units(), render_units())

    def test_renderings_are_deterministic(self):
        for fact_id, render in FACTS.items():
            with self.subTest(fact=fact_id):
                self.assertEqual(render(), render())


class TestSourceDoesNotRestateExitCodes(unittest.TestCase):
    """The gate governs documents; nothing governed the source's own docstrings.

    `run` and `query_main` each carried an exit-code mapping that went stale when
    degradation became first-class -- inside the very file the facts are derived
    from. A marker block cannot live in a docstring, so source prose is governed
    by *absence*: reference `_exit_for`, never restate it.
    """

    # Every restatement was written as "<code> <freshness-word>": "0 fresh",
    # "1 stale cache served", "2 no data / not found".
    RESTATEMENT = re.compile(
        r"\b[012]\b[^.\n]{0,40}?\b(fresh|stale|no[- ]data|no usable)", re.IGNORECASE)
    # `_exit_for` *is* the source, and the module docstring names the schema.
    ALLOWED = {"_exit_for"}

    def _offenders(self, source):
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = getattr(node, "name", "<module>")
            if name in self.ALLOWED:
                continue
            doc = ast.get_docstring(node) or ""
            hit = self.RESTATEMENT.search(doc)
            if hit:
                found.append((name, hit.group(0)))
        return sorted(found)

    def test_no_docstring_restates_the_exit_mapping(self):
        source = (REPO_ROOT / "fetch_pricing.py").read_text(encoding="utf-8")
        self.assertEqual(
            self._offenders(source), [],
            "exit-code mapping restated in a docstring -- reference `_exit_for` instead")

    def test_the_guard_actually_catches_a_restatement(self):
        """A guard that cannot fail is decoration; prove it fires."""
        stale = ('"""Module."""\n\n'
                 'def run():\n'
                 '    """Do work.\n\n'
                 '    Exit codes: 0 fresh, 1 stale cache served, 2 no usable cache.\n'
                 '    """\n')
        self.assertEqual([n for n, _ in self._offenders(stale)], ["run"])


class TestTrustRuleHoldsOperationally(unittest.TestCase):
    """SC-005: the documented procedure must reach the code's verdict."""

    @staticmethod
    def _explode(url):
        raise AssertionError("the suite must never reach the network")

    def _run_procedure(self, cache_path):
        """Check the documented verdict against `degraded` for every model in a
        cache envelope. Returns how many `needs_review` entries were exercised."""
        models = json.loads(pathlib.Path(cache_path).read_text(encoding="utf-8"))["models"]
        self.assertTrue(models, "cache has no models to verify against")

        exercised_review = 0
        for model, entry in models.items():
            args = argparse.Namespace(action="price", model=model,
                                      offline=True, ttl_hours=24)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                fetch_pricing.query_main(args,
                                         openrouter_fetcher=self._explode,
                                         litellm_fetcher=self._explode,
                                         cache_path=str(cache_path))
            answer = json.loads(buf.getvalue())
            documented = bool(entry.get("review"))
            with self.subTest(model=model):
                self.assertEqual(answer["degraded"], documented)
                self.assertFalse(answer["baseline"])
            exercised_review += documented
        return exercised_review

    def test_documented_procedure_matches_degraded_flag(self):
        """SC-005 over the shipped cache: every model, whatever its state."""
        cache_path = REPO_ROOT / "cache" / "pricing.json"
        if not cache_path.exists():
            self.skipTest("no cache/pricing.json; run fetch_pricing.py first")
        self._run_procedure(cache_path)

    def test_procedure_matches_on_a_needs_review_entry(self):
        """SC-005's strongest case: an entry sitting in `needs_review`.

        SC-005 says "including entries in needs_review" -- a scope clause, not a
        requirement that such entries exist. A clean queue is the healthy state
        (every price either attested or inherited), so this branch is driven by
        an injected entry rather than by asserting the shipped data stays broken.
        """
        cache_path = REPO_ROOT / "cache" / "pricing.json"
        if not cache_path.exists():
            self.skipTest("no cache/pricing.json; run fetch_pricing.py first")
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        model = "contract-probe-unattested"
        cache["models"][model] = {"in": 1.0, "out": 2.0, "source": "openrouter",
                                  "review": "unattested-price-ignored"}
        cache["needs_review"] = sorted(set(cache.get("needs_review") or []) | {model})
        with tempfile.TemporaryDirectory() as d:
            injected = pathlib.Path(d) / "pricing.json"
            injected.write_text(json.dumps(cache), encoding="utf-8")
            self.assertGreater(self._run_procedure(injected), 0,
                               "the needs_review branch went untested")


class TestGenerator(unittest.TestCase):
    def _governed_copy(self, tmp):
        """A minimal tree holding one registered document with one block."""
        rel = "README.md"
        (tmp / "README.md").write_text(
            "# Title\n\nprose before\n\n"
            "<!-- contract:begin envelope -->\nSTALE\n<!-- contract:end envelope -->\n\n"
            "prose after\n", encoding="utf-8")
        return rel

    def test_fix_rewrites_only_between_markers(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            self._governed_copy(tmp)
            original = (tmp / "README.md").read_text(encoding="utf-8")
            updated = rewrite_blocks(original)
            self.assertIn(render_envelope(), updated)
            self.assertNotIn("STALE", updated)
            self.assertIn("prose before", updated)
            self.assertIn("prose after", updated)

    def test_fix_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            self._governed_copy(tmp)
            once = rewrite_blocks((tmp / "README.md").read_text(encoding="utf-8"))
            twice = rewrite_blocks(once)
            self.assertEqual(once, twice)

    def test_bytes_outside_markers_are_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            self._governed_copy(tmp)
            original = (tmp / "README.md").read_text(encoding="utf-8")
            updated = rewrite_blocks(original)
            outside = lambda t: t.split("<!-- contract:begin")[0] + t.split("-->")[-1]
            self.assertEqual(outside(original), outside(updated))

    def test_generator_is_only_reachable_from_main(self):
        # The gate must never self-heal, so the writer may only be called from
        # the __main__ guard. Checked by AST, not by string search: a source
        # scan matches its own pattern and gives a false positive.
        tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
        guard = next(node for node in tree.body
                     if isinstance(node, ast.If) and "__main__" in ast.dump(node.test))
        guarded = {n.lineno for n in ast.walk(guard) if hasattr(n, "lineno")}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "fix"):
                self.assertIn(node.lineno, guarded,
                              f"line {node.lineno}: the generator is called outside "
                              f"the __main__ guard")


class TestSkillSymlinkIsGoverned(unittest.TestCase):
    """The governed file should be the one agents actually load.

    Only the installed checkout can assert this. Any other clone skips loudly
    rather than failing -- a secondary checkout is legitimate, and failing there
    would break CI and every contributor's copy.
    """

    INSTALLED = pathlib.Path.home() / ".pi" / "agent" / "skills" / "llm-pricing"

    def _skip_loudly(self, reason):
        print(f"\n[contract] symlink unverified: {reason}", file=sys.stderr)
        self.skipTest(reason)

    def test_installed_skill_is_a_link_not_a_copy(self):
        if not self.INSTALLED.exists():
            self._skip_loudly("~/.pi/agent/skills/llm-pricing absent; agent harness "
                              "not installed on this machine")
        self.assertTrue(self.INSTALLED.is_symlink(),
                        "the installed skill is a copy, not a link -- it will drift "
                        "from the governed file the moment either is edited")

    def test_installed_skill_resolves_into_this_repo(self):
        if not self.INSTALLED.exists():
            self._skip_loudly("agent harness not installed on this machine")
        target = self.INSTALLED.resolve()
        ours = (REPO_ROOT / "skills" / "llm-pricing").resolve()
        if target != ours:
            self._skip_loudly(f"this checkout is not the installed one "
                              f"({target} is); nothing to assert here")
        self.assertEqual(target, ours)


class TestCheckerIsHermetic(unittest.TestCase):
    def test_imports_are_stdlib_only(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
        imported = set(re.findall(r"^(?:from|import) (\w+)", source, re.M))
        allowed = set(sys.stdlib_module_names) | {"fetch_pricing"}
        self.assertEqual(imported - allowed, set())

    def test_no_network_primitives_used(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
        for forbidden in ("urllib", "socket", "http.client", "requests"):
            self.assertNotIn(f"import {forbidden}", source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="test_contract_drift",
                                     description="Rewrite canonical contract blocks in place.")
    parser.add_argument("--fix", action="store_true",
                        help="write canonical blocks into every registered live document")
    parsed = parser.parse_args()
    if parsed.fix:
        raise SystemExit(fix())
    unittest.main(argv=[sys.argv[0]])

# FOR_AKSINGH — how this repo works, and what it taught us

*Written 2026-09-08, at the end of the session that refitted the repo around a new
objective. If you read one document to understand this codebase, read this one. If
you need the normative rules, they live in the constitution and the specs — this file
explains, it does not govern.*

---

## 1. The one-sentence version

**This repo answers "what does it cost me to run this model, where I actually run it?"
— and refuses to guess any number it can't trace.**

Everything else is machinery in service of that sentence: two hand-held "truth" files,
three automated catalogs that *check* the truth rather than *being* it, a cache with
freshness metadata, a tiny CLI agents can call, and a test suite that never touches
the network.

---

## 2. Why it exists (and why the "why" changed)

### The original why

LLM prices are a moving target. Every hand-typed price table you've ever seen —
including this repo's own ancestor, `llm-cost-estimator/data/pricing.json` — rots
silently. Someone types `gpt-5.2: 0.40/1.60` in August, OpenAI changes it in
September, and every cost estimate after that is quietly wrong with a confident
exit code 0.

So the first version of this repo was a **catalog fetcher**: pull prices from
OpenRouter and LiteLLM, cache them with a TTL, serve them to agents. Sensible.

### What we found when we audited it

On 2026-09-08 we did something the repo had never done to itself: we checked every
number it served against the vendor's own pricing page. Three facts fell out:

1. **Proprietary models were exact.** OpenRouter's catalog matched OpenAI, Anthropic
   and Moonshot to the cent, six for six. The catalog is trustworthy for those.
2. **Hosted open-weight models were exact too — at the data layer.** Both OpenRouter's
   endpoints API and Hugging Face's router had Together's and Baseten's prices right,
   seven for seven. But the repo could only answer "who's *cheapest*". If you ran
   GLM-5.2 on Together, `cheapest` cheerfully reported DeepInfra's $0.49/$1.56 while
   Together actually charges $1.40/$4.40. A **3× miss on the exact number you needed.**
3. **Specialist models — the OCR models you care about most — have no per-token price
   at all.** Of 100 OCR models on the Hub, 4 had any provider and 0 had a router price.
   They're sold per run (Replicate), per page (Marker), flat-rate (Featherless), or
   not at all — only self-hosted, where the cost is `GPU $/hour × seconds per page`.

### The reframe

Here's the analogy that unlocked the redesign. A catalog is like a **restaurant
menu board**: accurate for what's printed on it, and useless for the meal you cook at
home. The old repo treated the menu as the truth about what you eat. The new repo
treats *your kitchen* — the deployments you actually run — as the truth, and uses the
menu only to sanity-check the prices you claim.

Concretely: **the catalog was demoted from source of truth to verifier.** What you run
is recorded in `deployments.json`, each entry priced in its *native* unit (tokens,
pages, runs, GPU-hours). Self-hosted entries don't carry a price at all — they carry a
GPU and a measured `seconds_per_unit` from your benchmark, and the pipeline derives the
price. The catalogs cross-check whatever they *can* cross-check and stay out of the
rest.

That's spec 005. The rest of this document is how it's built.

---

## 3. The architecture, top to bottom

```
                       ┌──────────────────────────────────────────────┐
  TRUTH (hand-held,    │  overrides.json    tokenizers, catalog pins,  │
  attested, expiring)  │                    attested per-token rates   │
                       │  deployments.json  what you actually run,     │
                       │                    any unit, quoted or derived │
                       │  gpu_rates.json    $/hour per <gpu>@<provider> │
                       └───────────────┬──────────────────────────────┘
                                       │ verified against ↓
                       ┌───────────────┴──────────────────────────────┐
  CATALOGS (fetched,   │  OpenRouter /models      per-model list price │
  demoted to           │  OpenRouter /endpoints   per-HOST prices      │
  verifiers)           │  HF router /v1/models    per-HOST prices      │
                       │  LiteLLM json            community fallback   │
                       └───────────────┬──────────────────────────────┘
                                       │ fetch → merge → verify → emit
                       ┌───────────────┴──────────────────────────────┐
  CACHE (gitignored,   │  cache/pricing.json    {models, deployments,  │
  regenerated)         │                         needs_review, ...}    │
                       │  cache/discovery.json  raw catalog layers     │
                       │  cache/endpoints/      per-slug host snapshots│
                       └───────────────┬──────────────────────────────┘
                                       │
                       ┌───────────────┴──────────────────────────────┐
  CONSUMERS            │  fetch_pricing.py query ...   (agents, Pi)    │
                       │  llm-cost-estimator            (reads models) │
                       └──────────────────────────────────────────────┘
```

### The files, and what each one is *for*

| File | Role | The thing to remember |
|---|---|---|
| `fetch_pricing.py` | The whole pipeline and CLI. One file, ~1,300 lines, stdlib only. | Deliberately one file: the "clone and run" property and the 35 ms cold-start both depend on it. |
| `overrides.json` | Truth layer 1. Tokenizer per model (nobody publishes those), catalog pins (`openrouter_slug`, `hf_id`), and — rarely — an attested negotiated price. | The *default* is to give only a tokenizer and let the catalog price flow through. Hand-typing a price is the exception and must be attested. |
| `deployments.json` | Truth layer 1b. What you run, keyed `model@host`, in its native unit. | Two forms: **quoted** (you know the price) or **derived** (self-host: GPU + seconds/unit + bench run id). |
| `gpu_rates.json` | Attested `$/hour`, keyed `<gpu>@<provider>`. | Never averaged across providers — you pay *one* of them. |
| `cache/` | Regenerated output. Gitignored. | If it's wrong, delete it and re-run. Never edit. |
| `tests/test_fetch_pricing.py` | 200+ hermetic tests. | Never touches the network; never reads the shipped truth files by accident (more on that below). |
| `tests/test_contract_drift.py` | The "contract gate" — derives four facts from the code and checks every document that restates them. | Also the generator: `--fix` rewrites the governed blocks. |
| `.specify/memory/constitution.md` | The rules, versioned. Now 3.0.0. | Amended in the *same commit* as the code that changed the rules. |
| `specs/00N-*/` | One folder per feature: spec, research, plan, data model, contract, quickstart, tasks. | `research.md` and `spec.md` are historical records — exempt from the gate on purpose. |
| `claude_review/` | Quality-pass reports, one per reviewed commit. | The *diff between runs* is the value. |

### The flow of one refresh

`python fetch_pricing.py --force` does this, in order:

1. Fetch OpenRouter's catalog (load-bearing: if it fails, serve stale). Fetch LiteLLM
   and the HF router (demoted: if they fail, reuse the last known layer, warn, carry on).
2. `attach_catalog_baseline` — for every override, find its catalog row. Inherit the
   price if the override has none; honour it if it's attested; **discard it and flag
   it** if it's a hand-typed number nobody claimed.
3. Stamp `unit: per_1m_tokens` on every model entry; validate; drop invalid ones with a
   named reason.
4. `resolve_deployments` — the same trust rules, applied to what you run. Derive
   self-host prices. Cross-check per-token deployments against the *named* host's
   catalog row. Record `drift`.
5. Roll every flagged id into `needs_review`, write the cache atomically, exit 0 if
   clean or 1 if anything needs a human.

### The flow of one query

`fetch_pricing.py query price glm-5.2 --host together`:

1. Load the cache; if stale and online, refresh it (with the cache's *own* TTL — a
   caller's `--ttl-hours` is a read-time gate and never persists).
2. Build a small request context: the cache view, the discovery layers, the host name
   canonicalised (`BaseTen` → `baseten`).
3. Is there a deployment `glm-5.2@together`? Serve it (`baseline: false` — truth).
4. Else, is there a catalog row at Together? Serve it (`baseline: true` — verifier).
5. Else `found: false`, exit 2.

Every answer says its `unit`, its `source`, whether it's `baseline`, and whether it's
`degraded`. Exit codes are deterministic and derived — the docs can't drift from them.

---

## 4. The design decisions, and the reasoning behind each

These are the calls a future you might be tempted to undo. Don't, without reading why.

### "Attest what you pay, verify against a catalog, expire the claim"

The trust rule is the best thing in the repo and it predates the refit. A hand-typed
price is *not* truth. It's a claim. To count, it needs a `note` (where did this come
from?) and a `verified_at` (when did a human last confirm it?). Claims expire after 90
days — otherwise `negotiated: true` becomes a permanent mute button and hand-typed
prices rot exactly as before. An expired claim **keeps its price** and lands in
`needs_review`: silently reverting to the catalog would change the number you believe
you pay, which is worse than asking.

The refit's key move was to notice this rule is *general*. It applies to deployments
and to GPU rates without modification. When a design has a rule that survives a change
of objective, that's the rule to build on.

### "Every price carries a unit, and units never share fields"

The obvious shortcut was to put a per-page price in `in` and let a `unit` field say
what it meant. Rejected, hard. `llm-cost-estimator` multiplies `in` by a token count.
A per-page number in `in` would produce a wrong cost with exit 0 — the exact failure
this repo exists to prevent. So `per_page` uses `price`, `per_gpu_hour` uses
`usd_per_hour`, and validation *rejects* a foreign field outright. A consumer that
doesn't know the unit **cannot accidentally use the number**. The cheap change was the
safe one.

### "The catalog is a verifier, not the truth"

Before: catalog price unless overridden. After: your deployment unless you have none.
Same code paths, opposite default. The tell that the old default was wrong: the
README's own caveat said *"OpenRouter price ≠ what we pay unless we route via
OpenRouter"* — and then served OpenRouter's price as the answer for 8 of 9 models.
When a document caveats its own default, the default is wrong.

### "Derived prices name every input, and refuse to exist without them"

A self-hosted price is `usd_per_hour × seconds_per_unit / 3600`. If the GPU rate is
missing, there is **no price** and a reason (`gpu-rate-missing`). If the measurement
is missing, no price (`bench-missing`). When there *is* a price, the answer carries
`rate: {key, usd_per_hour, provider}` so you can see exactly which input produced it.
The alternative — a plausible default GPU rate — would be a hand-typed price wearing a
disguise.

### "Demoted sources are opt-in by fetcher presence"

This one is subtle and worth understanding. The test suite has a *network guard*: it
patches `urllib.request.urlopen` to raise `AssertionError`, so any test that reaches
the real network fails loudly. Now: a demoted source (LiteLLM, HF) is fetched inside
`try: ... except Exception:` — that's the whole point of "demoted", failure is
survivable. But `AssertionError` **is** an `Exception`. So if `run()` fetched HF by
default, every existing test would have hit the guard, *caught it*, quietly taken the
fallback path, and passed. The guard would be silenced precisely where it mattered.

The fix: `run()` fetches HF only when handed an `hf_fetcher`. `main()` — the real CLI —
passes the real one. Tests pass a fake or nothing. A hermetic caller can never have a
network attempt swallowed into a fallback.

### "Host names are canonicalised by declaration, never by inference"

`BaseTen` and `baseten` are one host. `Fireworks` and `fireworks-ai` are one host.
`Makora` and `Morph` are two. The rule: lowercase, strip punctuation, then consult a
**declared alias table**. Unknown names stay distinct. Why not fuzzy-match? Because
pricing one host as another is the single worst silent failure available — and the
repo already had that bug once (`_resolve_slug` used to guess a slug after a pin
retired, and inherited another model's price). Declared beats clever.

### "Constitution amended in the same commit as the code"

The rules said prices MUST be USD per 1M tokens. The code was about to emit prices
per page. If the code landed first, the constitution would describe a repo that
didn't exist. So the amendment (2.0.0 → 3.0.0, with a Sync Impact Report explaining
each redefinition) went in the *same* commit as the units. There was never a moment
where doc and code disagreed.

### "One file. Still."

Every phase added functions to `fetch_pricing.py`. The temptation to split into a
package is real. Resisted because: (a) clone-and-run with zero install is a
constitutional principle, (b) the offline cold-start is 35 ms and every import costs,
and (c) the query surface was *already* decomposed into named handlers — new actions
slot in as functions, not branches. `query_main` is a 40-line dispatcher. Altitude is
about responsibility boundaries, not file boundaries.

---

## 5. The technologies, and why each one

| Tech | Used for | Why this and not the alternative |
|---|---|---|
| **Python stdlib only** (`urllib`, `json`, `argparse`, `unittest`, `re`) | Everything | Runs anywhere an agent runs, no install step. Non-negotiable (Principle I). `requests` would be nicer and would cost every consumer a venv. |
| **`unittest` with injectable fetchers** | Hermetic tests | Every network call takes a `fetcher` callable. Tests pass fakes. 231 tests run in 0.12 s with zero network. This injection seam is the repo's best structural habit. |
| **Atomic writes** (`tempfile` + `os.replace`) | Every cache write | Multiple agents read these files concurrently. A reader sees the old file or the new one, never half. No `fsync` — a crash can lose the newest write, and that's fine for a regenerable cache. |
| **Deferred imports** (`urllib.request`, `tempfile` imported inside the functions that use them) | Cold-start | Cut the offline query from 46 ms to 34 ms. Both modules are only needed on the write/fetch path. |
| **spec-kit** (`.specify/`, `specs/00N/`) | Feature workflow | Spec → research → plan → data model → contract → tasks → implement. The spec is written *before* the code and the code is held to it. `research.md` records what was *found* and is deliberately never updated. |
| **The contract-drift gate** (`tests/test_contract_drift.py`) | Doc/code consistency | Four facts (exit codes, envelope keys, trust rule, unit vocabulary) are derived from the running code and compared against marked blocks in seven documents. `--fix` regenerates. Never runs during tests — a gate that repairs itself hides the drift it exists to report. |
| **Hugging Face router** (`GET router.huggingface.co/v1/models`) | Second per-host catalog | Public, unauthenticated, *documented* — the `pricing` field is a contract, not an accident. 139 chat models, 14 hosts. Verified 6/7 exact against host pages; the miss was a promo HF hadn't ingested. |
| **`claude_review/`** | Recurring quality passes | One report per reviewed commit, immutable once HEAD moves. Four runs now; the trend line is the point. |

---

## 6. The bugs we hit, and what each one teaches

This is the section to reread when you're about to write similar code. Every one of
these was caught by a check, not by luck — and that's the lesson underneath all of
them.

### Bug 1 — The permanent review queue (before the refit)

**What:** Four of nine models sat in `needs_review` forever. The checks script had a
comment saying *"the review queue currently flags 4 models, so list/fresh LEGITIMATELY
exit 1."* A contract test asserted at least one flagged entry must exist.

**Why:** Those four had hand-typed prices from before the attestation rule existed.
When the rule landed, the author attested the one real negotiated rate and left the
rest — and then the gates absorbed the defect as an invariant.

**Lesson:** *When a test or a check encodes "some things are always broken," it's not
protecting you, it's protecting the bug.* A green suite on a repo with four
unpriceable models is a suite that has stopped asking questions.

### Bug 2 — The test that would fail on a Friday in November

**What:** `test_no_half_declared_attestation` asserted `attestation_state == "valid"`.
`glm-5.2` was attested 2026-08-16. Attestations expire at 90 days. On 2026-11-15 the
suite would go red with no code change.

**Why:** The test asserted *freshness* when it meant to assert *shape*. And the
pipeline already had a channel for expiry — `needs_review`. The test duplicated a
working mechanism as a hard failure.

**Lesson:** *Tests should pin the clock.* Anything time-dependent gets an explicit
`now=`. And if the system already reports a condition through a designed channel, a
test that re-raises it as a failure turns a reminder into an outage.

### Bug 3 — `stream=sys.stderr` as a default parameter

**What:** `def _print_table(rows, stream=sys.stderr)`. A new test wrapped the call in
`contextlib.redirect_stderr(buf)` and got an empty buffer. `IndexError` on `[0]`.

**Why:** Default parameter values are evaluated **once, at function definition time**.
`stream` was bound to whatever `sys.stderr` was when the module imported — the
original stream. `redirect_stderr` swaps `sys.stderr` later; the default never notices.

**Fix:** `stream=None` and `stream = stream or sys.stderr` inside — resolve at call time.

**Lesson:** This is the classic Python mutable-default gotcha's quieter cousin. Any
default that captures a *name that might be reassigned* (`sys.stderr`, a module
constant, a global config) is a bug waiting for the first redirect or patch.

### Bug 4 — Hermetic tests that weren't (same shape as Bug 3!)

**What:** `run(deployments_path=DEPLOYMENTS_PATH)`. Tests called `run()` with a temp
`overrides_path` and never passed `deployments_path` — so they silently read the
*real* `deployments.json`. And they **passed**, because today's seeds looked valid on
the wall clock. Only a test class with a pinned *past* clock went red (the seeds looked
future-dated → unattested → exit 1).

**Why:** Exactly Bug 3. The default captured the module constant at import. Patching
the constant later — the natural way to make a whole module hermetic — did nothing.

**Fix:** `deployments_path=None` resolved at call time, plus **one** patch in
`setUpModule` covering every `run()`/`query_main()`/`main()` call in the file. Then
*proved* it: with both truth files deleted from disk, the only failing test is the one
whose job is to notice they're gone.

**Lesson:** Two instances of the same shape in one day is a pattern, not a
coincidence. It's recorded as theme **T3 — defaults bound at import** in the review.
And: *a test that passes isn't evidence it's hermetic.* Prove hermeticity by removing
the thing it might be leaking on.

### Bug 5 — The second `setUpModule`

**What:** I added a `setUpModule()` at the top of the test file to install the patch
from Bug 4. It never ran. `_truth_patch` was `None`.

**Why:** There was *already* a `setUpModule()` 600 lines down — the network guard.
Python keeps the **last** definition of a name. Mine was silently shadowed.

**Fix:** Merge into the existing hook. It's where a hermeticity guard belongs anyway.

**Lesson:** Module-level hooks are singletons. Before adding one, `grep` for it. More
generally: *when a mechanism "doesn't work," instrument it before theorising.* One
print of the constant before and after `setUpModule()` found this in a minute; I'd
have spent longer theorising about `mock.patch.multiple`.

### Bug 6 — The missing alias

**What:** `canonical_host("featherless-ai")` → `featherlessai`, not `featherless`. Two
tests failed.

**Why:** I'd declared `fireworks-ai → fireworks` but not the identical pattern for
Featherless.

**Lesson:** This one is a *success story*. The design says aliases are declared, not
inferred. A fuzzy matcher would have "fixed" this silently — and would also silently
merge two genuinely different hosts someday. Loud failure on an unknown name is the
mechanism working. Add the row, move on.

### Bug 7 — Two stale claims in the README

**What:** The status line said precedence was `overrides > LiteLLM > OpenRouter` (wrong
since v2.0.0). A paragraph said the HF router API was auth-walled (it answers without a
token and the pricing field is documented).

**Lesson:** Prose restates facts; facts change; prose doesn't notice. The contract gate
exists precisely for this and governs what it *can* (blocks derived from code). For
the rest, the only defence is *checking claims against reality periodically* — which
is what the 2026-09-08 audit did, and how the HF finding was made at all.

---

## 7. Pitfalls to avoid next time

- **Don't hand-type a price without attesting it.** It'll be discarded and flagged.
  That's the design. If it's real, add `note` + `verified_at` (+ `negotiated: true` if
  it's not the public rate).
- **Don't put a non-token price in `in`/`out`.** Validation will reject it. Use the
  unit's own field.
- **Don't average GPU rates across providers.** Key them `<gpu>@<provider>`. You pay
  one.
- **Don't edit `cache/`.** It's output. Delete and regenerate.
- **Don't add a second `setUpModule`.** There's one. Extend it.
- **Don't use a default parameter to capture a redirectable name** (`sys.stderr`, a
  module path constant). Resolve at call time.
- **Don't restate a governed fact in prose.** Reference the block. The README's test
  count was removed for exactly this reason — a number in prose is a restatement that
  drifts.
- **Don't fuzzy-match hosts.** Add an alias row.
- **Don't trust `cheapest` for a workload you've already placed.** Ask `--host`.

---

## 8. How good engineers think — the habits this session ran on

If the bugs section is *what* went wrong, this is *how* it got found and fixed. These
are habits, and they're transferable.

**Verify by experiment, not by reading.** Every acceptance criterion was checked
against the real cache with the real CLI, and the check was asserted in-script so a
regression would trip it. The hermeticity claim was proven by *deleting the files*.
Reading a diff and nodding is not verification.

**Instrument before theorising.** When the patch "didn't work," one print of the
constant before/after told the truth in seconds. Hypotheses are cheap and usually
wrong; measurements are cheap and usually right.

**Small, additive, each step green.** Five phases, five commits, every one passing
the full suite and the checks script before the next started. When Phase 2 broke the
suite, it was obvious which fifty lines to look at. A 2,000-line commit would have
hidden Bugs 3, 4 and 5 inside each other.

**Change the rules in the same commit as the code.** The constitution never described
a repo that didn't exist.

**Let the design fail loudly.** Declared aliases, never-guess derivation, attestation
expiry, invalid entries emitted-with-no-price rather than dropped — every one of these
chooses a visible failure over a plausible silent one. In a source-of-truth repo, a
loud wrong answer is recoverable; a quiet wrong answer is the whole failure mode.

**Record what you *found*, separately from what you *decided*.** `research.md` says
what was true on 2026-09-08 and is deliberately never edited. The constitution says
what the rules are and is versioned. Confusing the two is how a repo ends up with a
README that argues with its own code.

**When a document caveats its own default, the default is wrong.** That single
observation — "OpenRouter price ≠ what we pay" printed above a table serving OpenRouter
prices — is what turned an audit into a redesign.

**Own the data, not just the code.** The last review's meta-observation: after four
passes, the residue is almost entirely data the *user* must supply — which hosts, which
GPU, how many seconds a page takes. The code's job is to refuse to guess any of it and
say exactly which input it used. It does. Now it's on you to replace the seeds.

---

## 9. Where to go from here

The seeds in `deployments.json` and `gpu_rates.json` are real prices at example hosts.
Three things make this *your* source of truth rather than a demonstration:

1. Replace the deployment hosts with the ones you actually run on.
2. Replace the OCR entry's `seconds_per_unit` (marked `PLACEHOLDER`) with a Matterwork
   bench measurement, and put the run id in `bench_run`.
3. Confirm `glm-5.2`'s negotiated rate against the z.ai plan and restamp `verified_at`.

Then `python fetch_pricing.py --force`, and `query deployments` shows you the cost of
your own work, in the units it's actually sold in, with every number traceable.

*— end —*

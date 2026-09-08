# Feature Specification: Cost per unit of work at a named deployment

**Feature Branch**: `005-cost-per-unit`
**Created**: 2026-09-08
**Status**: Draft
**Input**: User description: "Go back to first principles — the *why* — and refit the repo. I want one source of truth to quickly fetch the cost of using any particular model, for extensive open-weight use across hosts (Together, Baseten, Hugging Face) and self-hosted specialist models (OCR), across my repos."

## Why (first principles)

The README's stated objective is a *mechanism*: keep a price catalog fresh. The objective
that actually drives usage is a *question*: **what does this workload cost on the
deployment I would actually use?** Everything found while auditing the repo on
2026-09-08 is the gap between the two:

1. **Proprietary models are solved.** OpenRouter's catalog equals vendor list price to the
   cent (6/6 verified against OpenAI, Anthropic, Moonshot pricing pages).
2. **Hosted open-weight is solved at the data layer, not the query layer.** Per-host prices
   are exact in both OpenRouter's endpoints API and Hugging Face's router (7/7 verified
   against Together, Baseten, z.ai, DeepInfra pages). The repo *holds* them and cannot
   answer "at Together?" — `cheapest` returns DeepInfra at 0.49/1.56 for GLM-5.2 when the
   user's actual host, Together, charges 1.40/4.40: a 3× miss on the number they need.
3. **Specialist models have no per-token price because they are not sold per token.** Of
   100 OCR models on the Hub by downloads, 4 have any provider and 0 have a router price.
   They are sold per run (Replicate: ~$0.014/run), per page (Marker: $6/1,000), flat
   (Featherless: $10–75/mo), or not at all — only self-hosted, where cost = GPU $/hr ×
   seconds/page, and the seconds come from the user's own benchmark.

The per-token catalog is the right shape for (1), incomplete for (2), and structurally
wrong for (3). This feature does not replace it. It **demotes the catalog from source of
truth to one verifier**, and makes *the deployments the user actually runs* the truth —
each priced in its native unit, attested, and cross-checked against the catalog where one
exists. The trust model (attest what you pay; verify against a catalog; report
degradation loudly) is the best thing in the repo and is generalised, not replaced.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Every price carries a unit (Priority: P1)

A consumer reading `cache/pricing.json` can tell, for every price, what one unit of it
buys — a million tokens, a page, a run, a GPU-hour, a month — without out-of-band
knowledge. Existing per-token entries are unchanged except for gaining `unit:
"per_1m_tokens"`.

**Why this priority**: every other story emits a non-token price; none of them can be
represented until the schema says what a price *is*. It is also the only story that
touches existing entries, so it must land first and prove it breaks nothing.

**Independent Test**: refresh the cache; every entry in `models` carries `unit:
"per_1m_tokens"`; `llm-cost-estimator` runs end-to-end unchanged; the contract gate
regenerates the envelope block in every governed document.

**Acceptance Scenarios**:

1. **Given** the current `overrides.json`, **When** the pipeline runs, **Then** every
   emitted model entry carries `unit: "per_1m_tokens"` and `in`/`out` are byte-identical
   to before.
2. **Given** an entry with an unknown `unit`, **When** validated, **Then** it is rejected
   and reported, never emitted.
3. **Given** the vocabulary of units, **When** a governed document restates it, **Then**
   the contract gate derives the vocabulary from code and fails on drift.

---

### User Story 2 — A curated deployments layer, any unit, attested (Priority: P1)

The user records the deployments they actually run — a model at a host, or a model on
their own GPU — in `deployments.json`, each priced in its native unit with an
attestation. Self-hosted entries carry no price at all: they carry a GPU and a measured
`seconds_per_unit` from a benchmark run, and the pipeline derives the price from a small
attested `gpu_rates.json`. Deployments are emitted under a new envelope key
`deployments`, verified against the catalog where a per-token equivalent exists, and
reported in `needs_review` under the same rules as overrides.

**Why this priority**: this is the *why*. It is the only way to price the models the user
cares most about, and it is what turns the catalog into a verifier.

**Independent Test**: add a quoted deployment and a derived one; run the pipeline; both
appear under `deployments` with a computed price, unit, source, attestation state, and —
for the quoted per-token one — a `catalog` cross-check with `drift`. Expire the
attestation and it lands in `needs_review`.

**Acceptance Scenarios**:

1. **Given** `kimi-k3@together` quoted at 3.00/15.00 with a note and `verified_at`,
   **When** the pipeline runs, **Then** it is emitted with `unit: per_1m_tokens`,
   `source: deployment`, `baseline: false`, and a `catalog` row from the per-host
   catalog price at Together, with `drift` recorded if they differ by more than
   `DRIFT_TOLERANCE`.
2. **Given** `deepseek-ocr@self-host` with `derive: {gpu: "l40s@runpod",
   seconds_per_unit: 15, unit: "per_page"}`, **When** the pipeline runs, **Then** its
   price is `usd_per_hour × seconds_per_unit / 3600` and the entry names the GPU rate
   it used.
3. **Given** a derived deployment whose `derive.gpu` is absent from `gpu_rates.json`,
   **When** the pipeline runs, **Then** the deployment is emitted without a price and
   flagged `review: gpu-rate-missing`, and the exit code is 1.
4. **Given** a deployment whose `verified_at` is older than `ATTESTATION_MAX_AGE_DAYS`,
   **When** the pipeline runs, **Then** it keeps its price and is flagged
   `attestation-expired`.
5. **Given** a deployment with no `note` or no parseable `verified_at`, **When** the
   pipeline runs, **Then** it is flagged `unattested-deployment`; if a catalog price
   exists for that model at that host the catalog price is served instead, otherwise the
   declared price is kept (mirroring the overrides rule exactly).

---

### User Story 3 — Hugging Face router as a second per-host catalog (Priority: P2)

The pipeline fetches `https://router.huggingface.co/v1/models` — public, unauthenticated,
and documented — and persists its per-provider prices as an `hf_router` layer in
`discovery.json`. Models are mapped to Hub ids via an optional `hf_id` in
`overrides.json`. HF is a **demoted** source like LiteLLM: if it fails, the refresh
proceeds with the last known layer.

**Why this priority**: it covers host/model pairs OpenRouter does not route (Together's
DeepSeek price was invisible before), distinguishes model variants OpenRouter merges,
and gives a second independent verifier for deployment prices. But the deployments
layer works without it, so it is P2.

**Independent Test**: inject a fake router payload; the layer is normalised and
persisted; `query hosts` shows rows sourced `hf-router`; an injected fetch failure
leaves the previous layer in place and the refresh succeeds.

**Acceptance Scenarios**:

1. **Given** a router payload with per-provider `pricing`, **When** normalised, **Then**
   each `(hf_id, host)` carries `in`/`out` in USD per 1M tokens plus `context_length`
   and `status`; providers without `pricing` are retained without a price.
2. **Given** the HF fetch raises, **When** the pipeline refreshes, **Then** the refresh
   completes, the last known `hf_router` layer is reused, and a warning names the
   reuse (as the LiteLLM path does today).
3. **Given** a model with no `hf_id`, **When** hosts are queried, **Then** only
   OpenRouter-sourced rows appear and nothing errors.

---

### User Story 4 — Per-host queries (Priority: P2)

An agent can ask **what a model costs at a named host** — the price it will actually
pay — and can list every host that serves a model with its price and source. A
deployment at that host, when one exists, is the answer; otherwise the catalog's
per-host price is served as `baseline: true`.

**Why this priority**: the data has been on disk since spec 002; this is the missing
question. It depends on US2 for truth and on US3 for coverage but is useful with either.

**Independent Test**: `query hosts glm-5.2` lists Together, Baseten, DeepInfra, Z.AI …
with prices and sources; `query price glm-5.2 --host together` returns 1.40/4.40 and not
DeepInfra's 0.49/1.56.

**Acceptance Scenarios**:

1. **Given** endpoint and router data for a model, **When** `query hosts <model>` runs,
   **Then** one row per `(host, sku)` is returned, merged from both sources, host names
   canonicalised so `BaseTen` and `baseten` are one host, sorted by blended cost, with
   `source` naming which catalog each row came from.
2. **Given** a deployment for `<model>@<host>`, **When** `query price <model> --host
   <host>` runs, **Then** the deployment is served with `baseline: false` and its
   `catalog` cross-check; **When** no deployment exists **Then** the catalog row is
   served with `baseline: true`; **When** neither exists **Then** `found: false` and exit 2.
3. **Given** `--host`, **When** `query cheapest <model> --host <host>` runs, **Then** only
   that host's SKUs are ranked.
4. **Given** a host that serves the model under a flat subscription (Featherless),
   **When** hosts are listed, **Then** the row appears with `unit: per_month` or no price
   and is never ranked as cheapest per token.

---

### Edge Cases

- A `deployments.json` id that names a model not in `overrides.json` — allowed (a
  self-hosted OCR model has no tokenizer and is not a catalog model); such an entry is
  never merged into `models`, only into `deployments`.
- Two SKUs at one host for one model (Baseten lists GLM-5.2 at 1.40/4.40 and 2.10/6.60)
  — both rows are kept in `hosts`; `--host` ranking picks the cheapest by blended cost
  and names the SKU's quantization.
- Provider name collisions across sources (`fireworks-ai` vs `Fireworks`, `zai-org` vs
  `Z.AI`) — resolved by a declared alias table in code; unknown names canonicalise by
  lowercasing and stripping non-alphanumerics and are otherwise kept distinct.
- `gpu_rates.json` attestation expiry — a GPU rate is a price and expires like one;
  every derived deployment using it is flagged `gpu-rate-expired`.
- A `per_month` deployment has no per-unit cost — it is emitted with the flat price and
  `unit: per_month`, and any cost-per-unit computation must supply a volume.
- HF router lists a provider with `status: error` — the row is retained with its status
  and excluded from cheapest ranking.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every emitted price MUST carry a `unit` from a vocabulary defined once in
  `fetch_pricing.py` (`UNITS`) and derived into governed documents by the contract gate.
- **FR-002**: Per-token entries in `models` MUST be unchanged in `in`/`out` and gain only
  `unit: "per_1m_tokens"`. The envelope MUST gain exactly one key, `deployments`.
- **FR-003**: `deployments.json` MUST be loaded as a truth layer alongside
  `overrides.json`; each entry is keyed `<model>@<host>` and declares `unit`, either a
  price in that unit's fields or a `derive` block, plus attestation (`note` +
  `verified_at`, `negotiated` optional).
- **FR-004**: A derived deployment's price MUST be computed as
  `gpu_rates[derive.gpu].usd_per_hour × derive.seconds_per_unit / 3600`, and the emitted
  entry MUST name the rate key used. A missing rate MUST be reported
  (`gpu-rate-missing`), never guessed.
- **FR-005**: Deployment attestations MUST follow the overrides rules: expire after
  `ATTESTATION_MAX_AGE_DAYS` (`attestation-expired`, price kept); unattested entries are
  flagged (`unattested-deployment`) and replaced by a catalog price where one exists at
  that host, kept otherwise.
- **FR-006**: A per-token deployment at a host present in the per-host catalog MUST be
  cross-checked: the catalog row is attached as `catalog` and `drift` recorded above
  `DRIFT_TOLERANCE`, informationally.
- **FR-007**: The pipeline MUST fetch the HF router model list, normalise per-provider
  prices to USD per 1M tokens, and persist them as `discovery.json.hf_router`. HF is a
  demoted source: its failure MUST NOT discard an otherwise healthy refresh.
- **FR-008**: `overrides.json` entries MAY declare `hf_id`; without it, a model has no HF
  router rows and nothing errors.
- **FR-009**: `query hosts <model>` MUST list every `(host, sku)` serving the model from
  both catalogs plus any deployments, host names canonicalised via a declared alias
  table, each row naming its `source`.
- **FR-010**: `query price <model> --host <host>` MUST serve the deployment for that pair
  if one exists (`baseline: false`), else the catalog per-host row (`baseline: true`),
  else `found: false` with exit 2. `query cheapest --host` MUST restrict ranking to that
  host.
- **FR-011**: `query deployments` MUST list every deployment with computed price, unit,
  attestation state and any `review` reason; exit 1 while any is flagged.
- **FR-012**: All new query actions MUST print one JSON object to stdout, human notes to
  stderr, and map exit codes through `_exit_for` unchanged.
- **FR-013**: The suite MUST remain hermetic: the HF fetcher is injectable; tests use a
  fixture payload; no network.
- **FR-014**: The constitution MUST be amended to describe the two-file truth layer, the
  unit vocabulary, and HF as a demoted source, with a version bump and Sync Impact
  Report, and every governed block regenerated by the gate.

### Key Entities

- **Unit**: what one unit of a price buys. Vocabulary: `per_1m_tokens` (`in`, `out`),
  `per_page` (`price`), `per_run` (`price`), `per_gpu_hour` (`usd_per_hour`),
  `per_month` (`price`).
- **Deployment**: a model at a host (or on own hardware), priced in its native unit,
  attested. Quoted (`price fields`) or derived (`derive` block). The truth for cost.
- **GPU rate**: an attested `usd_per_hour` for a GPU at a provider, keyed
  `<gpu>@<provider>`. The only external input a derived deployment needs.
- **Host row**: one `(host, sku)` price for a model from a catalog (`openrouter-endpoints`
  or `hf-router`), `baseline: true`. A verifier, not truth.
- **Bench run**: an opaque id recorded on a derived deployment as its attestation of
  `seconds_per_unit`. Produced outside this repo; this repo only records it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `query price glm-5.2 --host together` returns 1.40/4.40 — the verified
  Together price — where `query cheapest glm-5.2` returns DeepInfra's 0.49/1.56 today.
- **SC-002**: A self-hosted OCR model with no API provider anywhere is priced per page
  from a GPU rate and a benchmark figure, with every input attested and named in the
  answer.
- **SC-003**: `llm-cost-estimator` runs end-to-end against the new envelope with no
  change to its code.
- **SC-004**: Zero governed documents disagree with shipped behaviour on exit codes,
  envelope, trust rule, or units — the gate passes with the new fact registered.
- **SC-005**: The suite stays hermetic and grows by less than one second.
- **SC-006**: Every seeded price in `deployments.json` and `gpu_rates.json` is traceable
  to a public page fetched on the `verified_at` date named in its note.

# Feature Specification: Pricing Query

**Feature Branch**: `001-pricing-query`  
**Created**: 2026-08-29  
**Status**: Approved  
**Input**: User description: "Add a pricing query interface to the single source of truth: price lookup, cheapest host, model list, and freshness queries, with auto-refresh when data is stale, an offline mode, and a global agent skill so agents discover the tool."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Look up a model's price (Priority: P1)

An agent (or human at a shell) asks "how much does model X cost" and receives a
structured answer: input and output price, which source the number came from
(authoritative pricing vs. discovery pricing), and how fresh the data is. If
the data is stale, the query refreshes it first and answers from fresh data
without the caller orchestrating anything.

**Why this priority**: Price lookup is the core use case; every other query
builds on it. It alone makes the tool useful.

**Independent Test**: Ask for the price of a model already present in the
authoritative data (no network needed); the answer contains the price, its
source, and freshness. Then ask for a model only present in discovery data;
the answer is labeled as baseline (non-authoritative).

**Acceptance Scenarios**:

1. **Given** fresh pricing data, **When** an agent asks for the price of a known model, **Then** the answer includes input price, output price, source, and freshness, with no refresh happening.
2. **Given** stale pricing data, **When** an agent asks for the price of a model, **Then** the data is refreshed automatically and the answer reflects the refreshed data.
3. **Given** a model that exists only in discovery sources, **When** an agent asks for its price, **Then** the answer includes the price and is explicitly marked as baseline (not what we actually pay).

---

### User Story 2 - Find the cheapest host for a model (Priority: P2)

An agent asks "where is model X cheapest" and receives the cheapest
provider-hosted variant of that model and its price, so it can pick the least
expensive routing option.

**Why this priority**: Cheapest-host discovery is the SOT's flagship
value-add for open-weight models; it is valuable but secondary to plain price
lookup.

**Independent Test**: Ask for the cheapest host of a model that multiple
providers host; the answer names the cheapest provider and its price.

**Acceptance Scenarios**:

1. **Given** multiple providers hosting the same model, **When** an agent asks for the cheapest host, **Then** the answer identifies the provider with the lowest price and reports that price.
2. **Given** a model hosted by only one provider, **When** an agent asks for the cheapest host, **Then** the answer returns that provider as the (only) option.
3. **Given** provider names that format the model name differently (e.g. `gemini-3.7` vs `gemini-3-7`), **When** an agent asks for the cheapest host, **Then** those variants are recognized as the same model family.

---

### User Story 3 - List models and check data freshness (Priority: P2)

An agent asks "what models do we know about, and how fresh is this data?" and
receives a model list plus the data's age and freshness status, so it can
judge whether to trust the numbers before using them.

**Why this priority**: Without visibility into coverage and staleness, agents
cannot trust the other answers.

**Independent Test**: Ask for the model list and freshness status; both return
without any network access and reflect the current data.

**Acceptance Scenarios**:

1. **Given** current data, **When** an agent asks for the model list, **Then** the answer lists every known model with its price and source.
2. **Given** current data, **When** an agent asks for freshness, **Then** the answer states the data's age and whether it is fresh or stale.
3. **Given** no data at all, **When** an agent asks for the model list or freshness, **Then** the answer honestly reports that no data is available.

---

### User Story 4 - Query without network (offline mode) (Priority: P3)

An agent can run any query in an offline mode that guarantees no network
activity, receiving whatever is already cached plus honest "not found" or
stale answers when data is missing.

**Why this priority**: Offline guarantees make the tool predictable for
scheduled/batched agent work; it is an enhancement on top of the primary
queries.

**Independent Test**: With network disabled, run each query; queries complete
from cache and unknown models return "not found" without any network attempt.

**Acceptance Scenarios**:

1. **Given** cached data, **When** an agent runs a query in offline mode, **Then** the answer comes from cache with zero network activity.
2. **Given** cached data that is stale, **When** an agent runs a query in offline mode, **Then** the answer is served from cache and is marked stale.
3. **Given** a model absent from cache, **When** an agent runs a price query in offline mode, **Then** the answer is "not found" with no network attempt.

---

### User Story 5 - Agents discover the tool (Priority: P3)

An agent that has never heard of this repository learns that the pricing tool
exists and how to query it, without a human having to explain it each time.

**Why this priority**: Discovery is what makes all the above queries actually
get used by agents; it has no value without the queries, so it ships after
them.

**Independent Test**: A fresh agent session whose instructions mention
pricing/cost is able to find the documented queries and run them correctly.

**Acceptance Scenarios**:

1. **Given** a fresh agent session, **When** the task involves model pricing or cost, **Then** the agent is presented with the tool's existence and usage instructions.
2. **Given** the discovery instructions, **When** the agent follows them, **Then** the agent can run each query and interpret the answers correctly.

---

### Edge Cases

- Unknown model with no cached or discovery data → "not found" (never a guessed price).
- Stale data + refresh fails (network down) → serve cached data marked stale; if no data exists at all → report no data available.
- Corrupt or unreadable cache → treated as missing; query falls back to refresh (or "not found" offline).
- Multiple providers tied at the cheapest price → return all tied providers (or the first, explicitly).
- Provider variant naming differences (`3.7` vs `3-7`, provider prefixes) → normalized matching.
- Price of zero (free tier) → reported as zero, not mistaken for missing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST answer a price query for a model with its input price, output price, the source of the number, and the data's freshness.
- **FR-002**: The system MUST mark discovery-sourced answers as baseline (non-authoritative) so callers never mistake them for what we actually pay.
- **FR-003**: The system MUST automatically refresh stale or missing data before answering a query, unless offline mode is active.
- **FR-004**: The system MUST support an offline mode that never performs network activity and returns cached data with honest staleness, or "not found".
- **FR-005**: The system MUST answer a cheapest-host query by comparing provider-hosted variants of the model and returning the cheapest provider and price.
- **FR-006**: The system MUST provide a model list query that reports every known model with its price and source.
- **FR-007**: The system MUST provide a freshness query that reports the data's age and fresh/stale status.
- **FR-008**: The system MUST return a deterministic outcome status (fresh / stale / no data) for every query so callers can branch on it reliably.
- **FR-009**: The system MUST ship a discovery artifact that agents automatically surface when a task involves pricing, documenting the queries and how to interpret answers.
- **FR-010**: All query answers MUST be structured and machine-readable.

### Key Entities *(include if feature involves data)*

- **Pricing Entry**: a model's input and output prices, its source (authoritative or baseline discovery), and tokenizer mapping.
- **Provider Variant**: a specific provider's hosted copy of a model with that provider's price; used by cheapest-host comparison.
- **Cache Snapshot**: the current dataset plus when it was fetched, its refresh window, and its fresh/stale status.
- **Discovery Artifact**: the instructions that make agents aware of the tool and its queries.

### Assumptions

- Authoritative pricing (what we actually pay) lives in a hand-maintained truth layer; discovery pricing is labeled baseline and is never presented as authoritative.
- Prices are expressed in USD per 1M tokens; no currency conversion in scope.
- The refresh window (24h default) applies to the whole dataset; per-model freshness is out of scope.
- Provider variant matching tolerates formatting differences (`3.7` vs `3-7`) and provider prefixes, but does not guarantee matching across renamed model families.
- The discovery artifact is machine-discoverable by agents (global), not project-local.
- Cost estimation (token counting and dollar math) is a separate concern owned by an existing consumer tool and is out of scope here.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A price query for a model present in the data returns an answer in under 2 seconds when the data is fresh.
- **SC-002**: 100% of query answers carry an explicit source and freshness label (no ambiguous pricing).
- **SC-003**: Stale data is refreshed automatically for at least 95% of queries that encounter it, without caller intervention.
- **SC-004**: Offline queries complete successfully with the network disabled for 100% of cases (cache hit or honest "not found").
- **SC-005**: An agent with no prior knowledge of the tool can discover and correctly run a price query using only the discovery artifact, on the first attempt.

# Feature Specification: Pricing Endpoints Upgrade

**Feature Branch**: `002-pricing-endpoints`  
**Created**: 2026-08-30  
**Status**: Approved  
**Input**: User description: "Upgrade cheapest host to OpenRouter per-provider endpoints API and demote LiteLLM to fallback cross-check with richer baseline fields and MCP documentation"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cheapest host from OpenRouter endpoints (Priority: P1)

An agent asks "where is model X cheapest" and receives the answer from
OpenRouter's own per-provider endpoints data: the cheapest provider's name,
input/output prices, quantization, and cache-read price when the provider
exposes one. Models OpenRouter does not route fall back to the existing
discovery-based variant scan (LiteLLM/OpenRouter layers).

**Why this priority**: This is the flagship lookup; the endpoints API replaces
the current fuzzy variant-matching heuristic with authoritative per-provider
data, so it is the core value of this feature.

**Independent Test**: Ask for the cheapest host of an OpenRouter-routed model
(e.g. `kimi-k3`); the answer names a concrete provider (e.g. Makora,
DeepInfra), its price, and quantization. Ask for a vendor-direct model with no
OpenRouter endpoints; the answer comes from the LiteLLM fallback and is labeled
as such.

**Acceptance Scenarios**:

1. **Given** an OpenRouter-routed model, **When** an agent asks for its cheapest host, **Then** the answer names a provider from the endpoints API with input/output prices and quantization.
2. **Given** a model with cache pricing on some endpoints, **When** an agent asks for its cheapest host, **Then** the answer includes the cache-read price where available.
3. **Given** a model OpenRouter does not route, **When** an agent asks for its cheapest host, **Then** the answer comes from the LiteLLM/discovery fallback and says which source produced it.
4. **Given** repeated cheapest queries for the same model within the freshness window, **When** the second query runs, **Then** no network fetch occurs (cached endpoint data is served).

---

### User Story 2 - Richer baseline fields (Priority: P2)

The OpenRouter discovery baseline captures input-cache-read/write prices (and
notes conditional `pricing.overrides` presence) alongside plain input/output
prices, so future cost work can account for cached-token pricing without
another data pull. Existing authoritative entries and consumer behavior are
unchanged.

**Why this priority**: Pure data capture with no behavior change — valuable
but strictly additive to the cheapest-host upgrade.

**Independent Test**: Fetch the OpenRouter baseline and confirm entries carry
cache-read/write prices for models that expose them, while the authoritative
cache and all existing tests remain unchanged.

**Acceptance Scenarios**:

1. **Given** an OpenRouter model with cache pricing, **When** the discovery baseline is built, **Then** its entry includes the cache-read and cache-write prices.
2. **Given** an OpenRouter model without cache pricing, **When** the discovery baseline is built, **Then** its entry omits cache fields without error.
3. **Given** existing authoritative entries, **When** the baseline gains new fields, **Then** authoritative entries and consumer behavior are unaffected.

---

### User Story 3 - Source roles documented (Priority: P3)

The repo's documentation states the new source roles (OpenRouter endpoints =
cheapest-host layer; LiteLLM = fallback/cross-check for vendor-direct pricing),
and the agent skill notes that OpenRouter's official MCP exists for interactive
account lookups (credits, exact per-generation cost) while the pipeline itself
stays plain REST.

**Why this priority**: Documentation accuracy prevents agents and humans from
misreading which layer to trust; it has no value without the first two stories.

**Independent Test**: Review the README source table and the skill file; both
state the new roles, and the skill's MCP note says "interactive lookups only —
not the local fetcher".

**Acceptance Scenarios**:

1. **Given** the updated README, **When** a reader checks the sources table, **Then** OpenRouter endpoints is the cheapest-host layer and LiteLLM is the fallback/cross-check.
2. **Given** the updated skill, **When** an agent reads it, **Then** it sees the MCP note describing interactive-only usage (credits, per-generation cost) and that the pipeline uses plain REST.

---

### Edge Cases

- Model id not in the OpenRouter catalog → no slug → fall back to the discovery variant scan; if nothing matches, "not found" (exit 2).
- Slug mapping provided by overrides when catalog exact-match fails → use the declared slug.
- Endpoints API failure (network/5xx/schema drift) → serve cached endpoint data; if none and online, fall back to the LiteLLM scan; if offline and no cache, "not found".
- Endpoints response shape drift → tolerant extraction; an unparseable response is treated as a source failure, not a crash.
- Single-endpoint model → that provider is the (only) cheapest.
- Tied cheapest prices across providers → return the cheapest set deterministically (first in provider order is acceptable and documented).
- `:batch` model variants → never mixed with interactive endpoint pricing.
- Offline cheapest query → serve cached endpoints; never fetch.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST answer cheapest-host queries from OpenRouter's per-provider endpoints API for OpenRouter-routed models, reporting provider name, input/output prices, quantization, and cache-read price where present.
- **FR-002**: The system MUST resolve a model id to an OpenRouter slug using the models catalog exact match, then an overrides-declared slug, then no slug (triggering fallback).
- **FR-003**: The system MUST cache endpoint responses locally under the same TTL gate (default 24h), refreshing only when stale and not offline.
- **FR-004**: The system MUST fall back to the existing discovery variant scan (LiteLLM/OpenRouter layers) when a model has no OpenRouter endpoints, labeling the answer baseline and naming the producing source.
- **FR-005**: The system MUST capture input-cache-read/write prices in the OpenRouter discovery baseline without changing authoritative entries or existing consumer behavior.
- **FR-006**: The system MUST NOT use the OpenRouter MCP for any pipeline path; documentation MUST state the MCP is for interactive agent-time account lookups only.
- **FR-007**: The README source-layer table MUST be updated to the new roles (OpenRouter endpoints = cheapest host; LiteLLM = fallback/cross-check for vendor-direct pricing).
- **FR-008**: Offline mode MUST serve endpoint data from cache with zero network activity.

### Key Entities *(include if feature involves data)*

- **Provider Endpoint**: one provider's hosted copy of a model — provider name, input/output price, quantization, cache-read price, status.
- **Slug Mapping**: the OpenRouter `{author}/{slug}` identifier resolved from a model id.
- **Endpoint Snapshot**: the TTL-gated local cache of a model's endpoints response.
- **Discovery Entry (baseline)**: the OpenRouter discovery record, now optionally carrying cache-read/write prices.

### Assumptions

- The OpenRouter endpoints API is public and unauthenticated (verified live for Kimi K3).
- Endpoint data is fetched per queried model on demand and cached, not prefetched for the whole catalog.
- LiteLLM remains in the pipeline solely as fallback/cross-check for vendor-direct pricing (e.g. z.ai GLM); it is not removed.
- The OpenRouter MCP remains an external, optional tool; this feature only documents it.
- The authoritative cache (overrides layer) and `llm-cost-estimator` behavior are unchanged by this feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of OpenRouter-routed model queries, the cheapest answer names a concrete provider with price and quantization.
- **SC-002**: Repeated cheapest queries within the TTL window require zero network activity (served from the endpoint cache).
- **SC-003**: For vendor-direct models absent from OpenRouter, cheapest still returns an answer via the LiteLLM fallback in 100% of cases where LiteLLM lists the model.
- **SC-004**: Discovery baseline entries include cache pricing for every model that exposes it, with zero regressions in the existing test suite.
- **SC-005**: README and skill documentation accurately state the new source roles (verified by review).

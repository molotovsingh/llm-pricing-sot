# Research: Cost per unit of work at a named deployment

**Feature**: `005-cost-per-unit` · **Date**: 2026-09-08

This records what was *found* on 2026-09-08 and the decisions taken. It is a historical
record and is exempt from the contract gate by path rule; it must keep saying what was
true when written.

## R1 — How accurate is the catalog today, and against what?

**Method.** Every model in the emitted cache was compared against the vendor's own
pricing page, then against per-host prices at Together, Baseten, z.ai, DeepInfra.

**Findings.**

| Layer | Result |
|---|---|
| OpenRouter catalog vs vendor list (proprietary) | 6/6 exact: gpt-5.6-luna, gpt-5.2, gpt-4o, claude-sonnet-4.6, claude-haiku-4.5, kimi-k3 |
| OpenRouter catalog vs vendor list (open-weight) | 3/3 *below* list — Sol is a promo equal to OpenAI's Flex tier; GLM and DeepSeek are third-party hosts, not the vendor |
| OpenRouter endpoints vs host's own page | 7/7 exact: Together ×3, Baseten ×3, Z.AI ×1 |
| HF router vs host's own page | 6/7 exact; the miss is DeepInfra's 35% promo, which HF had not ingested |

**Decision.** The catalogs are trustworthy *verifiers* of per-host per-token prices. The
error was never in the numbers — it was in serving the *cheapest* host's number when
the user's host was a different one.

## R2 — Do specialist models have per-token providers?

**Method.** Hub search for "ocr" by downloads (100 models); 24 known-good OCR models by
id; both cross-referenced against the HF router and OpenRouter's catalog.

**Findings.** 4/100 have any provider; 0/100 have a router price. Of the 24 named
models, only DeepSeek-OCR (Novita), GLM-OCR (z.ai) and typhoon-ocr (Featherless) are
served at all, and HF shows a price for none. chandra-ocr-2 (2.9M downloads), Unlimited-OCR
(2.7M), DeepSeek-OCR-2 (963K), GOT-OCR2 (680K), Florence-2 (618K), Nanonets-OCR-s,
dots.ocr, granite-docling, olmOCR, PaddleOCR-VL — none has a provider.

Three distinct causes of "listed, no price": the provider is flat-rate (Featherless:
$10–75/mo, unlimited tokens); the provider has a price HF has not ingested (z.ai GLM-OCR
$0.03/$0.03; Novita DeepSeek-OCR-2 $0.03/$0.03); the model is not a chat model (all of
PaddleOCR, `image-to-text` pipeline).

**Decision.** Do not chase provider coverage for specialists — it is ~zero and not going
to appear. Price them in the units they are actually sold in, or derive self-host cost.

## R3 — What units are specialist models actually sold in?

Same model, DeepSeek-OCR, on 2026-09-08:

| Where | Unit | Price |
|---|---|---|
| Novita (via HF) | per 1M tokens | $0.03 / $0.03, 8K ctx |
| Replicate `lucataco/deepseek-ocr` | per run | ≈ $0.014, L40S, ~15 s |
| Datalab Marker on Replicate | per page | $6 / 1,000 |
| Self-host | per GPU-hour | ~200K pages/day on one A100 (DeepSeek's figure) |
| Featherless (typhoon-ocr) | per month | $10–75, unlimited tokens |

From Novita's 8K context alone a request cannot exceed ~$0.0005 in tokens, so Replicate
is ≥28× dearer per page for the same weights. That is the cost decision, and a per-token
field cannot express it.

**Decision.** Vocabulary: `per_1m_tokens`, `per_page`, `per_run`, `per_gpu_hour`,
`per_month`. Defined once in code; derived into documents by the gate. Anything else is
rejected at validation.

## R4 — Is the HF router a contract the repo can depend on?

**Finding.** `GET https://router.huggingface.co/v1/models` answers without auth (HTTP
200, 139 chat models, 14 providers on 2026-09-08). HF's Hub API documentation specifies
the response, including `pricing` as *"input and output prices in USD per million
tokens, when available"*, plus `context_length`, `status`, `first_token_latency_ms`,
`throughput`. A per-model path `/v1/models/{org}/{model}` is documented; it wraps the
object in `data`. The README's 2026-08-30 note "router API is auth-walled" is stale.

**Decision.** Add it as a **demoted** source with the LiteLLM failure semantics (reuse
last known layer; never discard a healthy refresh). Persist under `discovery.json.hf_router`
keyed by Hub id. Map to tracked models via an optional `hf_id` override field. HF's MCP
server exposes no pricing tool — the REST endpoint is the contract.

## R5 — Where does a self-hosted price come from?

**Finding.** It does not exist as a published number. It is `GPU $/hr × seconds per
unit / 3600`. GPU rates are published (RunPod Secure Cloud on 2026-09-08: L40S $1.09,
A100-80GB $1.59, H100 SXM $3.49, L4 $0.49; Modal per-second: L40S $1.95, A100-80GB $2.50,
H100 $3.95, L4 $0.80, A10 $1.10, T4 $0.59). Seconds per unit is a **measurement** the
user's benchmark already produces.

**Decision.** `gpu_rates.json`: a small attested table keyed `<gpu>@<provider>` —
never averaged across providers, because the user pays one of them. A derived
deployment names the rate key, the seconds figure, and the benchmark run id that
produced it. This repo records the run id; it does not integrate with the benchmark.
The bench writes the entry (or the user does); the pipeline prices it.

**Rejected:** fetching GPU rates automatically. They change slowly, vary by tier
(Secure vs Community, on-demand vs spot) in ways a scraper would flatten, and the user
pays exactly one of them. A curated, attested, expiring table is the honest shape —
the same posture the repo already takes for negotiated rates.

## R6 — Backward compatibility

**Finding.** The user stated other agents (Hermes, Pi) use the repo infrequently;
`llm-cost-estimator` is the live consumer and reads `models[*].in/out/tokenizer`.

**Decision.** Additive anyway — it costs nothing and the constitution's Development
Workflow already requires it. `models` entries gain one field (`unit`); the envelope
gains one key (`deployments`); nothing is renamed or moved. The estimator is re-run
end-to-end as an acceptance check, not modified.

## R7 — Host name canonicalisation

**Finding.** The same host appears as `BaseTen` (OpenRouter) and `baseten` (HF);
`Fireworks` and `fireworks-ai`; `Z.AI`, `zai-org`, `z-ai`; `Moonshot AI`, `moonshotai`.

**Decision.** Canonicalise by lowercasing and stripping non-alphanumerics, then apply a
small declared alias table for the known multi-form names. Unknown names stay distinct
rather than being fuzzily merged — a false merge would silently price one host as
another, which is the exact failure `_resolve_slug` was fixed for in `2acd8b9`.

## R8 — Constitution impact

Principle II names `overrides.json` as *the* truth layer and the Data constraints say
prices MUST be USD per 1M tokens. Both are redefined: the truth layer becomes
`overrides.json` + `deployments.json` (+ `gpu_rates.json` as an input to it), and every
price carries a unit. HF joins LiteLLM as a demoted source under Principle IV. Per the
Governance section that is **MAJOR**: 2.0.0 → 3.0.0, with a Sync Impact Report, matching
the precedent of the 1.0.0 → 2.0.0 amendment.

# Quickstart: pricing what you actually run

**Feature**: `005-cost-per-unit` · **Date**: 2026-09-08

## Ask for a price at your host

```bash
python fetch_pricing.py query hosts glm-5.2                   # every host that serves it, cheapest first
python fetch_pricing.py query price glm-5.2 --host together    # the price at Together, not the cheapest host
python fetch_pricing.py query cheapest glm-5.2 --host baseten  # cheapest SKU at Baseten only
```

`--host` names are canonical (`together`, `baseten`, `fireworks`, `zai`, `deepinfra`,
`novita`, `moonshot`, `self-host`); `BaseTen` and `baseten` are the same host.

## Record a deployment you run

Quoted — you know the price:

```json
"glm-5.2@together": {
  "model": "glm-5.2", "host": "together", "unit": "per_1m_tokens",
  "in": 1.40, "out": 4.40,
  "note": "together.ai/pricing serverless", "verified_at": "2026-09-08"
}
```

Derived — self-hosted, priced from a GPU rate and your benchmark:

```json
"deepseek-ocr@self-host": {
  "model": "deepseek-ai/DeepSeek-OCR", "host": "self-host", "unit": "per_page",
  "derive": {"gpu": "l40s@runpod", "seconds_per_unit": 0.43, "bench_run": "mwb-2026-09-07-14"},
  "note": "seconds_per_unit from Matterwork bench run", "verified_at": "2026-09-08"
}
```

Then:

```bash
python fetch_pricing.py                    # the edit is detected by fingerprint; no --force needed
python fetch_pricing.py query deployments  # every deployment, price, unit, attestation, review
python fetch_pricing.py query price deepseek-ai/DeepSeek-OCR   # a deployment-only model answers without --host
```

The derived price is `usd_per_hour × seconds_per_unit / 3600`, and the answer names the
GPU rate it used. If `derive.gpu` is not in `gpu_rates.json` you get `gpu-rate-missing`
and exit 1 — never a guessed number.

## Add a GPU rate

```json
"h100-sxm@runpod": {
  "gpu": "H100 SXM", "provider": "runpod", "tier": "secure-cloud",
  "usd_per_hour": 3.49, "note": "runpod.io/pricing", "verified_at": "2026-09-08"
}
```

Key by `<gpu>@<provider>` — you pay one provider, so rates are never averaged.

## What degrades, and why

A deployment lands in `needs_review` (exit 1) when its attestation is missing or
older than `ATTESTATION_MAX_AGE_DAYS`, when a derived entry names a GPU rate that is
missing or expired, or when `seconds_per_unit` is absent. It keeps its price in every
case except a missing input — reverting silently would change the number you believe
you pay. `query review` and `query deployments` both show the reason.

## Units

Every price says what one unit buys. The vocabulary is derived from code into the
governed documents — see the `units` block in `README.md`. A per-page price never
appears in `in`/`out`, so a consumer that multiplies `in` by a token count cannot pick
one up by mistake.

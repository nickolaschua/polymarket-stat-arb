# Training Data Acquisition Plan

## Overview

ML models (XGBoost probability calibrator, LLM relationship classifier, longshot bias detector) require training data from **resolved** Polymarket markets. This document covers how to acquire that data given Polymarket's API limitations.

---

## What We Need

| Model | Data Required | Min Dataset Size | Fields Needed |
|-------|--------------|-----------------|---------------|
| **Probability calibrator** (Strategy 1) | Market prices at various times before resolution + final outcome | 500+ resolved markets | prices over time, resolution (YES/NO), time-to-resolution |
| **LLM relationship classifier** (Strategy 5) | Pairs of market questions + their logical relationship | 200+ labeled pairs | question text, relationship label (subset/superset/independent/correlated) |
| **Longshot bias detector** (Strategy 3) | Markets where the longshot (low-prob side) won | 1000+ resolved markets | final price before resolution, actual outcome, volume |

---

## Data Sources

### Source 1: Gamma API — Resolved Markets (Primary)

The Gamma API supports fetching closed/resolved markets directly.

```
GET https://gamma-api.polymarket.com/markets?closed=true&limit=100&offset=0&order=volume&ascending=false
```

**Available fields for resolved markets:**
- `question` — The market question text
- `outcomePrices` — Final prices (stringified JSON array)
- `outcomes` — Outcome names
- `clobTokenIds` — Token IDs (for historical price lookups)
- `volume`, `volume24hr` — Trading volume
- `startDate`, `endDate`, `closedTime` — Timing
- `conditionId` — On-chain condition ID
- `active=false`, `closed=true` — Status flags

**Pagination:** Use `offset` parameter. Increment by `limit` each page.

```python
import httpx
import json
import time

async def fetch_all_resolved_markets():
    """Fetch all resolved markets from Gamma API."""
    all_markets = []
    offset = 0
    limit = 100

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "closed": "true",
                    "limit": limit,
                    "offset": offset,
                    "order": "volume",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            markets = resp.json()

            if not markets:
                break

            all_markets.extend(markets)
            offset += limit

            # Respect rate limits (~100ms between requests)
            await asyncio.sleep(0.15)

    return all_markets
```

**Expected yield:** 2,000-5,000+ resolved markets (Polymarket has been running since 2020).

### Source 2: CLOB Price History — Historical Prices

For each resolved market, we can get price history to build time-series training features.

```
GET https://clob.polymarket.com/prices-history?market={token_id}&fidelity=720
```

**CRITICAL LIMITATION:** For resolved markets, only `fidelity=720` (12-hour candles) returns data. Finer granularity returns empty arrays (known issue, GitHub #216).

```python
async def fetch_price_history(token_id: str) -> list:
    """Fetch 12-hour price candles for a token."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://clob.polymarket.com/prices-history",
            params={"market": token_id, "fidelity": 720},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("history", [])
```

**Response format:** `[{"t": 1699450000, "p": 0.52}, ...]` where `t` = Unix timestamp, `p` = price.

### Source 3: CLOB Trades — Granular Trade Data

Individual trades may still be available for resolved markets.

```
GET https://clob.polymarket.com/trades?market={condition_id}&after={unix_ts}&before={unix_ts}
```

This gives tick-level data but requires paginating through potentially thousands of trades per market.

### Source 4: Events API — Multi-Outcome Markets

For the combinatorial strategy, we need related markets grouped by event.

```
GET https://gamma-api.polymarket.com/events?closed=true&limit=100&offset=0
```

Events with `negRisk=true` and multiple nested markets are the key training data for the LLM relationship classifier.

### Source 5: Real-Time Collection (Ongoing)

Set up a data pipeline that collects from active markets. This builds your highest-quality dataset over time.

```
Active Markets Pipeline:
  1. Gamma API polling (every 60s) → market metadata snapshots
  2. CLOB WebSocket subscription → real-time price ticks
  3. GET /trades polling (every 5s) → individual trade records

Store in SQLite/PostgreSQL with schema:
  - markets: id, question, outcomes, event_id, created_at, resolved_at, resolution
  - price_snapshots: market_id, token_id, price, timestamp
  - trades: trade_id, market_id, token_id, price, size, timestamp
```

---

## Data Collection Script

```python
#!/usr/bin/env python3
"""Collect resolved market data for ML training."""

import asyncio
import json
import logging
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("data/training")


async def collect_resolved_markets():
    """Main collection pipeline."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: Fetch all resolved markets
        logger.info("Fetching resolved markets from Gamma API...")
        markets = []
        offset = 0

        while True:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "closed": "true",
                    "limit": 100,
                    "offset": offset,
                    "order": "volume",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            batch = resp.json()

            if not batch:
                break

            markets.extend(batch)
            offset += 100
            logger.info(f"  Fetched {len(markets)} markets so far...")
            await asyncio.sleep(0.15)

        logger.info(f"Total resolved markets: {len(markets)}")

        # Save raw market data
        with open(OUTPUT_DIR / "resolved_markets.json", "w") as f:
            json.dump(markets, f, indent=2)

        # Step 2: Fetch price history for top markets by volume
        logger.info("Fetching price histories...")
        price_histories = {}

        for i, market in enumerate(markets[:500]):  # Top 500 by volume
            token_ids = json.loads(market.get("clobTokenIds", "[]"))
            if not token_ids:
                continue

            for token_id in token_ids[:1]:  # YES token only
                try:
                    resp = await client.get(
                        "https://clob.polymarket.com/prices-history",
                        params={"market": token_id, "fidelity": 720},
                    )
                    resp.raise_for_status()
                    history = resp.json().get("history", [])
                    if history:
                        price_histories[token_id] = {
                            "market_id": market.get("id"),
                            "question": market.get("question"),
                            "history": history,
                        }
                except Exception as e:
                    logger.warning(f"  Failed for {token_id[:20]}...: {e}")

                await asyncio.sleep(0.15)

            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i + 1}/500 markets")

        with open(OUTPUT_DIR / "price_histories.json", "w") as f:
            json.dump(price_histories, f, indent=2)

        logger.info(
            f"Collected price history for {len(price_histories)} tokens"
        )

        # Step 3: Fetch resolved events for combinatorial training data
        logger.info("Fetching resolved events...")
        events = []
        offset = 0

        while True:
            resp = await client.get(
                "https://gamma-api.polymarket.com/events",
                params={
                    "closed": "true",
                    "limit": 100,
                    "offset": offset,
                    "order": "id",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            batch = resp.json()

            if not batch:
                break

            events.extend(batch)
            offset += 100
            await asyncio.sleep(0.15)

        # Filter to multi-outcome events
        multi_outcome_events = [
            e for e in events if len(e.get("markets", [])) >= 2
        ]

        with open(OUTPUT_DIR / "resolved_events.json", "w") as f:
            json.dump(multi_outcome_events, f, indent=2)

        logger.info(
            f"Total resolved events: {len(events)}, "
            f"multi-outcome: {len(multi_outcome_events)}"
        )


if __name__ == "__main__":
    asyncio.run(collect_resolved_markets())
```

---

## Dataset Structure

After collection, organize into these training datasets:

### 1. Probability Calibration Dataset

```
data/training/probability_calibration.csv

Columns:
  market_id, question, yes_price_at_T, time_to_resolution_hours,
  volume_24h, open_interest, actual_outcome (1=YES, 0=NO)
```

Build by sampling price snapshots at different time-to-resolution intervals (e.g., 7 days, 3 days, 1 day, 12 hours before resolution).

### 2. Relationship Classification Dataset

```
data/training/market_relationships.jsonl

Each line:
{
  "market_a": "Will Trump win the 2024 election?",
  "market_b": "Will the Republican nominee win?",
  "relationship": "subset",  // subset | superset | independent | correlated
  "event_id": "...",
  "confidence": 1.0
}
```

**Labeling strategy:**
- Markets within the same negRisk event → "mutually_exclusive"
- Markets in the same event but different types → manual or LLM-assisted labeling
- Markets across events → use keyword/entity overlap as a starting heuristic, then manually verify a validation set of ~50 pairs

### 3. Longshot Bias Dataset

```
data/training/longshot_analysis.csv

Columns:
  market_id, question, final_yes_price, final_no_price,
  actual_outcome, volume, time_active_days
```

Focus on markets where one side was priced below 0.15 (longshot territory).

---

## Bootstrap Timeline

| Phase | Action | Duration | Expected Yield |
|-------|--------|----------|----------------|
| **Week 1** | Run collection script for resolved markets + price histories | 2-3 hours of API calls | 2,000+ markets, 500 price histories |
| **Week 1** | Set up real-time collection pipeline on server | 1 day dev | Ongoing data from day 1 |
| **Week 2** | Build probability calibration dataset from collected data | 1 day | 500+ calibration samples |
| **Week 2** | Label 200 market relationship pairs (semi-automated) | 2-3 days | 200 labeled pairs for LLM fine-tuning |
| **Week 3** | Train initial XGBoost calibrator, evaluate | 1 day | Baseline model |
| **Week 3** | Build longshot bias dataset, analyze patterns | 1 day | Statistical edge analysis |

---

## Storage Requirements

| Dataset | Estimated Size | Format |
|---------|---------------|--------|
| Resolved markets metadata | ~50 MB | JSON |
| Price histories (500 markets, 12h candles) | ~5 MB | JSON |
| Real-time price ticks (per month of collection) | ~200 MB | SQLite |
| Trade records (per month) | ~500 MB | SQLite |
| **Total bootstrap** | **~60 MB** | |
| **Total after 1 month of live collection** | **~800 MB** | |

---

## Key Limitations

1. **12-hour minimum granularity for resolved markets** — Cannot get minute-level or hourly data for markets that have already closed. This limits backtesting precision.

2. **No official "resolution outcome" field** — The Gamma API doesn't have a clean `resolution: "YES"` field. You must infer from final prices (price ≈ 1.00 = that outcome won) or check on-chain settlement data.

3. **Rate limits** — ~1,000 requests/hour for Gamma API. The full collection script should take 2-3 hours for the initial crawl.

4. **Data quality** — Some markets have minimal volume, broken price feeds, or were resolved via admin action. Filter to markets with `volume > 1000` for reliable training data.

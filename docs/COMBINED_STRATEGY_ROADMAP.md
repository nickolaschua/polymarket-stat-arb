# Combined Strategy Roadmap: Probability Arbitrage + Combinatorial Arbitrage

## Critical Reality Check (Read This First)

The IMDEA paper deep dive revealed something important that changes the strategy balance:

| Finding | Impact |
|---------|--------|
| **Combinatorial arb generated only $95K** vs. **$10.58M for single-market rebalancing** | Combinatorial is 0.24% of total arb profit. Single-market rebalancing dominates 111x. |
| **97.3% false positive rate** on LLM dependency detection | Most LLM-detected "dependencies" are false positives. Only 13 of 1,576 were genuine. |
| **62% execution failure rate** on correctly identified dependencies | Even when the relationship is real, execution often fails (liquidity, timing, slippage). |
| **Rule-based arb needs NO LLM** | Exhaustive partitions (conditions summing to >100%) and temporal consistency violations are detectable with pure arithmetic. |

**Revised strategy**: Don't lead with LLM-based combinatorial detection. Lead with rule-based relationship detection (free, instant, high frequency), then layer in probability modeling, then optionally add LLM-based detection as a refinement.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    SHARED INFRASTRUCTURE                          │
│  (Built once, used by both strategies)                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐  │
│  │ Market Data  │  │ Embedding    │  │ Trade Execution Engine  │  │
│  │ Collector    │  │ Pipeline     │  │                         │  │
│  │             │  │              │  │  - Order placement      │  │
│  │ - Gamma API │  │ - nomic-     │  │  - Position tracking    │  │
│  │ - CLOB API  │  │   embed-text │  │  - Kelly sizing         │  │
│  │ - WebSocket │  │ - ChromaDB   │  │  - Paper trade mode     │  │
│  │ - SQLite    │  │ - Similarity │  │  - Risk limits          │  │
│  │   storage   │  │   search     │  │                         │  │
│  └──────┬──────┘  └──────┬───────┘  └───────────┬─────────────┘  │
│         │                │                       │                │
├─────────┴────────────────┴───────────────────────┴────────────────┤
│                                                                    │
│  ┌────────────────────────┐    ┌────────────────────────────────┐ │
│  │  STRATEGY 5 (PRIMARY)  │    │  STRATEGY 1 (PRIMARY)          │ │
│  │  Combinatorial Arb     │    │  Probability Arbitrage         │ │
│  │                        │    │                                │ │
│  │  Phase A: Rule-based   │    │  - Feature engineering         │ │
│  │  - Partition sums      │    │  - ML probability model        │ │
│  │  - Temporal consistency│    │  - Venn-ABERS calibration      │ │
│  │  - NegRisk rebalancing │    │  - Kelly position sizing       │ │
│  │                        │    │  - Category specialization     │ │
│  │  Phase B: LLM-enhanced │    │                                │ │
│  │  - State space enum    │    │                                │ │
│  │  - Fine-tuned model    │    │                                │ │
│  │  - Multi-hop reasoning │    │                                │ │
│  └────────────────────────┘    └────────────────────────────────┘ │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Synergies: Build Once, Use Twice

These components serve BOTH strategies. Building them first gives you maximum leverage.

### 1. Market Data Collector & Database
- Fetches all active markets from Gamma API every 5-10 minutes
- Stores current prices, volumes, outcomes, resolution criteria in SQLite
- Records historical snapshots (critical — Polymarket doesn't provide fine-grained history for resolved markets)
- WebSocket feed for real-time price updates on monitored markets

**Used by Strategy 5**: Needs current prices for all markets to detect partition/temporal violations
**Used by Strategy 1**: Needs price history for feature engineering + backtesting

### 2. Embedding Pipeline (nomic-embed-text-v1.5 + ChromaDB)
- Embeds all market questions into 768-dim vectors
- Stores in ChromaDB with metadata (category, volume, dates, prices)
- Enables fast semantic similarity search

**Used by Strategy 5**: Groups similar markets for relationship detection
**Used by Strategy 1**: Finds related markets as features (related market prices improve probability estimates)

### 3. Trade Execution Engine
- Kelly criterion position sizing with Venn-ABERS calibration uncertainty
- Order placement via py-clob-client
- Paper trade mode (log trades without executing)
- Position tracking, P&L calculation
- Risk limits (max position size, max total exposure, max per category)

**Used by both**: Identical execution logic, different signal sources

### 4. Backtesting Framework
- Walk-forward validation on historical data
- Brier score measurement (your model vs. market)
- Simulated P&L with realistic fee assumptions
- Model calibration validation

**Used by both**: Strategy 5 backtests arb detection accuracy; Strategy 1 backtests probability model quality

### 5. Monitoring & Alerting
- Telegram alerts for detected opportunities and executed trades
- Dashboard for P&L, open positions, model performance
- Error alerting (API failures, rate limits, unexpected behavior)

---

## Infrastructure Decision

### Recommendation: Hetzner CPX31 (Frankfurt, Germany)

| Spec | Value |
|------|-------|
| vCPUs | 4 (AMD EPYC) |
| RAM | 8 GB |
| Storage | 160 GB NVMe |
| Location | Germany (not geoblocked) |
| Latency to CLOB | ~15-25ms |
| **Monthly cost** | **~$14/month** |

Why not AWS: 5x more expensive for equivalent specs. AWS t3.large is ~$46-68/month. For a stat-arb strategy with hours-to-days holding periods, the latency difference is irrelevant.

### Total Monthly Costs

| Item | Cost |
|------|------|
| Hetzner CPX31 | $14/month |
| LLM API (DeepSeek/GPT-4o-mini for classification) | $5-15/month |
| Verification LLM (GPT-4o/Claude for trade confirmation) | $2-5/month |
| News/sentiment API (optional, Phase 2) | $0-50/month |
| **Total (Phase 1)** | **~$20-35/month** |
| **Total (Full stack)** | **~$35-85/month** |

### Trading Capital

| Phase | Capital | Max per position |
|-------|---------|-----------------|
| Paper trading | $0 | N/A |
| Initial live | $500-1,000 | $50 (5%) |
| Validated live | $1,000-2,000 | $100 (5-10%) |
| Scaled | $2,000+ | Based on proven edge |

---

## Component Breakdown: AI-Buildable vs. Human Attention

Each component is classified:

- **AI** = Can be fully built by Claude Code agent loops with minimal supervision
- **GUIDED** = AI builds the scaffolding, you review and guide decisions
- **HUMAN** = Requires your domain expertise, judgment, or manual work

### Shared Infrastructure

| # | Component | AI Level | Effort | Notes |
|---|-----------|----------|--------|-------|
| S1 | Project scaffolding (config, logging, CLI) | **AI** | 2-3 hrs | Already partially built. Extend existing `src/` structure. |
| S2 | Gamma API market fetcher with pagination | **AI** | 3-4 hrs | Straightforward HTTP client. Handle stringified JSON parsing. |
| S3 | SQLite database schema + ORM | **AI** | 3-4 hrs | Markets, prices, trades, positions, model_predictions tables. |
| S4 | Historical data collection pipeline | **AI** | 4-5 hrs | Periodic fetcher that snapshots prices to SQLite. WebSocket recorder. |
| S5 | Embedding pipeline (nomic-embed-text + ChromaDB) | **AI** | 3-4 hrs | Install models, embed markets, store in ChromaDB. |
| S6 | Trade execution engine (paper mode) | **AI** | 4-6 hrs | Kelly sizing, order creation, paper trade logging. |
| S7 | Trade execution engine (live mode) | **GUIDED** | 3-4 hrs | Review risk limits, verify order signing, test with tiny amounts. |
| S8 | Position tracker + P&L calculator | **AI** | 3-4 hrs | Track open positions, mark-to-market, calculate realized/unrealized P&L. |
| S9 | Telegram alerting | **AI** | 2-3 hrs | python-telegram-bot integration for trade alerts. |
| S10 | Deployment scripts (Hetzner setup) | **GUIDED** | 2-3 hrs | Systemd service, auto-restart, log rotation. Review security. |
| S11 | Private key management | **HUMAN** | 1-2 hrs | Generate wallet, fund with USDC, store key securely. Never in code. |

### Strategy 5: Combinatorial Arbitrage

| # | Component | AI Level | Effort | Notes |
|---|-----------|----------|--------|-------|
| C1 | Exhaustive partition detector (rule-based) | **AI** | 3-4 hrs | For multi-outcome events: check if condition prices sum to >$1. Pure arithmetic. No LLM needed. |
| C2 | NegRisk rebalancing detector | **AI** | 2-3 hrs | For negRisk events: check if YES+NO < $1 within same condition. Already stubbed in codebase. |
| C3 | Temporal consistency detector (rule-based) | **GUIDED** | 4-5 hrs | Parse dates from market questions. "BTC > 100k in Feb" <= "BTC > 100k in 2026". Needs regex patterns you review. |
| C4 | Subset relationship detector (rule-based) | **GUIDED** | 3-4 hrs | Pattern matching for known subset structures (candidate → party, city → country). Semi-automated. |
| C5 | Semantic similarity grouping | **AI** | 3-4 hrs | Use embedding pipeline to find similar markets. Threshold tuning. |
| C6 | LLM state space enumeration | **GUIDED** | 6-8 hrs | Implement IMDEA methodology. Prompt engineering + validation. You review prompt quality. |
| C7 | LLM response validation pipeline | **AI** | 3-4 hrs | JSON parsing, consistency checks, false positive filtering. Programmatic. |
| C8 | Multi-leg execution handler | **GUIDED** | 4-6 hrs | Execute 2-3 orders near-simultaneously. Handle partial fills. You review logic. |
| C9 | Arbitrage P&L calculator with fees | **AI** | 2-3 hrs | Calculate net profit after Polymarket fees (0.01% trade + 2% winner). |
| C10 | Fine-tuning data collection | **HUMAN** | 8-15 hrs | Run GPT-4o on 500 market pairs, then manually review/correct the ~20% errors. This is the labeling work. |
| C11 | Model fine-tuning (GPT-4o-mini or Llama) | **GUIDED** | 3-4 hrs | Upload data, run fine-tuning job. AI handles mechanics, you evaluate results. |
| C12 | Backtesting on historical arb opportunities | **GUIDED** | 4-6 hrs | Validate detection accuracy on resolved markets. You interpret results. |

### Strategy 1: Probability Arbitrage

| # | Component | AI Level | Effort | Notes |
|---|-----------|----------|--------|-------|
| P1 | Feature engineering pipeline | **GUIDED** | 6-8 hrs | Define features: price history, volume, time-to-resolution, category, related market prices. You decide which features matter. |
| P2 | Base probability model (gradient boosting) | **GUIDED** | 4-6 hrs | XGBoost/LightGBM on tabular features. AI builds, you tune hyperparameters and evaluate. |
| P3 | NLP sentiment feature extractor | **AI** | 4-5 hrs | Embed news/social text with nomic-embed-text, compute sentiment scores as features. |
| P4 | Related market features (from embedding pipeline) | **AI** | 3-4 hrs | For each market, find top-5 similar markets via ChromaDB, use their prices as features. |
| P5 | Venn-ABERS calibration layer | **AI** | 3-4 hrs | Install venn-abers package, integrate with model output. Straightforward implementation. |
| P6 | Kelly criterion with calibration uncertainty | **AI** | 2-3 hrs | Standard Kelly formula adjusted by Venn-ABERS confidence interval width. |
| P7 | Walk-forward backtesting framework | **GUIDED** | 6-8 hrs | Time-series-aware validation. AI builds framework, you verify methodology is sound. |
| P8 | Brier score tracking + model monitoring | **AI** | 3-4 hrs | Track calibration over time. Alert if model degrades. |
| P9 | Category-specific model tuning | **HUMAN** | 8-12 hrs | Each category (politics, crypto, sports) needs different features and tuning. This is where domain expertise matters most. |
| P10 | News/event data integration | **GUIDED** | 4-6 hrs | Connect to news APIs, parse events, extract relevant signals. You decide which sources matter. |
| P11 | Continuous retraining pipeline | **AI** | 4-5 hrs | As markets resolve, add outcomes to training data. Retrain weekly/monthly. |
| P12 | Model A/B testing framework | **GUIDED** | 3-4 hrs | Run multiple models in parallel (paper trade), compare performance. |

---

## Effort Summary

### By AI Level

| Classification | Components | Total Hours | % of Work |
|---------------|------------|-------------|-----------|
| **AI** (agent loops handle fully) | S1-S6, S8-S9, C1-C2, C5, C7, C9, P3-P6, P8, P11 | ~55-70 hrs | ~45% |
| **GUIDED** (AI builds, you review) | S7, S10, C3-C4, C6, C8, C11-C12, P1-P2, P7, P10, P12 | ~55-70 hrs | ~45% |
| **HUMAN** (your expertise required) | S11, C10, P9 | ~17-29 hrs | ~10% |
| **Total** | 35 components | **~130-170 hrs** | |

### By Phase

| Phase | Components | Calendar Time | What Happens |
|-------|------------|---------------|-------------|
| **Phase 1**: Shared infra + Rule-based arb | S1-S11, C1-C2, C9 | Weeks 1-3 | Data collection starts. Rule-based arb running in paper mode. |
| **Phase 2**: Combinatorial detection | C3-C8, C12 | Weeks 3-5 | Temporal + subset detection. LLM classification pipeline. Paper trading. |
| **Phase 3**: Probability model | P1-P8 | Weeks 4-7 | Feature engineering, model training, calibration. Paper trading. |
| **Phase 4**: Live trading (small) | — | Weeks 7-9 | $500-1K live. Both strategies running. Monitor closely. |
| **Phase 5**: Refinement | C10-C11, P9-P12 | Weeks 9-14 | Fine-tune models, add categories, increase capital if profitable. |

---

## Detailed Implementation: Strategy 5 (Combinatorial Arbitrage)

### Phase A: Rule-Based Detection (No LLM, No ML)

This is where most of the money actually is. The IMDEA study found $10.58M from single-market rebalancing vs. $95K from combinatorial — but much of this is because the rule-based opportunities are easier to detect and execute.

#### Component C1: Exhaustive Partition Detector

**What it does**: For multi-outcome events (e.g., "Who will win the election?" with 5 candidates), check if condition prices sum to more than $1.

```python
# Pseudocode
for event in negRisk_events:
    total = sum(condition.yes_price for condition in event.conditions)
    if total > 1.0 + fee_threshold:
        opportunity = {
            'type': 'partition_violation',
            'event': event,
            'sum': total,
            'profit': total - 1.0 - fees,
            'action': 'SELL all conditions (buy NO on each)'
        }
```

**Why this works**: In a negRisk event, the conditions are mutually exclusive and exhaustive. Exactly one condition resolves YES. If you sell YES on all conditions for a combined $1.05, you pay out exactly $1.00 on the winner = $0.05 profit minus fees.

**Frequency**: Multiple opportunities per day on active markets.
**Edge**: 1-5% per trade. Near-risk-free when resolution is unambiguous.

#### Component C2: NegRisk Rebalancing (Already Stubbed)

**What it does**: Within a single binary condition, check if YES + NO < $1.

This is already partially implemented in `src/scanner/arbitrage.py`. The existing code detects these within single markets. Extend it to check across all conditions in negRisk events.

#### Component C3: Temporal Consistency Detector

**What it does**: Markets with temporal relationships must be logically consistent.

```
"BTC > $100k by Feb 28" (20%)  ≤  "BTC > $100k by Dec 31" (15%)
                                   ↑ This is a violation — yearly must be >= monthly
```

**Implementation**: Parse dates from market questions using regex + NLP. For pairs where one is a strict subset of the other's timeframe, check price consistency.

**Why GUIDED**: The date parsing regex needs your review. Edge cases in market question phrasing can cause false matches.

#### Component C4: Subset Relationship Detector (Rule-Based)

**What it does**: Detect known structural subsets without LLM.

Known patterns:
- Candidate → Party ("Trump wins" ≤ "Republican wins")
- City → State → Country
- Specific threshold → Broader threshold ("BTC > $150k" ≤ "BTC > $100k")
- Monthly → Quarterly → Yearly

**Implementation**: Maintain a lookup table of known entity relationships. Match market questions against these patterns. Rule-based, no LLM needed, but needs manual curation of the pattern library.

### Phase B: LLM-Enhanced Detection

Only pursue this AFTER Phase A is live and profitable. The IMDEA numbers show this generates much less profit, but it can still be +EV when combined with your probability model.

#### Component C6: LLM State Space Enumeration (IMDEA Method)

**What the IMDEA team actually did** (not simple classification):

1. Pass conditions from BOTH markets as numbered statements
2. Ask the LLM to enumerate ALL valid joint resolution vectors
3. If vectors < n * m (product of condition counts), markets are dependent
4. Programmatically verify the JSON structure

```python
# IMDEA-style prompt
prompt = f"""
Given these conditions from two prediction markets:
{numbered_conditions}

List ALL logically valid combinations of outcomes as JSON arrays of booleans.
Each array must have exactly one TRUE per market's condition group.
"""
```

**Critical finding**: 97.3% of LLM-detected "dependencies" were false positives. You MUST have a multi-layer validation pipeline:
1. Valid JSON parses
2. Exactly one TRUE per market group
3. Vector count < n * m
4. Cross-check with rule-based detectors
5. Manual review for first 50 trades

**Use DeepSeek ($0.14/1K calls) for initial screening**, then GPT-4o ($4/1K calls) for final verification on trades you're about to execute.

---

## Detailed Implementation: Strategy 1 (Probability Arbitrage)

### Feature Engineering (P1)

The core of this strategy is your feature set. Features fall into three categories:

#### Market-Intrinsic Features
| Feature | Source | Rationale |
|---------|--------|-----------|
| Current price (implied probability) | Gamma API `outcomePrices` | Baseline |
| 24h price change | Historical snapshots (your DB) | Momentum/mean-reversion signal |
| 7d price change | Historical snapshots | Longer-term trend |
| Volume (24h, 7d, all-time) | Gamma API | Liquidity proxy |
| Spread (bid-ask) | CLOB API | Market efficiency proxy |
| Time to resolution | Gamma API `endDate` | Closer = more certain |
| Number of conditions | Gamma API | Multi-outcome markets behave differently |
| Open interest | Gamma API | Capital committed |

#### Cross-Market Features (from Embedding Pipeline)
| Feature | Source | Rationale |
|---------|--------|-----------|
| Top-5 similar market prices | ChromaDB similarity search | Related market consensus |
| Price divergence from similar markets | Computed | Identifies outliers |
| Category average price for similar events | Computed | Base rate proxy |
| Event-level consistency score | Rule-based checks | Internal consistency |

#### External Features (Phase 2+)
| Feature | Source | Rationale |
|---------|--------|-----------|
| News sentiment score | News API + NLP | Directional bias |
| Social volume | Twitter/X API | Attention proxy |
| Polling data (political) | 538/RCP | Ground truth for political markets |
| Exchange price (crypto) | Binance/Coinbase API | Ground truth for crypto markets |
| Historical base rate | Your DB of resolved markets | Prior probability |

### Model Architecture (P2)

**Start simple, add complexity only if needed:**

```
Phase 1: XGBoost on market-intrinsic features
  → Calibrate with Venn-ABERS
  → Paper trade, measure Brier score vs. market

Phase 2: Add cross-market features from embeddings
  → Retrain, compare Brier scores
  → Go live if improvement is significant

Phase 3: Add NLP sentiment features
  → Retrain, compare
  → Only keep features that improve calibration

Phase 4: (Optional) Ensemble with LSTM for time series
  → Only if tabular model plateau'd
```

**Why XGBoost first**: It handles tabular data excellently, trains in seconds, and is interpretable. Don't reach for deep learning until you've exhausted what gradient boosting can do. Most Kaggle competitions on tabular data are still won by XGBoost/LightGBM.

### Calibration (P5)

**Use Venn-ABERS** — it's the only calibration method that provides confidence intervals, which directly inform Kelly sizing:

```python
from venn_abers import VennAbersCalibrator

# After model training
va = VennAbersCalibrator()
va.fit(model_scores_on_cal_set, actual_outcomes)

# At prediction time
p0, p1 = va.predict_proba(new_score)
calibrated = p0 / (p0 + (1 - p1))
uncertainty = p1 - p0  # Wider = less confident = bet smaller

# Kelly with uncertainty adjustment
kelly = standard_kelly(calibrated, market_price)
adjusted_kelly = kelly * max(0.1, 1.0 - uncertainty * 2)
position_size = min(adjusted_kelly * bankroll, max_position)
```

### Backtesting (P7)

**Critical constraint**: Polymarket API returns empty historical data for resolved markets at <12h granularity. This means:

1. **You cannot backtest on historical data you don't already have**
2. **Start collecting data NOW** — every day you wait is data you'll never get
3. Use 12h candles for resolved markets as a rough backtest
4. Primary validation: paper trade for 2-4 weeks, measure actual vs. predicted

**Walk-forward validation** (not random train/test split):
```
Month 1-3 data → Train model
Month 4 data → Validate (paper trade simulation)
Month 1-4 data → Retrain
Month 5 data → Validate
...repeat
```

---

## Implementation Timeline

```
WEEK 1-2: Foundation
├── S1: Project scaffolding                    [AI]
├── S2: Gamma API market fetcher               [AI]
├── S3: SQLite database schema                 [AI]
├── S4: Historical data collection pipeline    [AI]  ← START THIS FIRST
├── S5: Embedding pipeline                     [AI]
├── S11: Wallet setup + key management         [HUMAN]
└── S10: Hetzner server deployment             [GUIDED]

WEEK 2-3: Rule-Based Arb (Quick Wins)
├── C1: Exhaustive partition detector          [AI]
├── C2: NegRisk rebalancing detector           [AI]
├── C9: Arb P&L calculator with fees           [AI]
├── S6: Trade execution engine (paper mode)    [AI]
├── S8: Position tracker                       [AI]
└── S9: Telegram alerting                      [AI]
    → Paper trade rule-based arb

WEEK 3-5: Combinatorial Enhancement
├── C3: Temporal consistency detector          [GUIDED]
├── C4: Subset relationship detector           [GUIDED]
├── C5: Semantic similarity grouping           [AI]
├── C6: LLM state space enumeration            [GUIDED]
├── C7: LLM validation pipeline               [AI]
└── C8: Multi-leg execution handler            [GUIDED]
    → Paper trade full combinatorial system

WEEK 4-7: Probability Model
├── P1: Feature engineering                    [GUIDED]
├── P2: Base probability model (XGBoost)       [GUIDED]
├── P3: NLP sentiment features                 [AI]
├── P4: Related market features                [AI]
├── P5: Venn-ABERS calibration                 [AI]
├── P6: Kelly sizing                           [AI]
├── P7: Walk-forward backtesting               [GUIDED]
└── P8: Brier score monitoring                 [AI]
    → Paper trade probability model

WEEK 7-9: Go Live
├── S7: Live execution engine                  [GUIDED]
├── C12: Validate arb detection on historicals  [GUIDED]
├── Start with $500-1,000
├── Max 5% per position
└── Monitor daily, adjust weekly

WEEK 9-14: Refinement
├── C10: Fine-tuning data collection           [HUMAN]
├── C11: Model fine-tuning                     [GUIDED]
├── P9: Category-specific tuning               [HUMAN]
├── P10: News/event data integration           [GUIDED]
├── P11: Continuous retraining pipeline        [AI]
└── P12: Model A/B testing                     [GUIDED]
```

---

## Cost Summary

### One-Time Costs

| Item | Cost | Notes |
|------|------|-------|
| Wallet funding (USDC) | $500-2,000 | Your trading capital |
| Polygon gas for approval txns | ~$1-5 | One-time token approvals |
| Fine-tuning LLM (if pursued) | ~$0.50-2.00 | GPT-4o-mini fine-tune on 500 examples |
| GPU rental for fine-tuning (if Llama) | ~$0.50-1.00 | vast.ai spot instance for 1-2 hours |

### Monthly Recurring Costs

| Item | Phase 1 | Full Stack |
|------|---------|------------|
| Hetzner CPX31 | $14 | $14 |
| LLM API (DeepSeek/GPT-4o-mini) | $5 | $15 |
| Verification LLM (GPT-4o on trade execution) | $0 | $5 |
| News API (optional) | $0 | $0-50 |
| Domain + monitoring (optional) | $0 | $5-10 |
| **Total** | **~$19/month** | **~$40-95/month** |

### Break-Even Analysis

At $19/month infrastructure cost with $1,000 trading capital:
- Need 1.9% monthly return just to cover costs
- At 3-5% monthly return (conservative estimate): **$30-50/month net profit**
- At 5-10% monthly return (if model is well-calibrated): **$50-100/month net profit**
- Compound effect: $1,000 at 5% monthly for 12 months = ~$1,796

The strategy becomes more capital-efficient as you scale. At $5K capital, the same 5% monthly = $250/month on $40 costs.

---

## What To Build First (Priority Order)

### Priority 1: Data Collection (Start Immediately)

**Why**: Polymarket does not provide fine-grained historical data for resolved markets. Every day you delay, you lose data you can never recover. Even before you build anything else, get a data collector running.

```
Deploy data collector on Hetzner → snapshot all market prices every 15 min → SQLite
```

This is 100% AI-buildable and should be the first thing deployed.

### Priority 2: Rule-Based Arb Detection

**Why**: Requires no ML, no LLM, no external APIs. Pure arithmetic on data you're already collecting. Proven to generate the majority of arb profits.

### Priority 3: Probability Model (MVP)

**Why**: This is where your ML skills create the most durable edge. Start with simple features (market-intrinsic only), add complexity only when the simple model plateaus.

### Priority 4: LLM-Based Combinatorial (Optional Refinement)

**Why**: The IMDEA data shows this generates 0.24% of total arb profits with a 97% false positive rate. Worth exploring but should NOT be the priority. Only pursue after rule-based arb and probability model are live and profitable.

---

## References

- [IMDEA: "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"](https://arxiv.org/abs/2508.03474)
- [Semantic Trading (Columbia/IBM, Dec 2025)](https://arxiv.org/abs/2512.02436)
- [Lead-Lag LLM Paper (Feb 2026)](https://arxiv.org/abs/2602.07048)
- [Venn-ABERS Calibration](https://github.com/ip200/venn-abers)
- [nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Polymarket py-clob-client](https://github.com/Polymarket/py-clob-client)
- [Polymarket Agents (Official AI Framework)](https://github.com/Polymarket/agents)
- [QuantPedia: Systematic Edges in Prediction Markets](https://quantpedia.com/systematic-edges-in-prediction-markets/)

*Compiled: 2026-02-15*

# Polymarket Statistical Arbitrage Bot

## What This Is

An autonomous multi-strategy arbitrage bot for Polymarket prediction markets. Detects mispriced opportunities across 8,000+ active markets using LLM-powered relationship detection, ML probability estimation, and behavioral bias exploitation. Trades programmatically via GTC limit orders with Kelly criterion sizing, running 24/7 from a Hetzner EU server.

## Core Value

Build a complete data-to-trading pipeline: collect minute-level market data, detect mispricings through combinatorial logic and calibrated probability models, and execute trades automatically with proper risk management.

## Requirements

### Validated

- ✓ Polymarket API client wrapper (Gamma, CLOB, Data, WebSocket) — existing
- ✓ Market scanner with same-market arbitrage detection (YES+NO<$1.00) — existing
- ✓ Configuration system (Pydantic + YAML + env vars) — existing
- ✓ Retry logic with exponential backoff and rate limiting (token-bucket) — existing
- ✓ Circuit breaker for automatic trading halt on losses — existing
- ✓ Heartbeat manager for CLOB order keepalive (8s interval) — existing
- ✓ CLI interface (scan, run, check, price, book commands) — existing
- ✓ Comprehensive research & strategy documentation (21 docs) — existing

### Active

- [ ] **Data collection daemon** — 24/7 TimescaleDB pipeline: price snapshots (60s), orderbook (5min), WebSocket trades, market metadata (5min), resolution tracking
- [ ] **Embedding pipeline** — sentence-transformers + ChromaDB for semantic market similarity search
- [ ] **Rule-based combinatorial detection** — Partition sum checks, temporal consistency, subset/superset relationships, NegRisk rebalancing
- [ ] **LLM relationship classification** — IMDEA state space enumeration methodology with 8-filter validation pipeline
- [ ] **Probability model** — XGBoost on market-intrinsic + cross-market features, Venn-ABERS calibration for uncertainty quantification
- [ ] **Trade execution engine** — Kelly criterion sizing, order placement via py-clob-client, position tracking, paper trade mode
- [ ] **Backtesting framework** — Walk-forward validation, Brier score tracking, slippage simulation
- [ ] **Live trading with risk management** — Circuit breaker integration, max position limits (5% per trade, 20% per category), Telegram alerts
- [ ] **Hetzner deployment** — CPX31 Frankfurt, Docker for TimescaleDB, age-encrypted private key, systemd service

### Out of Scope

- HFT / momentum strategies — 15-25ms latency makes sub-200ms arb unviable, dynamic fees actively fight this
- Cross-platform arbitrage (Polymarket vs Kalshi) — capital split, geoblocking complexity, thin post-fee margins
- Fine-tuned LLMs — use API-based LLMs first, fine-tune only if profitable and data supports it
- Mobile app / web dashboard — CLI and Telegram alerts sufficient for solo operation
- Multi-user / team features — solo developer, solo trader

## Context

**Market Opportunity:**
- $40M in arbitrage extracted from Polymarket over 12 months (IMDEA 2025 study)
- Only 0.51% of wallets earned >$1K profit — concentrated advantage for sophisticated players
- Combinatorial arb is least competitive ($95K of $40M) — most traders lack LLM infrastructure
- 41% of market conditions showed arbitrage opportunities at some point

**Academic Foundation:**
- IMDEA (2025): Comprehensive arbitrage taxonomy, LLM dependency detection methodology
- Semantic Trading (Columbia/IBM, 2025): 60-70% relationship accuracy sufficient for profitability
- Lead-Lag (2026): LLM semantic filtering improved P&L by 205% over pure statistical methods
- Wolfers & Zitzewitz (2006): Prediction market prices deviate significantly near extremes

**Critical Data Constraint:**
- Polymarket only offers 12-hour candles for resolved markets (GitHub issue #216, unfixed)
- Minute-level training data must be collected in real-time — cannot be obtained retroactively
- Every day without data daemon running = permanently lost training data

**Latency Reality:**
- Our latency: 15-25ms (Hetzner Frankfurt → CLOB in London)
- Same-market arb half-life: <200ms (too fast for us)
- Our hold periods: hours to days (latency irrelevant)
- We're a quantitative research bot that trades, not an HFT bot

## Constraints

- **Capital:** Paper trade first, fund based on demonstrated profitability. Target $500-2K initial live capital.
- **Infrastructure:** Hetzner CPX31 Frankfurt ($14/mo), 4 vCPU, 8GB RAM, 160GB NVMe. Non-geoblocked German IP.
- **Database:** TimescaleDB from day 1 (Docker locally + Hetzner). asyncpg directly, no ORM.
- **Dev Environment:** Windows local development, Hetzner Linux production. asyncio requires WindowsSelectorEventLoopPolicy on Windows.
- **API Rate Limits:** Gamma 200/10s, CLOB read 1000/10s, CLOB trade 400/10s (70% safety margins)
- **Execution Model:** GTC limit orders, 1-10 trades/day. Not aggressive market orders.
- **Geoblocking:** Must use EU-based server IP. Never access trading wallet from blocked country.
- **LLM Provider:** Decide when needed. Options: DeepSeek ($0.14/1K), GPT-4o-mini ($0.24/1K), local Llama 3.1 8B.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| TimescaleDB over SQLite for data daemon | Time-series optimized, compression, continuous aggregates. Matches production from day 1. | — Pending |
| asyncpg directly, not SQLAlchemy ORM | TimescaleDB features need raw SQL. asyncpg is 3x faster for bulk inserts. | — Pending |
| Hetzner over AWS | $14/mo vs $43/mo. Sufficient for our needs. Same Frankfurt region. | — Pending |
| GTC limit orders, not market orders | At 15-25ms latency, edge comes from better estimates not faster execution. | — Pending |
| Paper trade before live | Validate model calibration (Brier score) before risking capital. | — Pending |
| Combinatorial arb as primary strategy | Least competitive, near-risk-free when correct, leverages LLM expertise. | — Pending |
| Data daemon as first implementation | Prerequisite for ML training. Every day of delay = lost data forever. | — Pending |
| 70% rate limit safety margins | Avoid hitting hard limits. Better to under-utilize than get banned. | ✓ Good |
| Pydantic for config validation | Type-safe, consistent with existing codebase. | ✓ Good |
| py-clob-client as CLOB SDK | Official Polymarket library. Must track API changes. | ✓ Good |

---
*Last updated: 2026-02-16 after initialization*

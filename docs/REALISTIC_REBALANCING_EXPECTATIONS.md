# Realistic Rebalancing & Latency Expectations

## Overview

This document sets honest expectations about which strategies are viable at different latency tiers. Our infrastructure (Hetzner Germany, 15-25ms to Polymarket CLOB in eu-west-2) has implications for which strategies can generate consistent fills.

---

## Latency Tiers and Strategy Viability

| Latency | Who Has It | Viable Strategies |
|---------|-----------|-------------------|
| **<1ms** | Co-located HFT firms, Polymarket's own market makers | Same-market arb (C1/C2), MEV-style frontrunning |
| **1-5ms** | Professional firms with AWS eu-west-2 instances + optimized clients | Fast same-market arb, reactive market making |
| **15-25ms** | **Us (Hetzner Germany / AWS Frankfurt)** | Probability arbitrage, combinatorial arb, longshot bias, mean reversion |
| **50-200ms** | Retail traders, consumer internet | Manual trading, very slow strategies |

---

## Strategy-by-Strategy Latency Analysis

### Same-Market Arbitrage (YES + NO < $1.00) — NOT viable for us

**Why:** The IMDEA study found that same-market mispricings last **<200ms on average** in liquid markets. At our 15-25ms round-trip, by the time we:
1. Detect the mispricing (~15ms to receive data)
2. Build and sign two orders (~5ms)
3. Submit both orders (~15-25ms each)

...the opportunity has likely been consumed by faster participants. The total detection-to-execution time of 50-70ms means we'd catch at most the longest-lived opportunities, which are typically in illiquid markets where execution size is tiny.

**Evidence from IMDEA study:**
- Single-market rebalancing extracted $10.58M total (impressive, but dominated by HFT-speed bots)
- 97.3% of opportunities that an automated system could detect turned out to be false positives by the time execution was attempted
- The most profitable single-market arbitrageurs were bots with sub-millisecond response times

**Our approach:** We still scan for same-market arb as a signal (it indicates market stress or thin liquidity), but we do NOT build execution around it. It's a monitoring metric, not a trading strategy.

### Combinatorial Arbitrage (Multi-Market) — Viable (our primary edge)

**Why it works at our latency:** Combinatorial mispricings persist for **hours to days**, not milliseconds. The IMDEA study found only $95K extracted from combinatorial arbitrage despite $39.59M in total arb — meaning this is massively under-exploited.

**Reasons for persistence:**
- Requires understanding logical relationships between markets (humans and simple bots can't do this at scale)
- Often involves 2-4 legs, which is more complex to execute
- Market makers don't actively cross-arbitrage between related markets
- New information affects related markets at different speeds

**Our latency disadvantage is irrelevant** because:
- We're not racing against HFT bots
- We're racing against humans who may take hours to notice a cross-market inconsistency
- Our edge is *detection* (semantic understanding), not *speed*

### Probability Arbitrage (Fair Value vs. Market Price) — Viable

**Why it works:** This strategy holds positions for hours to days. The edge comes from better probability estimation, not faster execution.

**Time horizon:** Enter when our model disagrees with market price by >X%, hold until convergence or resolution. Typical hold period: 1-7 days.

**Latency irrelevance:** A 25ms delay on entering a position you'll hold for 3 days is completely negligible.

### Longshot Bias Exploitation — Viable

**Why it works:** Behavioral bias that persists for the lifetime of a market. Longshot-priced outcomes (< $0.15) are systematically overpriced in prediction markets due to:
- Narrative-driven retail trading
- Probability distortion (people overweight small probabilities)
- Entertainment value of "what if" bets

**Time horizon:** Sell overpriced longshots, hold until resolution. Weeks to months.

### Mean Reversion — Partially viable

**Why it works at our latency:** We're looking for overreactions to news events that take hours to correct, not tick-level mean reversion.

**Caveat:** Pure mean reversion in prediction markets is weak because prices are driven by information, not random fluctuation. Only viable when combined with a probability model that says "this move was an overreaction."

---

## What This Means for Implementation Priority

### Build First (Viable at our latency)

1. **Combinatorial Arbitrage** — Highest expected value, most under-exploited
2. **Probability Arbitrage** — Strong edge if calibration model is good
3. **Longshot Bias** — Simple, persistent, well-documented in academic literature

### Build for Monitoring Only

4. **Same-Market Arb Scanner** — Useful as a market health indicator, NOT for trading

### Deprioritize

5. **Mean Reversion** — Weak standalone edge in prediction markets
6. **Momentum/Frontrunning** — Requires sub-second speed, ethically questionable

---

## Execution Timing Doesn't Need to Be Fast

For our viable strategies, order execution quality matters more than speed:

| Aspect | HFT (Same-Market Arb) | Our Strategies |
|--------|----------------------|----------------|
| Detection-to-execution | <100ms required | Minutes to hours is fine |
| Order type | Aggressive FOK/FAK | Patient GTC limit orders |
| Slippage sensitivity | Critical (eats entire edge) | Moderate (edge is 5-15%) |
| Execution rate | 100s of trades/day | 1-10 trades/day |
| Hold period | Seconds | Days to weeks |

**Our orders should be limit orders (GTC)** placed at favorable prices and left to fill. We are not trying to cross the spread aggressively. The savings from patient execution (~0.5-1% per trade) compound significantly over time.

---

## Heartbeat Implications

Since our strategies hold positions for days, not seconds:
- We only need the heartbeat running when we have active GTC orders on the book
- We do NOT need to maintain a heartbeat 24/7
- If the heartbeat fails and orders get cancelled, we simply re-place them on the next scan cycle
- This is a nuisance, not a catastrophe (unlike for an HFT market maker)

---

## Summary

**We are NOT an HFT bot.** We are a quantitative research-driven bot that:
- Uses ML models to find mispricings that persist for hours/days
- Detects semantic relationships between markets that other participants miss
- Executes with patient limit orders, not aggressive market orders
- Makes 1-10 trades per day, not 1,000

Our 15-25ms latency is perfectly adequate for this approach. The strategies that require sub-millisecond speed (same-market arb, momentum frontrunning) are explicitly not our focus.

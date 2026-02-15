# Statistical Arbitrage in Prediction Markets: Viability Analysis

## TL;DR

**Stat arb in prediction markets is viable but fundamentally different from equities.** The edge comes not from mean-reversion of prices, but from **superior probability estimation** and exploiting **behavioral biases**. Traditional pairs trading / cointegration approaches don't directly apply. Instead, you're betting your probability forecast is better than the market's.

---

## Why Traditional Stat Arb Doesn't Directly Apply

### The Core Problem

Traditional stat arb relies on:
1. **Mean reversion** — prices deviate from fair value and revert
2. **Cointegration** — pairs of assets move together long-term
3. **Continuous prices** — assets can oscillate indefinitely

Prediction markets break all three assumptions:

| Traditional Stat Arb | Prediction Markets |
|---------------------|-------------------|
| Prices revert to historical mean | Prices converge to 0 or 1 at expiry |
| No terminal payoff | Binary terminal payoff ($0 or $1) |
| Continuous time horizon | Discrete expiration |
| Mean is historical average | "Fair value" is unknowable true probability |
| Can hold indefinitely | Position dies at resolution |

### The Convergence Problem

In equities, a mispriced stock will eventually revert to fair value, and you can wait. In prediction markets:

- **Price must reach $0.00 or $1.00** at expiry — no middle ground
- **No reversion to "mean"** — there's only convergence to truth
- **Time decay isn't theta** — it's increasing certainty as information arrives

If you buy YES at $0.40 expecting mean reversion to $0.50, but the event fails, you get $0.00. There is no mean to revert to — only the binary outcome.

---

## What Actually Works: Probability Stat Arb

The viable strategy isn't price mean-reversion — it's **probability mispricing exploitation**.

### The Framework

```
Alpha = P_true - P_market

Where:
  P_market = current YES price (market's implied probability)
  P_true = your model's estimated true probability
```

If your model says 70% but market says 55%, you have +15% edge. Buy YES, size with Kelly, and if your model is calibrated, you profit over many trades.

### Why This Works

Prediction markets are **inefficient** for several documented reasons:

1. **Longshot Bias** — Retail overvalues low-probability outcomes (lottery tickets)
   - Study found: betting on favorites returned -3.64%, underdogs -26.08%
   - Systematically sell tails ($0.05-$0.15), buy favorites

2. **Recency Bias** — Prices overreact to news, then partially revert
   - Short-term negative autocorrelation in price changes
   - This IS mean-reversion, but on short timeframes (hours/days)

3. **Platform Fragmentation** — Same event priced differently across Polymarket/Kalshi
   - 2024 election showed persistent 3-5% cross-platform spreads
   - Arbitrage windows lasted minutes, not milliseconds

4. **Attention-Driven Mispricing** — High-volume markets are MORE inefficient
   - National presidential markets showed greater inefficiency than state-level
   - Retail attention ≠ information efficiency

---

## Concrete Strategies

### Strategy 1: Model-Based Probability Arbitrage

Build a model that forecasts P_true better than the market:

```python
# Inputs
- Polling data (538-style aggregation)
- Historical base rates
- Sentiment analysis (news/social)
- Time to resolution
- Related market prices (internal consistency)

# Output
P_true estimate with confidence interval

# Trade Signal
if P_true - P_market > threshold:
    BUY YES, size = kelly(edge, odds)
if P_market - P_true > threshold:
    BUY NO, size = kelly(edge, odds)
```

**Expected edge:** 3-10% over market consensus if model is well-calibrated
**Win rate:** ~55-60% (slight edge, compounded via Kelly)

### Strategy 2: Short-Term Mean Reversion (Recency Bias)

Prices overreact to news. After large moves, partial reversion occurs.

```python
# Signal
price_change_24h = current_price - price_24h_ago

if abs(price_change_24h) > 0.10:  # >10% move
    # Fade the move
    if price_change_24h > 0:
        BUY NO (expect partial reversion)
    else:
        BUY YES (expect partial reversion)
```

**Expected edge:** 1-3% per trade
**Hold time:** 1-7 days
**Risk:** News was correct, no reversion

### Strategy 3: Longshot Fade (Behavioral Bias)

Systematically sell overpriced tail events:

```python
# Find markets where
P_market < 0.15  # Low probability
P_true < P_market * 0.8  # Overpriced by >20%

# Sell YES (buy NO) in these markets
# Small size, many positions for diversification
```

**Expected edge:** Academic research shows consistent alpha
**Risk:** The "impossible" happens (fat tails)

### Strategy 4: Cross-Platform Arbitrage

```python
# Monitor same event across Polymarket + Kalshi
poly_yes = polymarket.get_price("event_X", "YES")
kalshi_no = kalshi.get_price("event_X", "NO")

if poly_yes + kalshi_no < 0.97:  # 3% profit threshold
    BUY poly_yes
    BUY kalshi_no
    # Guaranteed $1 payout, paid $0.97 = $0.03 profit
```

**Expected edge:** 1-3% per opportunity
**Risk:** Settlement divergence (different resolution criteria)

### Strategy 5: Combinatorial Consistency

Related markets must be logically consistent:

```
"Trump wins presidency" ≤ "Republican wins presidency"
"BTC > $100k in Feb" ≤ "BTC > $90k in Feb"
```

When violations occur, arbitrage exists.

---

## Realistic Expectations

### What The Data Shows

| Metric | Value | Source |
|--------|-------|--------|
| Total arb profits extracted | $40M | IMDEA 2024-2025 study |
| Top 3 wallets combined | $4.2M | Same study |
| Win rate for favorites | -3.64% | Longshot bias study |
| Win rate for underdogs | -26.08% | Longshot bias study |
| Cross-platform spread | 3-5% | 2024 election data |
| Markets with arbitrage | 41% | Polymarket analysis |

### Expected Returns (Conservative)

| Strategy | Monthly Return | Sharpe | Drawdown Risk |
|----------|---------------|--------|---------------|
| Model-based probability | 5-15% | 1.5-2.5 | Medium |
| Short-term reversion | 3-8% | 1.0-1.5 | Low |
| Longshot fade | 2-5% | 0.8-1.2 | High (tail risk) |
| Cross-platform arb | 1-3% | 3.0+ | Low |
| Combinatorial arb | 1-5% | 2.0+ | Low |

### Requirements for Profitability

1. **Calibrated probability model** — If your model is wrong, Kelly sizing magnifies losses
2. **Sufficient capital** — Need diversification across many bets
3. **Low latency for arb** — Simple arb captured in <1 second by bots
4. **Domain expertise** — Better forecasts require deep knowledge of event types

---

## Implementation Recommendations

### Phase 1: Data Collection & Backtesting
1. Collect historical Polymarket data (prices, outcomes, volumes)
2. Build probability models per event category (politics, crypto, sports)
3. Backtest mean-reversion signals on historical price changes
4. Validate model calibration (predicted 60% should win ~60%)

### Phase 2: Paper Trading
1. Run model in real-time, paper trade predictions
2. Track hit rate, P&L, Sharpe
3. Identify which event categories have most edge
4. Tune Kelly fraction for real volatility

### Phase 3: Small Live
1. Start with $500-1000 capital
2. Max 5% per position
3. Focus on highest-conviction signals
4. Track all trades, outcomes, model confidence

### Phase 4: Scale
1. Increase capital gradually (only if profitable)
2. Add more event categories
3. Add cross-platform if accessible
4. Consider automation for speed

---

## Conclusion: Is It Viable?

**Yes, but it's not traditional stat arb.**

The viable strategies are:

| Strategy | Viability | Why |
|----------|-----------|-----|
| Pairs trading / cointegration | ❌ Low | No mean to revert to — binary outcomes |
| Price mean-reversion (short-term) | ⚠️ Medium | Works on 1-7 day horizons, news overreaction |
| Probability arbitrage | ✅ High | Beat the market's forecast, Kelly size |
| Behavioral bias exploitation | ✅ High | Longshot bias is persistent and documented |
| Cross-platform arb | ✅ High | Persistent but requires capital on multiple platforms |
| Combinatorial arb | ✅ High | Logical inconsistencies exist in 41% of conditions |

The edge exists. The question is whether your probability model is better than the market's.

---

## References

1. IMDEA (2025) — "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"
2. QuantPedia (2025) — "Systematic Edges in Prediction Markets"
3. Navnoor Bawa (2025) — "The Math of Prediction Markets"
4. Clinton & Huang (2025) — "Price Discovery and Trading in Prediction Markets"
5. HackMD — "Polymarket Mispricing Strategy: An Alpha-Generating Framework"

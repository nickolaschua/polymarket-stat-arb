# Strategy 3: Short-Term Mean Reversion

## Feasibility Score: 5/10

---

## Concept

Prediction market prices overreact to news. When a market moves >10% in 24 hours, it tends to partially revert over the following 1-7 days. Fade the move, take profit on reversion.

```
Signal: |price_change_24h| > 10%
Action: Bet against the move (buy the opposite side)
Target: 50% reversion of the move
Exit: Take profit at target, stop loss if move continues, or time exit after 7 days
```

---

## What You'd Need to Implement This

### Data Requirements
- **Real-time price feeds**: WebSocket connection to Polymarket for live price updates
- **24-hour price history**: Rolling window of price changes for all active markets
- **Historical price change data**: 6-12 months of tick-level or hourly price data for backtesting
  - Need to track: price at t, price at t-24h, subsequent price path for 7 days
- **News event data**: To distinguish information moves from overreactions
- **Volume data**: Volume spikes often correlate with overreaction moves

### Resources & Compute
| Resource | Requirement | Cost Estimate |
|----------|-------------|---------------|
| WebSocket feed | Real-time Polymarket price stream | Free (Polymarket WebSocket API) |
| Historical data | 6-12 months of price/volume data | Free (scrape via APIs, ~2 weeks effort) |
| News feed | Real-time news for context | $0-50/month (Twitter/X API, NewsAPI) |
| Compute | Light — signal generation is simple math | $20-30/month |
| Non-US server | Required for Polymarket access | $30-80/month |
| Always-on monitoring | Must detect moves 24/7 | Built into the bot |

### Technical Skills Required
- Time series analysis (autocorrelation, mean reversion statistics)
- Signal processing (detecting significant moves vs. noise)
- NLP for news classification (was this an information move or overreaction?)
- Backtesting framework for event-driven strategies

---

## What Would Be Your Edge?

### The Academic Case is Mixed

**Supporting evidence:**
- QuantPedia: "Prediction markets show negative autocorrelation in daily price changes"
- Behavioral economics: Recency bias causes systematic overreaction
- Academic research confirms that momentum does NOT persist in prediction markets (unlike equities)
- Markets in a reversion regime on shorter time scales (hours-days)

**Against:**
- The ScienceDirect study "Improving prediction market forecasts by detecting and correcting possible over-reaction to price movements" found the effect exists but is modest
- Not all large moves are overreactions — some are genuine information arrival
- The reversion effect is strongest in markets with low informed-trader participation

### Where Your ML Skills Add Value

1. **Overreaction classifier**: The key challenge is distinguishing overreactions from information-driven moves. An NLP model that classifies the news driving a price move could significantly improve signal quality:
   - **Sentiment-driven moves** (e.g., viral tweet, emotional reaction): More likely to revert
   - **Data-driven moves** (e.g., poll release, official announcement): Less likely to revert

2. **Optimal entry/exit timing**: Use time series models to predict the reversion path and optimize entry timing

3. **Feature engineering**: Combine price change, volume spike, order flow imbalance, news sentiment, and time-of-day effects

### Estimated Edge: 1-3% per trade (when signal is correct)

---

## Is the Alpha Already Arbitraged Away?

### Mostly yes, and here's why:

1. **Simple to implement**: This is one of the easiest strategies to code — just monitor 24h price changes and bet against large moves. Any developer with API access can build this in a weekend.

2. **Momentum bots already exist**: The same bots that front-run momentum also fade overreactions. If a BTC market spikes 15%, bots detect and fade it within minutes.

3. **Speed matters**: The reversion happens quickly (often within hours). By the time you detect a large move and enter a position, much of the reversion may have already occurred.

4. **The edge is thin**: At 1-3% per trade with 55-65% win rate, you need many trades and low fees to be profitable. With Polymarket's fee structure, the margin is tight.

### The alpha isn't fully gone, but it's thin:
- Works best on **lower-volume markets** where bot competition is less intense
- Works best on **novel/unusual events** where price discovery is still happening
- Getting worse over time as more bots enter the space

---

## Why Don't More People Do This?

1. **Low edge per trade**: 1-3% per trade doesn't justify the effort for most traders, especially with capital lock-up of 1-7 days

2. **Hard to distinguish signal from noise**: Not every 10% move is an overreaction. Without a good classifier, your win rate drops to ~50% (break-even before fees)

3. **Requires continuous monitoring**: You need to be watching markets 24/7 to catch moves quickly. The faster you enter, the better your fill price.

4. **Better alternatives exist**: Most sophisticated traders focus on higher-edge strategies (probability arbitrage, combinatorial arb, momentum front-running)

5. **Capital lock-up**: Each position ties up capital for 1-7 days. With $500-2K, you can only run a few trades at a time.

---

## Possible Exposure (Risk)

| Risk | Severity | Mitigation |
|------|----------|------------|
| **News was correct** | HIGH | Use NLP classifier to filter information-driven moves. Only fade sentiment-driven moves. |
| **Whipsaw** | MEDIUM | Use wider stop losses (move continues another 10%+). Accept that some trades will stop out. |
| **Timing risk** | MEDIUM | Enter quickly after detecting move. Use limit orders to get better fills. |
| **Low edge after fees** | MEDIUM | Focus on larger moves (>15%) where the reversion is more pronounced. Avoid marginal signals. |
| **Capital lock-up** | LOW-MEDIUM | Set max hold time of 3-5 days. Exit at time limit regardless. |
| **Correlated moves** | LOW | Multiple markets may move together on macro news. Don't fade the same event in multiple markets. |

### Expected P&L Profile
With $1,000 capital, 5 trades/month:
- Average win: $20 (2% on $1K position)
- Average loss: $30 (3% stop loss)
- Win rate: 58%
- Monthly P&L: ~$30-50 (3-5% monthly)
- Worst month: -$80 to -$120 (if multiple trades stop out)

---

## Additional Considerations

### The NLP Classifier Is the Key Differentiator

Without ML, this strategy is marginal (simple 24h change threshold). With a good NLP classifier, you can significantly improve signal quality:

```
Input: News/social data around the time of the move
Classification:
  - OVERREACTION (sentiment-driven): HIGH CONFIDENCE fade
  - INFORMATION (data-driven): NO TRADE
  - AMBIGUOUS: REDUCE SIZE

Features:
  - Sentiment polarity of news articles
  - Source credibility (AP/Reuters vs. random tweet)
  - Whether data supports the move (poll numbers, official stats)
  - Historical pattern: has this event type caused overreactions before?
```

This classifier is where your NLP skills add genuine value — but it requires significant training data and may still be unreliable for novel event types.

### Backtesting Challenges

This strategy is notoriously hard to backtest accurately:
- **Survivorship bias**: You only see resolved markets, not ones that were delisted
- **Execution assumptions**: You won't get the exact price you see in historical data
- **Regime changes**: The prediction market landscape changes rapidly (new fee structures, new bots, new market types)
- **Sample size**: Large moves (>10%) happen infrequently per market, so you need data across many markets

### Works Better Combined with Other Strategies

Mean reversion is better as a **signal overlay** for Strategy 1 (probability arbitrage) rather than a standalone strategy:
- When your probability model disagrees with the market AND a recent large move occurred, your conviction is higher
- The reversion signal confirms that the market may have deviated from fair value

### References
- [Improving prediction market forecasts by detecting over-reaction (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0377221718305575)
- [Trends and Reversion in Financial Markets on Time Scales from Minutes to Decades (arXiv)](https://arxiv.org/html/2501.16772v1)
- [QuantPedia: "Systematic Edges in Prediction Markets"](https://quantpedia.com/systematic-edges-in-prediction-markets/)
- [Analysis: Polymarket Traders' Biases Can Lead to Irrational Results (CoinDesk)](https://www.coindesk.com/markets/2025/10/30/analysis-prediction-market-bettors-miscalculated-dutch-election-results)

---

## Verdict

**Worth investing time: PROBABLY NOT as standalone**

The edge is thin (1-3% per trade), the strategy is easy to replicate (more competition), and you need continuous monitoring. The NLP classifier adds value but requires significant development effort for a modest improvement.

**Better approach**: Use mean reversion signals as a **feature/overlay** in your probability model (Strategy 1) rather than as a standalone strategy. When your model says "this market is overpriced" AND there was a recent large move, size up.

**Time to first results**: 2-4 weeks (backtesting + signal development)
**Capital efficiency**: Medium (1-7 day hold times)
**Scalability**: Limited by number of qualifying signals per month

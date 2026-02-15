# Strategy 4: Cross-Platform Arbitrage (Polymarket vs Kalshi vs Others)

## Feasibility Score: 4/10

---

## Concept

The same event is priced differently on different prediction market platforms (Polymarket, Kalshi, Robinhood, etc.). Buy YES on one platform and NO on the other. Regardless of the outcome, you receive $1.00 total, having paid less than $1.00.

```
Platform A: YES = $0.42
Platform B: NO = $0.55
Total cost: $0.97
Guaranteed profit: $0.03 (3.09% return)
```

This is the closest thing to "risk-free" arbitrage in prediction markets — but it's not truly risk-free.

---

## What You'd Need to Implement This

### Data Requirements
- **Real-time prices from multiple platforms**: Polymarket + Kalshi at minimum
- **Event matching**: Map equivalent events across platforms (different naming conventions)
- **Resolution criteria comparison**: Detailed comparison of how each platform resolves equivalent events
- **Fee schedules**: Current fee structures for each platform

### Resources & Compute
| Resource | Requirement | Cost Estimate |
|----------|-------------|---------------|
| Polymarket API access | CLOB API + WebSocket | Free (but needs non-US IP) |
| Kalshi API access | REST API + WebSocket, requires account | Free (US-only, requires KYC) |
| Event matching system | NLP-based or manual mapping | Development time |
| Capital on BOTH platforms | Need funded accounts on each | $500-1K per platform minimum |
| Non-US server (Polymarket) | EU-based VPS | $30-80/month |
| US access (Kalshi) | Kalshi is US-only, requires US identity | May be a blocker |

### Technical Skills Required
- Multi-API integration (different auth methods, data formats)
- Event matching (NLP similarity or manual curation)
- Concurrent order execution (both legs must execute near-simultaneously)
- Partial fill handling (critical — one leg fills, other doesn't)

### Platform Access Matrix

| Platform | API Available | Auth Required | Geographic Restriction | Fees |
|----------|-------------|---------------|----------------------|------|
| Polymarket | Yes (py-clob-client) | Yes (wallet + API key) | Blocks US, UK, AU, FR, etc. | 0.01% trade + 2% winner fee |
| Kalshi | Yes (kalshi-python) | Yes (API key + KYC) | US-only (CFTC regulated) | ~0.7% trade fee |
| Robinhood | No public trading API | N/A | US-only | 0% fees |
| PredictIt | Shutting down | N/A | N/A | N/A |

---

## What Would Be Your Edge?

### The Spread Is Real But Shrinking

During the 2024 US presidential election, Polymarket and Kalshi showed persistent 3-5% cross-platform spreads that lasted minutes. This is well-documented:
- Clinton & Huang (2025) documented these spreads academically
- Polymarket led price discovery (higher liquidity), Kalshi lagged by minutes
- Combined trading volumes reached $37 billion in 2025 across platforms

### Where Your ML Skills Add Value

Honestly, **this strategy doesn't heavily leverage ML skills**. The edge is in:
1. Speed of execution (engineering, not ML)
2. Event matching accuracy (some NLP, but mostly manual curation)
3. Settlement risk assessment (reading resolution criteria carefully)

ML could help with:
- Automated event matching using semantic similarity
- Predicting which events are likely to have persistent spreads
- Settlement divergence risk scoring

### Estimated Edge: 1-3% per opportunity (before fees)

### After Fees: Often Near Zero

This is the critical issue. Let's do the math:

```
Gross spread: 3%
Polymarket fee: 0.01% + 1% (half of 2% winner fee) = 1.01%
Kalshi fee: 0.7%
Total fees: 1.71%

Net profit: 3% - 1.71% = 1.29%
```

For a 2% spread: 2% - 1.71% = **0.29%** — barely profitable.

---

## Is the Alpha Already Arbitraged Away?

### Mostly, and getting worse:

1. **Dedicated arb bots exist**: Multiple open-source cross-platform arb bots are available on GitHub (e.g., `polymarket-kalshi-btc-arbitrage-bot`). The bar to entry is low.

2. **eventarb.com exists**: A public website that displays cross-platform arbitrage opportunities in real-time. When opportunities are public, they close quickly.

3. **Institutional players**: Professional market makers run cross-platform strategies with better infrastructure and more capital.

4. **Spreads are narrowing**: As both platforms mature and more bots compete, spreads are getting thinner. The 3-5% spreads from 2024 elections are now more like 1-2%.

5. **Dynamic fees**: Polymarket has introduced dynamic fees on short-term crypto markets, further squeezing margins.

---

## Why Don't More People Do This?

1. **Geographic paradox**: Polymarket blocks US IPs; Kalshi is US-only. To arb between them, you need access to BOTH, which requires either:
   - Being a non-US resident with US Kalshi access (limited)
   - Using a VPN for Polymarket (violates ToS, risk of frozen funds)
   - Complex entity structures

2. **Capital split**: You need funded accounts on both platforms. With $500-2K total capital, splitting it leaves too little on each side for meaningful trades.

3. **Settlement divergence is real**: The 2024 government shutdown case showed platforms can resolve the "same" event differently:
   - Polymarket: "OPM issues shutdown announcement" → YES
   - Kalshi: "Shutdown exceeds 24 hours" → NO
   - Same event, opposite resolutions. If you had arb positions, you'd lose on BOTH sides.

4. **Partial fill risk**: If one leg fills and the other doesn't, you have unhedged directional exposure.

5. **Capital is locked until resolution**: Unlike equities arb where you can close both legs any time, prediction market positions are hard to exit (illiquid, wide spreads).

---

## Possible Exposure (Risk)

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Settlement divergence** | CRITICAL | Only arb markets with identical, objective resolution sources (e.g., "AP calls the race"). Read BOTH sets of resolution criteria carefully. |
| **Platform access issues** | HIGH | Need legitimate access to both platforms. VPN for Polymarket = risk of frozen funds. |
| **Partial fill** | HIGH | Use FOK (Fill or Kill) orders. If one leg fails, immediately cancel the other. Have a partial-fill handler. |
| **Fee erosion** | MEDIUM | Only trade spreads >2.5% after fees. Most opportunities won't meet this threshold. |
| **Capital split** | MEDIUM | Need sufficient capital on each platform. At $1K total, $500/platform is very thin. |
| **Execution latency** | MEDIUM | Both legs must execute near-simultaneously. Network latency between platforms is a risk factor. |
| **Regulatory risk** | HIGH | Kalshi faced a Massachusetts lawsuit (Sept 2025) for operating unlicensed sports betting. Platform regulatory risk is real. |

### Worst-Case Scenario
- Settlement divergence: Lose both legs = -100% on position size
- Partial fill: Stuck with directional exposure on one platform
- Account frozen: If VPN detected on Polymarket, funds can be frozen

---

## Additional Considerations

### The Geographic Blocker Is Severe

This is probably the biggest practical obstacle. You said you can't access Polymarket locally due to IP restrictions, which suggests you're in a restricted country. To do cross-platform arb:

1. **Polymarket**: Needs non-US IP → EU/Singapore VPS ($30-80/month)
2. **Kalshi**: Needs US identity and KYC → May not be available to you

If you can't access Kalshi, this strategy is dead on arrival. If you CAN access both, the geographic barrier is actually your moat — fewer people can do it.

### Your ML Skills Are Underutilized Here

This strategy is primarily an **infrastructure/engineering challenge**, not an ML challenge:
- Speed of execution matters more than model quality
- Event matching is a one-time NLP task, not continuous ML
- The edge is in plumbing, not prediction

### Capital Rotation Can Improve Returns

If you don't hold to maturity but instead exit both positions when the spread closes (before resolution), you can rotate capital more efficiently:
- Hold 3 months for 2% = ~8% annualized
- Rotate weekly at 2% = ~280% annualized (theoretical, not achievable in practice)
- Realistic rotation: Monthly at 1-2% = 12-24% annualized

But this requires sufficient liquidity on both platforms to exit positions — often not available for smaller markets.

### Better Alternatives for Cross-Platform

Instead of true arbitrage (risk-free but thin margins), consider **cross-platform information flow**:
- Polymarket leads price discovery for most events
- Use Polymarket prices as a leading indicator for Kalshi
- This is more of a momentum strategy than arbitrage

### References
- [SSRN (2024 Election): Cross-Platform Price Disparities](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5910522)
- [Kalshi vs Polymarket: Complete Comparison (CryptoNews)](https://cryptonews.com/cryptocurrency/kalshi-vs-polymarket/)
- [Event Contract Arbitrage Calculator](https://www.eventarb.com/)
- [Polymarket vs Kalshi for Arbitrage Traders (ArbBets)](https://getarbitragebets.com/blog/polymarket-vs-kalshi)
- [Polymarket Geographic Restrictions](https://docs.polymarket.com/polymarket-learn/FAQ/geoblocking)

---

## Verdict

**Worth investing time: NO (for your situation)**

The geographic access problem (needing both US and non-US access), capital split requirement, settlement divergence risk, and thin post-fee margins make this strategy impractical at your capital level. This strategy requires $10K+ split across platforms, legitimate access to both, and infrastructure for near-simultaneous execution.

Your ML skills are largely wasted here — the edge is in engineering speed and geographic access, not in modeling.

**Time to first results**: 2-3 weeks (API integration + event matching)
**Capital efficiency**: Very low (capital split across platforms, locked until resolution)
**Scalability**: Limited by available cross-platform opportunities and capital constraints

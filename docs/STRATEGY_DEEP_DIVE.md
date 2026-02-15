# Polymarket Trading Strategies: Complete Deep Dive

## Executive Summary

This document covers 6 distinct strategies for profiting on Polymarket, ranked by viability and complexity. Each strategy includes academic backing, implementation details, expected returns, and risks.

---

## Strategy 1: Probability Arbitrage (Model-Based)

### Concept
Build a model that estimates true probability P_true better than market price P_market. The edge is:

```
Edge = P_true - P_market
```

When your model says 70% but market says 55%, you have 15% edge.

### Academic Foundation
- Wolfers & Zitzewitz (2006): "Prices in prediction markets approximate mean beliefs but can deviate significantly near extremes ($0.00 or $1.00)"
- Kelly Criterion paper (arXiv:2412.14144): Optimal position sizing for binary outcomes

### Kelly Criterion for Prediction Markets

**Formula:**
```
f* = (Q - P) / (1 + Q)

Where:
  P = p / (1-p)     [market odds]
  Q = q / (1-q)     [your estimated odds]
  p = market price
  q = your probability estimate
```

**Example:**
- Market price: $0.60 (60% implied probability)
- Your model: 75% true probability
- P = 0.60/0.40 = 1.5
- Q = 0.75/0.25 = 3.0
- f* = (3.0 - 1.5) / (1 + 3.0) = 0.375 (37.5% of bankroll)

**Practical Adjustment:** Use 25-50% of Kelly (fractional Kelly) to reduce variance.

### Implementation

```python
class ProbabilityModel:
    def estimate(self, market_data, external_data):
        """
        Inputs:
        - Polling data (aggregated like 538)
        - Historical base rates
        - Sentiment scores (news/social)
        - Time to resolution
        - Related market prices (internal consistency)
        
        Output:
        - P_true estimate with confidence interval
        """
        
    def calculate_kelly(self, p_market, p_true):
        P = p_market / (1 - p_market)
        Q = p_true / (1 - p_true)
        kelly = (Q - P) / (1 + Q)
        return max(0, min(kelly * 0.25, 0.1))  # 25% Kelly, max 10% position
```

### Expected Returns
- **Edge required:** 3-10% over market consensus
- **Win rate:** ~55-60% with calibrated model
- **Monthly return:** 5-15% with good model calibration
- **Sharpe ratio:** 1.5-2.5

### Risks
1. **Model miscalibration** — If your model is wrong, Kelly sizing magnifies losses
2. **Overfitting** — Historical patterns may not repeat
3. **Information disadvantage** — Market may have info you don't

### Model Inputs to Consider

| Category | Input | Rationale |
|----------|-------|-----------|
| Market-Specific | Time to Maturity | Events closer to resolution have higher information flow |
| Market-Specific | Volatility (24h changes) | Measures uncertainty/information arrival |
| Market-Specific | Volume/Liquidity | Low volume = less efficient |
| Exogenous | Sentiment Score | Directional bias in news/social |
| Exogenous | Key Data Releases | Scheduled high-impact information |
| Exogenous | Polling Data | For political markets |
| Exogenous | On-chain Data | For crypto markets |

---

## Strategy 2: Longshot Bias Exploitation

### Concept
Retail traders systematically overvalue low-probability outcomes (lottery ticket effect). Fade them by selling tails and buying favorites.

### Academic Foundation
- **50+ years of documented bias** across horse racing, sports betting, and prediction markets
- NBER Working Paper: "Explaining the Favorite-Longshot Bias"
- Empirical study (12,084 matches): Favorites returned -3.64%, underdogs -26.08%

### The Bias Explained

| Outcome Type | Market Behavior | True Probability | Implied Probability |
|--------------|-----------------|------------------|---------------------|
| Longshots (5-15%) | Overbet | ~5% | ~10-15% |
| Mid-range (40-60%) | Roughly accurate | ~50% | ~50% |
| Favorites (85-95%) | Underbet | ~90% | ~85-88% |

### Implementation

```python
class LongshotFader:
    def __init__(self):
        self.threshold_low = 0.15   # Target contracts < 15%
        self.overpricing_min = 1.2  # Must be 20% overpriced
        
    def find_opportunities(self, markets):
        """Find overpriced longshots to fade"""
        opportunities = []
        
        for market in markets:
            yes_price = market.yes_price
            
            # Target low probability markets
            if yes_price > self.threshold_low:
                continue
            
            # Estimate true probability (simplified)
            # Better: use historical calibration data
            p_true = self.estimate_true_prob(market)
            
            # Check if overpriced
            if yes_price / p_true > self.overpricing_min:
                opportunities.append({
                    'market': market,
                    'action': 'BUY_NO',  # Fade the longshot
                    'edge': (yes_price - p_true) / yes_price,
                    'yes_price': yes_price,
                    'p_true': p_true
                })
        
        return sorted(opportunities, key=lambda x: -x['edge'])
```

### Position Sizing for Tail Fading
- **Many small positions** — Diversify across 20-50+ markets
- **Max 2-5% per position** — One black swan shouldn't kill you
- **Exit early** — Don't hold to resolution on subjective markets

### Expected Returns
- **Win rate:** 80-90% (most longshots lose)
- **Average win:** Small (you paid $0.85-0.95 for $1)
- **Average loss:** Large (you lose entire position when tail hits)
- **Monthly return:** 2-5%
- **Sharpe ratio:** 0.8-1.2

### Risks
1. **Fat tails** — The "impossible" does happen (Trump 2016, Leicester City)
2. **Correlated risk** — Multiple longshots can hit together (e.g., election upset)
3. **Liquidity** — Hard to exit tail positions at fair prices

---

## Strategy 3: Short-Term Mean Reversion

### Concept
Prices overreact to news. After large moves (>10% in 24h), partial reversion occurs over 1-7 days.

### Academic Foundation
- QuantPedia: "Prediction markets show negative autocorrelation in daily price changes"
- Behavioral economics: Recency bias causes overreaction
- Momentum does NOT persist in prediction markets (unlike equities)

### Implementation

```python
class MeanReversionStrategy:
    def __init__(self):
        self.move_threshold = 0.10  # 10% move triggers signal
        self.reversion_target = 0.5  # Expect 50% reversion
        self.max_hold_days = 7
        
    def find_signals(self, markets_with_history):
        """Find overreactions to fade"""
        signals = []
        
        for market in markets_with_history:
            price_now = market.current_price
            price_24h = market.price_24h_ago
            
            move = price_now - price_24h
            
            if abs(move) < self.move_threshold:
                continue
            
            # Calculate expected reversion
            expected_reversion = move * self.reversion_target
            target_price = price_now - expected_reversion
            
            signals.append({
                'market': market,
                'action': 'BUY_NO' if move > 0 else 'BUY_YES',
                'entry': price_now,
                'target': target_price,
                'stop_loss': price_now + (move * 0.5),  # Stop if continues
                'move_size': move
            })
        
        return sorted(signals, key=lambda x: -abs(x['move_size']))
    
    def manage_position(self, position, current_price):
        """Check for exit conditions"""
        # Take profit if reverted
        if self.hit_target(position, current_price):
            return 'EXIT_PROFIT'
        
        # Stop loss if continued
        if self.hit_stop(position, current_price):
            return 'EXIT_LOSS'
        
        # Time-based exit
        if position.age_days > self.max_hold_days:
            return 'EXIT_TIME'
        
        return 'HOLD'
```

### Key Observations
- **Works best on news-driven moves** — Earnings, poll releases, etc.
- **Doesn't work on information moves** — If news genuinely changes probability
- **Shorter hold = better** — Reversion happens fast or not at all

### Expected Returns
- **Win rate:** 55-65%
- **Average trade:** 1-3% return
- **Hold time:** 1-7 days
- **Monthly return:** 3-8%
- **Sharpe ratio:** 1.0-1.5

### Risks
1. **News was correct** — Sometimes the move reflects new truth
2. **Whipsaw** — Can trigger both entry and stop in volatile periods
3. **Timing** — Need to detect overreaction quickly before reversion starts

---

## Strategy 4: Cross-Platform Arbitrage (Polymarket vs Kalshi)

### Concept
The same event is priced differently on different platforms. Buy YES on one, NO on the other. Guaranteed $1 payout, paid less than $1.

### Academic Foundation
- SSRN Study (2024 Election): "Significant price disparities exist between Polymarket and Kalshi"
- Polymarket led price discovery (higher liquidity), Kalshi lagged by minutes
- Clinton & Huang (2025): Documented 3-5% cross-platform spreads during election

### The Math

```
Platform A: YES price = $0.42
Platform B: NO price = $0.55
Total cost: $0.97

Regardless of outcome:
- If event happens: Win $1.00 on Platform A, lose $0.55 on Platform B = $0.45
- If event fails: Lose $0.42 on Platform A, win $1.00 on Platform B = $0.58

Net profit = $0.03 guaranteed (3.09% return)
```

### Implementation

```python
class CrossPlatformArbitrage:
    def __init__(self, polymarket_client, kalshi_client):
        self.poly = polymarket_client
        self.kalshi = kalshi_client
        self.min_profit_pct = 0.02  # 2% minimum after fees
        
    async def find_opportunities(self, event_pairs):
        """Scan matched events across platforms"""
        opportunities = []
        
        for poly_event, kalshi_event in event_pairs:
            poly_yes = self.poly.get_price(poly_event, 'YES')
            poly_no = self.poly.get_price(poly_event, 'NO')
            kalshi_yes = self.kalshi.get_price(kalshi_event, 'YES')
            kalshi_no = self.kalshi.get_price(kalshi_event, 'NO')
            
            # Check both directions
            # Poly YES + Kalshi NO
            cost_1 = poly_yes + kalshi_no
            # Kalshi YES + Poly NO
            cost_2 = kalshi_yes + poly_no
            
            profit_1 = 1.0 - cost_1 - self.calculate_fees(cost_1)
            profit_2 = 1.0 - cost_2 - self.calculate_fees(cost_2)
            
            if profit_1 > self.min_profit_pct:
                opportunities.append({
                    'poly_action': 'BUY_YES',
                    'kalshi_action': 'BUY_NO',
                    'poly_price': poly_yes,
                    'kalshi_price': kalshi_no,
                    'profit': profit_1
                })
            
            if profit_2 > self.min_profit_pct:
                opportunities.append({
                    'poly_action': 'BUY_NO',
                    'kalshi_action': 'BUY_YES',
                    'poly_price': poly_no,
                    'kalshi_price': kalshi_yes,
                    'profit': profit_2
                })
        
        return opportunities
    
    def calculate_fees(self, cost):
        """Platform fee estimates"""
        poly_fee = 0.0001  # 0.01% trade fee
        kalshi_fee = 0.007  # ~0.7% fee
        poly_winner_fee = 0.02  # 2% on winnings (only applies to winning side)
        
        # Conservative: assume worst case fees
        return poly_fee + kalshi_fee + (poly_winner_fee * 0.5)
```

### Execution Considerations

```python
class ArbitrageExecutor:
    def execute(self, opportunity):
        """Execute both legs as close to simultaneously as possible"""
        
        # Pre-checks
        poly_balance = self.poly.get_balance()
        kalshi_balance = self.kalshi.get_balance()
        
        position_size = min(
            poly_balance,
            kalshi_balance,
            self.max_position
        )
        
        # Execute both legs
        # CRITICAL: Execute faster platform first if there's latency
        async with asyncio.TaskGroup() as tg:
            poly_task = tg.create_task(
                self.poly.place_order(opportunity.poly_action, position_size)
            )
            kalshi_task = tg.create_task(
                self.kalshi.place_order(opportunity.kalshi_action, position_size)
            )
        
        # Verify both filled
        if not (poly_task.result().filled and kalshi_task.result().filled):
            # PARTIAL FILL RISK - need to handle
            self.handle_partial_fill(poly_task.result(), kalshi_task.result())
```

### ⚠️ Critical Risk: Settlement Divergence

The **biggest risk** isn't execution — it's settlement criteria differences.

**2024 Government Shutdown Example:**
- Polymarket: "OPM issues shutdown announcement" → Resolved YES
- Kalshi: "Shutdown exceeds 24 hours" → Resolved NO
- **Same event, opposite resolutions**

**Protection:**
1. Read BOTH platforms' resolution criteria carefully
2. Only arb markets with identical, objective resolution sources
3. Prefer markets resolved by same data source (AP, official statistics)

### Rotation Strategy (Capital Efficiency)

Don't hold to maturity — rotate capital:

```python
def should_exit_position(self, position, current_opportunities):
    """Exit if better opportunity exists"""
    
    current_spread = self.get_current_spread(position)
    
    # Exit if spread closed (take profit)
    if current_spread < 0.005:  # < 0.5%
        return True
    
    # Exit if better opportunity exists
    best_new = max(current_opportunities, key=lambda x: x.profit)
    if best_new.profit > current_spread * 1.5:  # 50% better
        return True
    
    return False
```

**Why rotation matters:**
- Holding 3 months for 2% = ~8% annualized
- Rotating weekly at 2% = ~280% annualized (theoretical)

### Expected Returns
- **Profit per trade:** 1-5% 
- **Win rate:** ~95% (settlement risk is the 5%)
- **Capital requirement:** Need funds on both platforms
- **Monthly return:** 1-3% (capital constrained)
- **Sharpe ratio:** 3.0+ (near risk-free when settlement matches)

### Platform Fees

| Platform | Trade Fee | Winner Fee | Notes |
|----------|-----------|------------|-------|
| Polymarket | 0.01% | 2% on profits | Crypto (USDC on Polygon) |
| Kalshi | ~0.7% | None | Fiat USD, CFTC regulated |
| Robinhood | 0% | 0% | Limited markets |

**Fee impact on 3% gross arb:**
- Polymarket: 0.01% + 1% (half of 2%) = 1.01%
- Kalshi: 0.7%
- Net: 3% - 1.71% = **1.29%** actual profit

---

## Strategy 5: Combinatorial Arbitrage (Intra-Polymarket)

### Concept
Logically related markets are mispriced against each other. The probability constraints are violated.

### Academic Foundation
- IMDEA Study (2025): "41% of Polymarket conditions showed arbitrage opportunities"
- $40M total profits extracted over Apr 2024 - Apr 2025
- Top 3 wallets: $4.2M combined from 10,200 trades

### Types of Combinatorial Relationships

**1. Subset Relationships:**
```
"Trump wins presidency" ≤ "Republican wins presidency"

If Trump is at 55% but Republican is at 50%, that's impossible.
Arbitrage: Buy "Republican wins" at 50%, sell "Trump wins" at 55%
```

**2. Exhaustive Partitions:**
```
Within multi-outcome market:
"Candidate A wins" + "Candidate B wins" + "Candidate C wins" = 100%

If they sum to 95%, buy all three for guaranteed profit.
```

**3. Temporal Consistency:**
```
"BTC > $100k in Feb 2026" ≤ "BTC > $100k in 2026"

If February price exceeds yearly price, arbitrage exists.
```

### Detection Using LLMs

The IMDEA study used LLMs to detect logical relationships:

```python
class CombinatorialDetector:
    def __init__(self, llm_client):
        self.llm = llm_client
        
    async def find_relationships(self, market_a, market_b):
        """Use LLM to detect logical dependencies"""
        
        prompt = f"""
        Analyze these two prediction markets for logical relationships:
        
        Market A: "{market_a.question}"
        Market B: "{market_b.question}"
        
        Determine if any of these relationships hold:
        1. A implies B (if A true, B must be true)
        2. B implies A (if B true, A must be true)
        3. Mutually exclusive (both cannot be true)
        4. Independent (no logical relationship)
        
        Output JSON: {{"relationship": "...", "confidence": 0.0-1.0}}
        """
        
        response = await self.llm.generate(prompt)
        return json.loads(response)
    
    def check_arbitrage(self, market_a, market_b, relationship):
        """Check if prices violate the relationship"""
        
        p_a = market_a.yes_price
        p_b = market_b.yes_price
        
        if relationship == "A_implies_B":
            # P(A) must be ≤ P(B)
            if p_a > p_b:
                return {
                    'type': 'implication_violation',
                    'profit': p_a - p_b,
                    'action': f'Sell {market_a.id}, Buy {market_b.id}'
                }
        
        elif relationship == "mutually_exclusive":
            # P(A) + P(B) must be ≤ 1
            if p_a + p_b > 1.0:
                return {
                    'type': 'exclusion_violation',
                    'profit': p_a + p_b - 1.0,
                    'action': f'Sell both {market_a.id} and {market_b.id}'
                }
        
        return None
```

### Vector Similarity for Market Grouping

Use embeddings to find semantically similar markets:

```python
from sentence_transformers import SentenceTransformer
import chromadb

class MarketGrouper:
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.chroma = chromadb.Client()
        self.collection = self.chroma.create_collection("markets")
        
    def embed_markets(self, markets):
        """Create embeddings for all markets"""
        for market in markets:
            embedding = self.model.encode(market.question)
            self.collection.add(
                embeddings=[embedding.tolist()],
                ids=[market.id],
                metadatas=[{'question': market.question}]
            )
    
    def find_similar(self, market, threshold=0.8):
        """Find markets similar to this one"""
        embedding = self.model.encode(market.question)
        
        results = self.collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=10
        )
        
        similar = []
        for i, score in enumerate(results['distances'][0]):
            if score < (1 - threshold):  # ChromaDB uses distance
                similar.append(results['ids'][0][i])
        
        return similar
```

### Expected Returns
- **Opportunities found:** 41% of conditions (per IMDEA)
- **Profit per opportunity:** 1-10%
- **Complexity:** High (requires semantic understanding)
- **Monthly return:** 1-5%
- **Sharpe ratio:** 2.0+

### Risks
1. **False relationships** — LLM may misinterpret market intent
2. **Resolution ambiguity** — Markets may resolve differently than logic suggests
3. **Execution latency** — Multi-leg trades have slippage risk

---

## Strategy 6: News/Momentum Front-Running

### Concept
Detect news/information before the market prices it in. Enter position, wait for market to react.

### Academic Foundation
- Yahoo Finance (2026): "Bots exploit tiny windows where Polymarket prices lag confirmed spot momentum"
- QuantVPS: "By entering when actual probability is ~85% but market shows 50/50, bot repeatedly buys mispriced certainty"

### How Momentum Bots Work (BTC Markets)

```python
class MomentumFrontRunner:
    """
    For markets like "Will BTC be up in next 15 minutes?"
    Price on Binance/Coinbase moves BEFORE Polymarket updates.
    """
    
    def __init__(self):
        self.exchange_ws = BinanceWebsocket()
        self.polymarket = PolymarketClient()
        
    async def monitor(self, btc_15m_market):
        """Monitor for price momentum"""
        
        while True:
            # Get real-time BTC price from exchange
            btc_price = await self.exchange_ws.get_price('BTCUSDT')
            btc_open = await self.get_period_open()
            
            # Calculate actual momentum
            pct_change = (btc_price - btc_open) / btc_open
            
            # If BTC clearly moving one direction
            if abs(pct_change) > 0.002:  # > 0.2% move
                direction = 'UP' if pct_change > 0 else 'DOWN'
                
                # Check Polymarket prices
                poly_up = self.polymarket.get_price(btc_15m_market, 'UP')
                poly_down = self.polymarket.get_price(btc_15m_market, 'DOWN')
                
                # If Polymarket hasn't priced in the move
                if direction == 'UP' and poly_up < 0.65:
                    # Market is behind - buy UP
                    return {'action': 'BUY_UP', 'confidence': min(0.9, 0.5 + abs(pct_change)*10)}
                
                elif direction == 'DOWN' and poly_down < 0.65:
                    return {'action': 'BUY_DOWN', 'confidence': min(0.9, 0.5 + abs(pct_change)*10)}
            
            await asyncio.sleep(0.1)  # 100ms polling
```

### Requirements for This Strategy
1. **Low latency** — Need <100ms to exchange data
2. **API speed** — Polymarket order execution speed
3. **Capital** — High turnover, many small trades
4. **Automation** — Can't do manually

### Expected Returns (Per QuantVPS)
- One documented case: $200 → $764 in single day
- **Highly variable** — depends on market conditions
- Works best on high-frequency markets (15-min, hourly)

### Risks
1. **Competition** — Other bots doing the same thing
2. **Market adapts** — Spreads widen as bots compete
3. **Black swan** — Flash crash/spike in wrong direction

---

## Strategy Comparison

| Strategy | Expected Monthly Return | Win Rate | Complexity | Capital Required | Sharpe |
|----------|------------------------|----------|------------|------------------|--------|
| Probability Arb | 5-15% | 55-60% | High | Medium | 1.5-2.5 |
| Longshot Fade | 2-5% | 80-90% | Low | Medium | 0.8-1.2 |
| Mean Reversion | 3-8% | 55-65% | Medium | Low | 1.0-1.5 |
| Cross-Platform | 1-3% | 95% | Medium | High (2 platforms) | 3.0+ |
| Combinatorial | 1-5% | 75-85% | Very High | Medium | 2.0+ |
| Momentum/News | Variable | 60-80% | Very High | Low | Variable |

---

## Recommended Approach

### Phase 1: Start Simple (Month 1)
1. **Longshot Fade** — Easy to implement, low complexity
2. **Same-market rebalancing** — Check for YES + NO < $1 within markets
3. Paper trade everything first

### Phase 2: Add Complexity (Month 2-3)
1. **Mean Reversion** — Add 24h change monitoring
2. **Probability Model** — Start building forecasting model
3. Live trade with small capital ($500-1000)

### Phase 3: Scale & Automate (Month 3+)
1. **Cross-Platform** — If you can access Kalshi
2. **Combinatorial** — Add LLM-based relationship detection
3. Increase capital based on proven edge

---

## Implementation Priority for Your Bot

Given your setup (AWS instance, can access Polymarket):

1. **Priority 1:** Same-market rebalancing (YES + NO < $1)
2. **Priority 2:** Longshot bias fading (NO on markets < 15%)
3. **Priority 3:** Mean reversion (fade 24h moves > 10%)
4. **Priority 4:** Combinatorial (within same event, no LLM needed)
5. **Priority 5:** Probability model (requires domain expertise)
6. **Future:** Cross-platform (requires Kalshi access)

---

*Research compiled: 2026-02-15*
*Sources: IMDEA, QuantPedia, NBER, arXiv, QuantVPS, academic papers*

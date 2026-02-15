# Strategy 1: Probability Arbitrage — Complete Implementation Guide

## Overview

Build an ML model that estimates P_true better than the market price P_market. When your model disagrees by a sufficient margin, bet accordingly, sized by Kelly criterion with Venn-ABERS calibration uncertainty.

---

## Technical Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Model** | XGBoost (Phase 1), LightGBM + LSTM ensemble (Phase 2) | XGBoost dominates tabular data. LSTM adds temporal patterns later. |
| **Calibration** | Venn-ABERS | Only method providing confidence intervals for Kelly sizing |
| **Embeddings** | nomic-embed-text-v1.5 | Free, local, CPU-friendly, 768-dim with Matryoshka support |
| **Vector search** | ChromaDB | Metadata filtering + persistence + adequate speed |
| **Features** | Market-intrinsic + cross-market + NLP sentiment | Multi-source fusion is your edge |
| **Database** | SQLite (via SQLAlchemy) | Already in requirements.txt, sufficient for this scale |
| **Execution** | py-clob-client | Official Polymarket Python client |

---

## Component P1: Feature Engineering Pipeline

### AI Level: GUIDED
### Effort: 6-8 hours

Your model's quality depends entirely on your features. Here's the complete feature set, organized by implementation priority.

### Tier 1 Features (Market-Intrinsic, Available Immediately)

These come directly from the Gamma API and your price snapshot database. No external data needed.

```python
@dataclass
class MarketFeatures:
    # Price features
    current_price: float          # Gamma API outcomePrices
    price_24h_ago: float          # Your SQLite snapshots
    price_7d_ago: float           # Your SQLite snapshots
    price_change_24h: float       # Derived: current - 24h
    price_change_7d: float        # Derived: current - 7d
    price_volatility_7d: float    # Std dev of daily snapshots

    # Volume features
    volume_24h: float             # Gamma API volume24hr
    volume_7d: float              # Gamma API volume1wk
    volume_ratio: float           # Derived: 24h / 7d (spike detection)

    # Market structure
    spread: float                 # CLOB API get_spread()
    liquidity: float              # Gamma API liquidityNum
    open_interest: float          # Gamma API openInterest
    num_conditions: int           # Number of outcomes in event

    # Time features
    days_to_resolution: float     # endDate - now
    pct_time_elapsed: float       # (now - startDate) / (endDate - startDate)

    # Category (one-hot encoded)
    category: str                 # Gamma API category
```

**AI builds**: Data fetcher, feature computation, storage. **You review**: Which features to actually include in the model.

### Tier 2 Features (Cross-Market, From Embedding Pipeline)

These require the shared embedding pipeline (Component S5).

```python
@dataclass
class CrossMarketFeatures:
    # Related market prices
    similar_market_avg_price: float      # Avg price of top-5 similar markets
    similar_market_price_std: float      # Price disagreement among similar markets
    price_vs_similar_diff: float         # This market's price - similar avg

    # Event consistency
    event_sum_probability: float         # Sum of all condition prices in event
    event_deviation: float               # How far sum is from 1.0

    # Category base rate
    category_avg_resolution_rate: float  # Historical: what % of markets in this
                                         # category at this price actually resolve YES?
```

**Why these matter**: If 5 similar markets price an event at 65% but this market prices it at 55%, there's either a mispricing or this market has unique information. The divergence is a signal.

### Tier 3 Features (External, Phase 2+)

```python
@dataclass
class ExternalFeatures:
    # Sentiment (from nomic-embed-text encoding of news)
    news_sentiment_score: float     # [-1, 1] aggregated sentiment
    social_volume_zscore: float     # Z-score of social mentions vs. baseline

    # Domain-specific
    polling_aggregate: float        # For political markets (538/RCP)
    exchange_price: float           # For crypto markets (Binance)
    exchange_momentum: float        # For crypto markets (24h change)
```

---

## Component P2: Base Probability Model

### AI Level: GUIDED
### Effort: 4-6 hours

### XGBoost Configuration

```python
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit

model = xgb.XGBClassifier(
    n_estimators=200,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_alpha=0.1,
    reg_lambda=1.0,
    objective='binary:logistic',
    eval_metric='logloss',
    early_stopping_rounds=20,
    random_state=42
)

# CRITICAL: Use TimeSeriesSplit, NOT random split
tscv = TimeSeriesSplit(n_splits=5)
for train_idx, val_idx in tscv.split(X):
    X_train, X_val = X[train_idx], X[val_idx]
    y_train, y_val = y[train_idx], y[val_idx]
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)])
```

### Training Data

**Source**: Your database of resolved markets with price snapshots.

**Label**: Binary outcome (1 = YES resolved, 0 = NO resolved).

**Critical**: Each training sample is a (market, timestamp) pair. For a market that resolved YES, you create multiple samples at different timestamps with different prices — the model learns "given these features at time T, what's the probability of YES resolution?"

```python
# Training data construction
samples = []
for market in resolved_markets:
    for snapshot in market.price_snapshots:
        features = compute_features(market, snapshot.timestamp)
        label = 1 if market.resolved_yes else 0
        samples.append((features, label))
```

**Minimum data**: ~500 resolved markets with at least weekly snapshots = ~2,000-5,000 training samples. This is achievable after 2-3 months of data collection.

**Cold start problem**: You don't have historical data yet. Solutions:
1. Start collecting immediately (Priority 1 from roadmap)
2. Use 12h candles from resolved markets as rough historical data
3. Paper trade for 4-8 weeks while collecting data
4. Scrape community data sources (PolymarketAnalytics, Dune)

---

## Component P5: Venn-ABERS Calibration

### AI Level: AI
### Effort: 3-4 hours

```python
from venn_abers import VennAbersCalibrator
import numpy as np

class CalibratedPredictor:
    def __init__(self, model, kelly_fraction=0.25, max_position_pct=0.10):
        self.model = model
        self.calibrator = VennAbersCalibrator()
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.is_calibrated = False

    def fit_calibration(self, X_cal, y_cal):
        """Fit calibration on held-out resolved markets."""
        raw_scores = self.model.predict_proba(X_cal)[:, 1]
        self.calibrator.fit(raw_scores, y_cal)
        self.is_calibrated = True

    def predict(self, features):
        """Return calibrated probability + uncertainty."""
        raw_score = self.model.predict_proba(features.reshape(1, -1))[:, 1]
        p0, p1 = self.calibrator.predict_proba(raw_score)

        calibrated = p0[0] / (p0[0] + (1 - p1[0]))
        uncertainty = p1[0] - p0[0]

        return calibrated, uncertainty

    def should_trade(self, market_price, features, min_edge=0.03):
        """Determine if a trade signal exists."""
        p_true, uncertainty = self.predict(features)

        edge = abs(p_true - market_price)

        # No trade if edge too small or uncertainty too high
        if edge < min_edge:
            return None
        if uncertainty > 0.3:  # Very uncertain calibration
            return None

        direction = 'BUY_YES' if p_true > market_price else 'BUY_NO'

        # Kelly sizing with uncertainty adjustment
        position_size = self._kelly_size(p_true, market_price, uncertainty)

        return {
            'direction': direction,
            'p_true': p_true,
            'p_market': market_price,
            'edge': edge,
            'uncertainty': uncertainty,
            'position_size': position_size,
            'confidence': 'HIGH' if uncertainty < 0.1 else 'MEDIUM'
        }

    def _kelly_size(self, p_true, p_market, uncertainty, bankroll=1.0):
        """Kelly criterion adjusted for calibration uncertainty."""
        if p_true > p_market:
            # Buying YES
            edge = p_true - p_market
            odds = (1 - p_market) / p_market
        else:
            # Buying NO
            edge = p_market - p_true
            odds = p_market / (1 - p_market)

        kelly = edge * odds - (1 - edge)
        kelly = max(0, kelly / odds)

        # Adjust for calibration uncertainty
        confidence_mult = max(0.1, 1.0 - uncertainty * 2)
        adjusted = kelly * self.kelly_fraction * confidence_mult

        return min(adjusted * bankroll, self.max_position_pct * bankroll)
```

---

## Component P7: Walk-Forward Backtesting

### AI Level: GUIDED
### Effort: 6-8 hours

```python
class WalkForwardBacktester:
    def __init__(self, model_class, calibrator_class,
                 train_months=3, test_months=1):
        self.model_class = model_class
        self.calibrator_class = calibrator_class
        self.train_months = train_months
        self.test_months = test_months

    def run(self, data, markets):
        """Walk-forward validation with realistic P&L simulation."""
        results = []

        for period in self.generate_periods(data):
            # Train on historical data
            model = self.model_class()
            model.fit(period.train_X, period.train_y)

            # Calibrate on most recent training data
            cal = self.calibrator_class()
            cal.fit(period.cal_X, period.cal_y)

            # Generate signals on test period
            for market in period.test_markets:
                features = self.compute_features(market)
                signal = self.generate_signal(model, cal, market, features)

                if signal:
                    result = self.simulate_trade(signal, market)
                    results.append(result)

        return self.compute_metrics(results)

    def compute_metrics(self, results):
        """Calculate performance metrics."""
        return {
            'total_trades': len(results),
            'win_rate': sum(1 for r in results if r['pnl'] > 0) / len(results),
            'total_pnl': sum(r['pnl'] for r in results),
            'avg_pnl_per_trade': np.mean([r['pnl'] for r in results]),
            'sharpe': self.calculate_sharpe(results),
            'max_drawdown': self.calculate_drawdown(results),
            'brier_score_model': self.brier_score(results, 'p_true'),
            'brier_score_market': self.brier_score(results, 'p_market'),
            'calibration_plot': self.reliability_diagram(results),
        }
```

### Key Metrics to Track

| Metric | Target | Meaning |
|--------|--------|---------|
| **Brier score (your model)** | < Brier score (market) | Your model must beat the market's implied probabilities |
| **Win rate** | > 52% | Slight edge, compounded via Kelly |
| **Average edge per trade** | > 3% | Minimum to overcome fees and variance |
| **Sharpe ratio** | > 1.0 | Risk-adjusted return |
| **Max drawdown** | < 25% | Capital preservation |
| **Calibration** | Slope ~1.0 on reliability diagram | When you say 70%, it should happen ~70% of the time |

---

## Category Specialization (P9)

### AI Level: HUMAN
### Effort: 8-12 hours

This is where your domain expertise matters most. Each market category has different dynamics:

### Crypto Markets
- **Edge source**: Exchange price data as ground truth
- **Features**: BTC/ETH/SOL price, funding rates, exchange volume, on-chain metrics
- **Advantages**: Data is freely available, real-time, and quantitative
- **Risk**: Very short-duration markets (15min, 1hr) are dominated by latency bots
- **Focus on**: Medium-duration markets (will BTC exceed $X by end of month?)

### Political Markets
- **Edge source**: Polling aggregation, historical base rates
- **Features**: Polling averages, endorsements, campaign finance, demographic data
- **Advantages**: Highest volume markets, most data
- **Risk**: Most efficient markets (highest attention), insider information
- **Focus on**: State-level and down-ballot races (less attention = more mispricing)

### Sports Markets
- **Edge source**: Elo ratings, injury data, historical matchup data
- **Features**: Team stats, player availability, venue, weather
- **Advantages**: Most frequent resolution (daily/weekly)
- **Risk**: Competing with sports betting professionals
- **Focus on**: Markets where Polymarket pricing diverges from Vegas lines

### Niche/Novel Markets
- **Edge source**: Historical base rates for similar events
- **Features**: Limited — category base rate, volume, attention
- **Advantages**: Least efficient (lowest attention), most mispricing
- **Risk**: Low volume, hard to exit, limited training data
- **Focus on**: Markets with clear resolution criteria and sufficient liquidity

**Recommendation**: Start with **crypto markets** (quantitative data, familiar territory for prediction market users) and **niche markets** (least competition). Add political markets later when you have more data.

---

## Model Monitoring (P8, P11)

### Continuous Tracking

```python
class ModelMonitor:
    def __init__(self):
        self.predictions = []  # (market_id, timestamp, p_true, p_market, outcome)

    def record_prediction(self, market_id, p_true, p_market):
        self.predictions.append({
            'market_id': market_id,
            'timestamp': datetime.now(),
            'p_true': p_true,
            'p_market': p_market,
            'outcome': None  # Filled when market resolves
        })

    def update_outcome(self, market_id, resolved_yes):
        for p in self.predictions:
            if p['market_id'] == market_id:
                p['outcome'] = 1 if resolved_yes else 0

    def check_degradation(self, window=50):
        """Alert if model is degrading."""
        recent = [p for p in self.predictions[-window:] if p['outcome'] is not None]

        if len(recent) < 20:
            return None

        model_brier = np.mean([(p['p_true'] - p['outcome'])**2 for p in recent])
        market_brier = np.mean([(p['p_market'] - p['outcome'])**2 for p in recent])

        if model_brier > market_brier:
            return {
                'alert': 'MODEL_DEGRADATION',
                'model_brier': model_brier,
                'market_brier': market_brier,
                'action': 'REDUCE_POSITION_SIZES or RETRAIN'
            }

        return None
```

### Retraining Schedule

- **Weekly**: Add newly resolved markets to training data
- **Monthly**: Full retrain with all data, re-evaluate feature importance
- **On degradation alert**: Immediate retrain + paper trade for 1 week before resuming live

---

## Risk Management

### Position Limits

```python
RISK_LIMITS = {
    'max_position_pct': 0.10,        # Max 10% of bankroll per position
    'max_category_pct': 0.30,        # Max 30% in any single category
    'max_correlated_pct': 0.20,      # Max 20% in correlated markets
    'max_total_exposure': 0.80,      # Keep 20% as reserve
    'min_edge': 0.03,                # Minimum 3% edge to trade
    'min_liquidity': 1000,           # Minimum $1K market liquidity
    'min_days_to_resolution': 2,     # Don't trade markets resolving in <2 days
    'max_uncertainty': 0.30,         # Don't trade if Venn-ABERS uncertainty > 0.3
}
```

### Correlation Management

Markets are correlated (e.g., all political markets during an election). Use the embedding pipeline to detect correlation clusters and limit exposure per cluster.

---

*This document details the complete implementation for Strategy 1. See COMBINED_STRATEGY_ROADMAP.md for how it integrates with Strategy 5 and the shared infrastructure.*

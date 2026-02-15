# Strategy 5: Combinatorial Arbitrage — Complete Implementation Guide

## Overview

Detect logically inconsistent pricing between related Polymarket markets and exploit the violations. Two phases: rule-based detection (no ML needed, generates most profit) and LLM-enhanced detection (adds marginal opportunities).

---

## Critical Context from IMDEA Research

Before diving into implementation, the numbers:

| Metric | Value | Implication |
|--------|-------|-------------|
| Single-market rebalancing profit | $10.58M | Simple YES+NO<$1 detection dominates |
| Combinatorial arbitrage profit | $95K | Only 0.24% of total arb profits |
| LLM false positive rate | 97.3% | Need aggressive filtering pipeline |
| LLM single-market accuracy | 81.45% | Decent but not production-ready without validation |
| Execution failure rate (correct IDs) | 62% | Even real opportunities often fail to execute |
| Conditions with any arbitrage | 41% | There ARE opportunities — detection is the bottleneck |

**Interpretation**: Combinatorial arb is REAL but mostly rule-detectable. LLM-based detection adds marginal value with significant false positive risk. Lead with rules, layer in LLM cautiously.

---

## Technical Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Rule engine** | Python + regex + date parsing | No ML needed for highest-value detections |
| **Embeddings** | nomic-embed-text-v1.5 (CPU) | Similarity grouping for candidate pairs |
| **Vector search** | ChromaDB | Metadata filtering + persistence |
| **LLM (screening)** | DeepSeek API ($0.14/1K calls) | Cheapest option for bulk classification |
| **LLM (verification)** | GPT-4o ($4/1K calls) | High accuracy for pre-trade verification |
| **Fine-tuned model** | GPT-4o-mini or Llama 3.1 8B LoRA | Production inference after training data collected |
| **Database** | SQLite | Price snapshots + detected relationships + trade history |

---

## Phase A: Rule-Based Detection (No LLM Required)

### Component C1: Exhaustive Partition Detector

#### AI Level: AI
#### Effort: 3-4 hours

**What**: For multi-outcome negRisk events, check if condition YES prices sum to more than $1.00.

**Why it works**: In a negRisk event (e.g., "Who will win the election?"), exactly one condition resolves YES. If you sell YES on ALL conditions for a combined $1.05, you pay out exactly $1.00 on the winner = $0.05 gross profit.

```python
import json
from dataclasses import dataclass

@dataclass
class PartitionOpportunity:
    event_id: str
    event_title: str
    conditions: list  # [{id, question, yes_price, token_id}]
    total_yes_sum: float
    gross_profit: float
    net_profit_after_fees: float

class PartitionDetector:
    def __init__(self, min_profit_pct=0.02, fee_rate=0.0201):
        self.min_profit_pct = min_profit_pct
        self.fee_rate = fee_rate  # 0.01% trade + 2% winner fee (worst case)

    def scan_events(self, events):
        """Scan all negRisk events for partition violations."""
        opportunities = []

        for event in events:
            if not event.get('negRisk'):
                continue

            markets = event.get('markets', [])
            if len(markets) < 2:
                continue

            conditions = []
            for market in markets:
                prices = json.loads(market.get('outcomePrices', '[]'))
                clob_ids = json.loads(market.get('clobTokenIds', '[]'))

                if not prices or not clob_ids:
                    continue

                yes_price = float(prices[0])
                conditions.append({
                    'id': market['id'],
                    'question': market['question'],
                    'yes_price': yes_price,
                    'token_id': clob_ids[0],  # YES token
                    'no_token_id': clob_ids[1] if len(clob_ids) > 1 else None,
                    'liquidity': market.get('liquidityNum', 0),
                })

            total = sum(c['yes_price'] for c in conditions)

            if total <= 1.0:
                continue

            gross_profit = total - 1.0
            # Fee: you sell YES on all. Winner pays 2% on profit.
            # Worst case fee estimate:
            net_profit = gross_profit - (self.fee_rate * 1.0)

            if net_profit / total < self.min_profit_pct:
                continue

            # Check liquidity — all legs need sufficient depth
            min_liquidity = min(c['liquidity'] for c in conditions)
            if min_liquidity < 500:
                continue

            opportunities.append(PartitionOpportunity(
                event_id=event['id'],
                event_title=event.get('title', ''),
                conditions=conditions,
                total_yes_sum=total,
                gross_profit=gross_profit,
                net_profit_after_fees=net_profit,
            ))

        return sorted(opportunities, key=lambda x: -x.net_profit_after_fees)
```

### Component C2: NegRisk Rebalancing Detector

#### AI Level: AI
#### Effort: 2-3 hours

**What**: Within a single binary market (YES/NO), check if YES + NO < $1.00. Already stubbed in `src/scanner/arbitrage.py`.

**Enhancement**: Also check within negRisk events — the NO token for condition A is economically equivalent to "any condition except A resolves YES."

```python
class RebalancingDetector:
    def __init__(self, min_spread_pct=0.005):
        self.min_spread_pct = min_spread_pct

    def scan_markets(self, markets):
        """Check YES + NO < $1 for all binary markets."""
        opportunities = []

        for market in markets:
            prices = json.loads(market.get('outcomePrices', '[]'))
            if len(prices) != 2:
                continue

            yes_price = float(prices[0])
            no_price = float(prices[1])
            total = yes_price + no_price

            if total >= 1.0:
                continue

            spread = 1.0 - total
            if spread < self.min_spread_pct:
                continue

            liquidity = market.get('liquidityNum', 0)
            if liquidity < 500:
                continue

            opportunities.append({
                'market_id': market['id'],
                'question': market['question'],
                'yes_price': yes_price,
                'no_price': no_price,
                'spread': spread,
                'spread_pct': spread * 100,
                'liquidity': liquidity,
                'action': 'BUY YES + BUY NO',
            })

        return sorted(opportunities, key=lambda x: -x['spread'])
```

### Component C3: Temporal Consistency Detector

#### AI Level: GUIDED
#### Effort: 4-5 hours

**What**: Markets with temporal relationships must be consistent. "X by February" must be <= "X by December".

```python
import re
from datetime import datetime

class TemporalDetector:
    # Month ordering for comparison
    MONTHS = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'may': 5, 'june': 6, 'july': 7, 'august': 8,
        'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
        'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }

    # Patterns to extract temporal scope
    TEMPORAL_PATTERNS = [
        # "by [month] [year]" or "in [month] [year]"
        r'(?:by|in|before)\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|oct|nov|dec)\s+(\d{4})',
        # "by end of [year]"
        r'(?:by\s+)?end\s+of\s+(\d{4})',
        # "in [year]"
        r'in\s+(\d{4})',
        # "Q1/Q2/Q3/Q4 [year]"
        r'(Q[1-4])\s+(\d{4})',
    ]

    def find_temporal_pairs(self, markets):
        """Find markets about the same topic with different time horizons."""
        # Group by topic using embedding similarity (from ChromaDB)
        # Then check temporal consistency within each group

        pairs = []
        # ... group by similarity, extract dates, compare ...
        return pairs

    def check_consistency(self, market_short, market_long):
        """
        If market_short covers a subset of market_long's timeframe,
        then P(short) <= P(long) must hold.

        E.g., "BTC > 100k in Feb 2026" <= "BTC > 100k in 2026"
        """
        p_short = market_short['yes_price']
        p_long = market_long['yes_price']

        if p_short > p_long:
            return {
                'type': 'temporal_violation',
                'short_market': market_short,
                'long_market': market_long,
                'short_price': p_short,
                'long_price': p_long,
                'profit': p_short - p_long,
                'action': f'SELL YES on short ({market_short["question"]}), '
                         f'BUY YES on long ({market_long["question"]})',
            }
        return None
```

**Why GUIDED**: The date extraction regex needs your review. Market questions use inconsistent phrasing, and false temporal matches lead to bad trades.

### Component C4: Subset Relationship Detector (Rule-Based)

#### AI Level: GUIDED
#### Effort: 3-4 hours

**What**: Known structural subsets that don't need LLM detection.

```python
KNOWN_SUBSETS = {
    # Candidate → Party (political)
    'political_party': {
        'patterns': [
            # (specific_pattern, general_pattern)
            (r'trump\s+win', r'republican\s+win'),
            (r'harris\s+win', r'democrat\s+win'),
            (r'biden\s+win', r'democrat\s+win'),
            # Add more as discovered
        ],
    },
    # Threshold subsets (crypto)
    'threshold': {
        # "BTC > $150k" implies "BTC > $100k"
        # Detect by parsing threshold values
    },
    # Geographic subsets
    'geographic': {
        # "X in California" implies "X in the US"
    },
}

class SubsetDetector:
    def __init__(self, known_patterns=KNOWN_SUBSETS):
        self.patterns = known_patterns

    def check_pair(self, market_a, market_b):
        """Check if market_a is a subset of market_b using known patterns."""
        q_a = market_a['question'].lower()
        q_b = market_b['question'].lower()

        for category, config in self.patterns.items():
            for specific, general in config['patterns']:
                if re.search(specific, q_a) and re.search(general, q_b):
                    # A implies B: P(A) must be <= P(B)
                    p_a = market_a['yes_price']
                    p_b = market_b['yes_price']

                    if p_a > p_b:
                        return {
                            'type': 'subset_violation',
                            'category': category,
                            'specific': market_a,
                            'general': market_b,
                            'profit': p_a - p_b,
                            'action': f'SELL YES on specific, BUY YES on general',
                        }
        return None
```

**Why GUIDED**: The pattern library needs your curation. False patterns cause real losses.

---

## Phase B: LLM-Enhanced Detection

### Component C5: Semantic Similarity Grouping

#### AI Level: AI
#### Effort: 3-4 hours

**What**: Use embeddings to find candidate pairs for LLM analysis. This REDUCES the number of LLM calls needed (only analyze similar markets, not all N^2 pairs).

```python
from sentence_transformers import SentenceTransformer
import chromadb

class MarketGrouper:
    def __init__(self, similarity_threshold=0.75):
        self.model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5',
                                          trust_remote_code=True)
        self.chroma = chromadb.PersistentClient(path="./chroma_data")
        self.collection = self.chroma.get_or_create_collection(
            name="polymarket_markets",
            metadata={"hnsw:space": "cosine"}
        )
        self.threshold = similarity_threshold

    def embed_all_markets(self, markets):
        """Embed and store all active markets."""
        questions = [m['question'] for m in markets]
        # nomic-embed requires task prefix
        prefixed = [f"search_document: {q}" for q in questions]
        embeddings = self.model.encode(prefixed, show_progress_bar=True)

        self.collection.upsert(
            ids=[m['id'] for m in markets],
            embeddings=[e.tolist() for e in embeddings],
            documents=questions,
            metadatas=[{
                'category': m.get('category', ''),
                'yes_price': float(json.loads(m.get('outcomePrices', '["0"]'))[0]),
                'end_date': m.get('endDateISO', ''),
                'volume': m.get('volumeNum', 0),
                'event_id': m.get('negRiskMarketID', ''),
            } for m in markets]
        )

    def find_candidate_pairs(self, market):
        """Find markets similar enough to warrant LLM analysis."""
        query = f"search_query: {market['question']}"
        embedding = self.model.encode([query])

        results = self.collection.query(
            query_embeddings=[embedding[0].tolist()],
            n_results=20,
            where={
                "$and": [
                    {"category": market.get('category', '')},
                    # Don't compare market to itself
                ]
            }
        )

        candidates = []
        for i, distance in enumerate(results['distances'][0]):
            similarity = 1 - distance  # ChromaDB returns distance
            if similarity >= self.threshold:
                candidates.append({
                    'id': results['ids'][0][i],
                    'question': results['documents'][0][i],
                    'similarity': similarity,
                    'metadata': results['metadatas'][0][i],
                })

        return candidates
```

**Key optimization**: The IMDEA team filtered to same-topic + same-end-date markets before LLM analysis. This reduced their pair count from millions to ~46K. Your embedding similarity + metadata filtering does the same thing.

### Component C6: LLM State Space Enumeration

#### AI Level: GUIDED
#### Effort: 6-8 hours

**What**: The IMDEA methodology — ask LLM to enumerate valid joint resolution vectors.

```python
import json
from openai import OpenAI  # or anthropic, or deepseek

class LLMRelationshipClassifier:
    def __init__(self, api_key, model="deepseek-reasoner"):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"  # DeepSeek is cheapest
        )
        self.model = model

    def classify_relationship(self, market_a_conditions, market_b_conditions):
        """
        IMDEA methodology: enumerate valid joint resolution vectors.

        Args:
            market_a_conditions: list of condition strings for market A
            market_b_conditions: list of condition strings for market B

        Returns:
            dict with relationship type, valid vectors, and confidence
        """
        # Number conditions
        all_conditions = []
        for i, c in enumerate(market_a_conditions):
            all_conditions.append(f"({i}) {c}")
        offset = len(market_a_conditions)
        for i, c in enumerate(market_b_conditions):
            all_conditions.append(f"({offset + i}) {c}")

        conditions_text = "\n".join(all_conditions)
        n_a = len(market_a_conditions)
        n_b = len(market_b_conditions)

        prompt = f"""You are analyzing prediction market conditions for logical dependencies.

Given these conditions from two prediction markets:

Market A conditions (exactly one must be TRUE):
{chr(10).join(all_conditions[:n_a])}

Market B conditions (exactly one must be TRUE):
{chr(10).join(all_conditions[n_a:])}

List ALL logically valid combinations where exactly one condition from Market A is TRUE and exactly one from Market B is TRUE.

Output ONLY a JSON array of boolean arrays. Each inner array has {n_a + n_b} elements.

Rules:
- Exactly one TRUE in positions 0-{n_a-1} (Market A)
- Exactly one TRUE in positions {n_a}-{n_a+n_b-1} (Market B)
- Only include combinations that are logically possible in the real world
- If all combinations are possible, output all {n_a * n_b} vectors

Output JSON only, no explanation."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=2000,
        )

        return self._parse_and_validate(
            response.choices[0].message.content, n_a, n_b
        )

    def _parse_and_validate(self, response_text, n_a, n_b):
        """Multi-layer validation of LLM output."""
        # Step 1: Parse JSON
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if not json_match:
                return {'valid': False, 'error': 'No JSON array found'}
            vectors = json.loads(json_match.group())
        except json.JSONDecodeError:
            return {'valid': False, 'error': 'Invalid JSON'}

        # Step 2: Validate structure
        for vec in vectors:
            if len(vec) != n_a + n_b:
                return {'valid': False, 'error': f'Vector length {len(vec)} != {n_a + n_b}'}

            # Exactly one TRUE in Market A positions
            a_trues = sum(vec[:n_a])
            if a_trues != 1:
                return {'valid': False, 'error': f'Market A has {a_trues} TRUEs'}

            # Exactly one TRUE in Market B positions
            b_trues = sum(vec[n_a:])
            if b_trues != 1:
                return {'valid': False, 'error': f'Market B has {b_trues} TRUEs'}

        # Step 3: Determine relationship
        max_possible = n_a * n_b
        actual = len(vectors)

        if actual == max_possible:
            return {
                'valid': True,
                'relationship': 'INDEPENDENT',
                'vectors': vectors,
                'dependency_ratio': 0.0,
            }
        elif actual < max_possible:
            return {
                'valid': True,
                'relationship': 'DEPENDENT',
                'vectors': vectors,
                'missing_count': max_possible - actual,
                'dependency_ratio': 1 - (actual / max_possible),
            }
        else:
            return {'valid': False, 'error': f'Too many vectors: {actual} > {max_possible}'}
```

### Component C7: Multi-Layer Validation Pipeline

#### AI Level: AI
#### Effort: 3-4 hours

**What**: Given the 97.3% false positive rate, aggressive filtering is essential.

```python
class ArbitrageValidator:
    """8-filter pipeline to reduce false positives."""

    FILTERS = [
        'llm_confidence',
        'state_space_verification',
        'rule_based_cross_check',
        'orderbook_depth',
        'temporal_proximity',
        'resolution_source_match',
        'minimum_spread',
        'no_ambiguity_flags',
    ]

    def validate(self, opportunity, llm_result, market_a, market_b):
        """Run all filters. ALL must pass."""
        results = {}

        # 1. LLM confidence
        results['llm_confidence'] = (
            llm_result.get('valid', False) and
            llm_result.get('dependency_ratio', 0) > 0.3
        )

        # 2. State space verification (programmatic)
        results['state_space_verification'] = self._verify_state_space(
            llm_result.get('vectors', []),
            len(market_a['conditions']),
            len(market_b['conditions'])
        )

        # 3. Cross-check with rule-based detectors
        results['rule_based_cross_check'] = self._rule_based_check(
            market_a, market_b
        )

        # 4. Orderbook depth (can we actually execute?)
        results['orderbook_depth'] = (
            market_a.get('liquidityNum', 0) > 1000 and
            market_b.get('liquidityNum', 0) > 1000
        )

        # 5. Temporal proximity (markets should resolve around same time)
        results['temporal_proximity'] = self._check_temporal(
            market_a.get('endDateISO'), market_b.get('endDateISO')
        )

        # 6. Resolution source consistency
        results['resolution_source_match'] = self._check_resolution(
            market_a.get('resolutionSource', ''),
            market_b.get('resolutionSource', '')
        )

        # 7. Minimum spread after fees
        results['minimum_spread'] = opportunity.get('profit', 0) > 0.03

        # 8. No ambiguity flags
        results['no_ambiguity_flags'] = not self._has_ambiguity(
            market_a.get('description', ''),
            market_b.get('description', '')
        )

        passed = all(results.values())
        return {
            'passed': passed,
            'filters': results,
            'failed_filters': [k for k, v in results.items() if not v],
        }
```

### Component C8: Multi-Leg Execution Handler

#### AI Level: GUIDED
#### Effort: 4-6 hours

**What**: Execute 2+ orders near-simultaneously with partial fill handling.

```python
class MultiLegExecutor:
    def __init__(self, client, max_slippage=0.02):
        self.client = client
        self.max_slippage = max_slippage

    async def execute_arb(self, legs, position_size):
        """
        Execute multi-leg arbitrage trade.

        Strategy: Execute the least liquid leg first.
        If it fills, execute remaining legs.
        If it fails, abort.
        """
        # Sort legs by liquidity (least liquid first)
        sorted_legs = sorted(legs, key=lambda l: l['liquidity'])

        filled_legs = []

        for leg in sorted_legs:
            try:
                result = await self._execute_leg(leg, position_size)

                if result['filled']:
                    filled_legs.append(result)
                else:
                    # Partial or no fill — unwind previous legs
                    await self._unwind(filled_legs)
                    return {'success': False, 'reason': 'leg_failed', 'leg': leg}

            except Exception as e:
                await self._unwind(filled_legs)
                return {'success': False, 'reason': str(e)}

        return {
            'success': True,
            'legs': filled_legs,
            'total_cost': sum(l['cost'] for l in filled_legs),
            'expected_profit': 1.0 - sum(l['cost'] for l in filled_legs),
        }

    async def _execute_leg(self, leg, size):
        """Execute a single leg with slippage protection."""
        # Get current price
        current_price = float(
            self.client.get_price(leg['token_id'], side='BUY')['price']
        )

        # Check slippage
        if abs(current_price - leg['expected_price']) > self.max_slippage:
            return {'filled': False, 'reason': 'slippage_exceeded'}

        # Place FOK order (fill-or-kill)
        order = MarketOrderArgs(
            token_id=leg['token_id'],
            amount=size,
            side=BUY,
            order_type=OrderType.FOK,
        )
        signed = self.client.create_market_order(order)
        response = self.client.post_order(signed, OrderType.FOK)

        return {
            'filled': response.get('status') == 'filled',
            'cost': current_price * size,
            'price': current_price,
            'leg': leg,
        }

    async def _unwind(self, filled_legs):
        """Unwind filled legs if later legs fail."""
        for leg in filled_legs:
            # Sell back at market
            # Accept loss on the unwind
            sell_order = MarketOrderArgs(
                token_id=leg['leg']['token_id'],
                amount=leg['cost'],
                side=SELL,
                order_type=OrderType.FOK,
            )
            signed = self.client.create_market_order(sell_order)
            self.client.post_order(signed, OrderType.FOK)
```

**Why GUIDED**: Multi-leg execution is where real money is at risk. Partial fill handling, slippage protection, and unwind logic must be reviewed carefully.

---

## Fine-Tuning Pipeline (Phase 2, Components C10-C11)

### Data Collection (C10 - HUMAN, 8-15 hrs)

1. Run GPT-4o on 500 market pairs from your embedding similarity search
2. Cost: ~$2.00 total for 500 calls
3. Manually review outputs — expect ~20% errors
4. Correct labels and save as training data

```jsonl
{"messages": [
  {"role": "system", "content": "You classify relationships between prediction market conditions."},
  {"role": "user", "content": "Market A: 'Will Trump win the 2024 election?'\nMarket B: 'Will a Republican win the 2024 election?'"},
  {"role": "assistant", "content": "{\"relationship\": \"A_implies_B\", \"confidence\": 0.95, \"reasoning\": \"If Trump wins, a Republican wins. But a Republican could win without Trump.\"}"}
]}
```

### Fine-Tuning Options (C11 - GUIDED, 3-4 hrs)

**Option A: GPT-4o-mini fine-tune** (easiest)
- Upload JSONL to OpenAI
- Cost: ~$0.50 for 500 examples
- Time: 30-60 minutes
- Expected accuracy: 90-95% (up from ~75% zero-shot)

**Option B: Llama 3.1 8B LoRA** (zero ongoing cost)
- LoRA rank 16, alpha 32
- Train on vast.ai GPU spot instance (~$0.50)
- Quantize to GGUF Q4_K_M for CPU inference
- CPU inference: 10-20 tok/s (10-20 sec per classification)
- Expected accuracy: 83-90% fine-tuned

**Recommendation**: Start with Option A (fast, easy), switch to Option B once you validate the approach works in production.

---

## Scanning Loop Architecture

```python
class CombinatorialScanner:
    """Main scanning loop combining all detectors."""

    def __init__(self, config):
        self.partition_detector = PartitionDetector()
        self.rebalancing_detector = RebalancingDetector()
        self.temporal_detector = TemporalDetector()
        self.subset_detector = SubsetDetector()
        self.grouper = MarketGrouper()
        self.llm_classifier = LLMRelationshipClassifier(config.llm_api_key)
        self.validator = ArbitrageValidator()
        self.executor = MultiLegExecutor(config.clob_client)

    async def scan_cycle(self):
        """Single scan cycle — run every 5-10 minutes."""
        # Fetch all active markets
        markets = await self.fetch_all_markets()
        events = await self.fetch_all_events()

        opportunities = []

        # Phase A: Rule-based (instant, free)
        opportunities += self.partition_detector.scan_events(events)
        opportunities += self.rebalancing_detector.scan_markets(markets)
        opportunities += self.temporal_detector.find_violations(markets)
        opportunities += self.subset_detector.scan_all_pairs(markets)

        # Phase B: LLM-enhanced (optional, costs $)
        if self.config.enable_llm_detection:
            # Only run on markets not already caught by rules
            uncaught = self.filter_already_detected(markets, opportunities)
            candidates = self.grouper.find_candidate_pairs_batch(uncaught)

            for pair in candidates:
                llm_result = await self.llm_classifier.classify_relationship(
                    pair['market_a']['conditions'],
                    pair['market_b']['conditions']
                )

                if llm_result.get('relationship') == 'DEPENDENT':
                    opp = self.build_opportunity(pair, llm_result)
                    validation = self.validator.validate(
                        opp, llm_result,
                        pair['market_a'], pair['market_b']
                    )

                    if validation['passed']:
                        opportunities.append(opp)

        # Rank and execute
        ranked = sorted(opportunities, key=lambda x: -x.get('net_profit', 0))

        for opp in ranked[:3]:  # Max 3 trades per cycle
            if self.config.paper_trade:
                self.log_paper_trade(opp)
            else:
                result = await self.executor.execute_arb(
                    opp['legs'],
                    self.config.position_size
                )
                self.log_trade(opp, result)
```

---

## Risk Management

### Position Limits for Combinatorial Arb

```python
COMBO_RISK_LIMITS = {
    'max_position_per_arb': 0.15,     # Max 15% of bankroll per arb (it's "near-risk-free")
    'max_total_arb_exposure': 0.60,   # Max 60% in active arbs
    'min_net_profit': 0.02,           # Min 2% net profit after fees
    'max_legs': 5,                    # Max 5 legs per arb (more legs = more execution risk)
    'min_liquidity_per_leg': 500,     # Min $500 liquidity per leg
    'max_slippage': 0.02,             # Max 2% slippage per leg
    'require_validation': True,       # Must pass 8-filter validation
    'llm_min_confidence': 0.8,        # For LLM-detected opportunities
}
```

### What Can Go Wrong

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| False positive (LLM) | HIGH | HIGH (97.3%) | 8-filter validation pipeline |
| Partial fill | HIGH | MEDIUM | FOK orders + unwind logic |
| Resolution ambiguity | HIGH | LOW | Read resolution criteria carefully |
| Oracle dispute | HIGH | VERY LOW | Avoid subjective markets |
| Slippage on execution | MEDIUM | MEDIUM | Slippage limits, smaller positions |
| Fee miscalculation | MEDIUM | LOW | Conservative fee estimates |

---

*This document details the complete implementation for Strategy 5. See COMBINED_STRATEGY_ROADMAP.md for how it integrates with Strategy 1 and the shared infrastructure.*

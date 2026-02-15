# Strategy 5: Combinatorial Arbitrage (LLM-Based Relationship Detection)

## Feasibility Score: 8/10

---

## Concept

Logically related markets on Polymarket are frequently mispriced against each other. Using LLMs and NLP, detect these logical relationships and exploit pricing violations.

**Types of violations:**

1. **Subset violation**: "Trump wins presidency" (55%) > "Republican wins presidency" (50%) → Impossible. Buy Republican, sell Trump.

2. **Exhaustive partition violation**: "Candidate A" (40%) + "Candidate B" (35%) + "Candidate C" (30%) = 105% → Sum should be ≤100%. Sell all three.

3. **Temporal consistency violation**: "BTC > $100k in Feb 2026" (20%) > "BTC > $100k in 2026" (15%) → Impossible. Monthly must be ≤ yearly.

---

## What You'd Need to Implement This

### Data Requirements
- **All active market data**: Questions, descriptions, prices, volumes from Polymarket Gamma API
- **Market embeddings**: Vector representations of market questions for similarity search
- **LLM access**: For classifying relationships between market pairs
- **Historical arbitrage data**: Track which relationships have existed and how they resolved

### Resources & Compute
| Resource | Requirement | Cost Estimate |
|----------|-------------|---------------|
| Market data | Gamma API (all active markets) | Free |
| LLM API | GPT-4o/Claude for relationship classification | $10-50/month (batched queries) |
| Embedding model | sentence-transformers (local) or OpenAI embeddings | Free (local) or $5/month |
| Vector database | ChromaDB (local) or Pinecone | Free (local) |
| Compute | CPU for embeddings, GPU for fine-tuned models | $20-50/month |
| Non-US server | Required for Polymarket access | $30-80/month |

### Technical Skills Required
- **NLP/Embeddings** (you have this): Sentence transformers, semantic similarity
- **LLM prompting/fine-tuning** (you have this): Relationship classification
- **Graph theory**: Model market relationships as directed graphs for arbitrage detection
- **Combinatorial optimization**: Multi-leg position sizing
- **Risk management**: Multi-leg execution with slippage

---

## What Would Be Your Edge?

### This Is Where Your NLP Skills Are Most Valuable

The IMDEA study (2025) — the most comprehensive research on Polymarket arbitrage — explicitly used LLMs and text embeddings for combinatorial arbitrage detection. Their methodology:

1. **Embedding generation**: Used Linq-Embed-Mistral to create vector representations of market questions
2. **Similarity clustering**: Grouped markets by semantic similarity using vector search
3. **LLM classification**: Used DeepSeek-R1-Distill-Qwen-32B to classify relationships between pairs:
   - A implies B
   - B implies A
   - Mutually exclusive
   - Independent
4. **Arbitrage detection**: Check if prices violate the classified relationship

### The Results Were Massive

- **41% of Polymarket conditions showed arbitrage opportunities**
- **$39.59M total profit extracted** over the study period (Apr 2024 - Apr 2025)
- **Top 3 wallets: $4.2M combined** from 10,200 trades
- Political markets had the largest spreads; sports markets had the most frequent opportunities

### Your Specific ML Edge

1. **Better embeddings**: You can fine-tune embedding models on Polymarket market descriptions for higher-quality similarity matching. Off-the-shelf embeddings miss domain-specific nuances.

2. **Better relationship classification**: Fine-tune an LLM on labeled market pairs to improve classification accuracy. The IMDEA study used general-purpose LLMs — a fine-tuned model would be superior.

3. **Multi-hop reasoning**: Some arbitrage requires chaining relationships (A→B, B→C, therefore A→C). Graph-based reasoning over market relationships can find opportunities that pairwise analysis misses.

4. **Automated pipeline**: Build an end-to-end system: embed markets → cluster → classify pairs → detect violations → execute. The full pipeline is your moat.

### Estimated Edge: 2-8% per opportunity

---

## Is the Alpha Already Arbitraged Away?

### No — this is one of the least-competed strategies

1. **High implementation complexity**: This requires NLP expertise + LLM integration + graph theory + multi-leg execution. Very few traders can build this end-to-end.

2. **The IMDEA study is recent**: Published in 2025, the methodology is cutting-edge. Few teams have replicated it.

3. **New markets constantly create new relationships**: Polymarket launches new markets daily. Each new market potentially creates new relationships with existing markets, generating fresh opportunities.

4. **The $40M was extracted by a very small number of wallets**: The top 3 wallets captured most of the profit. This isn't a crowded trade — it's dominated by a few sophisticated actors.

5. **Open-source implementations are basic**: The GitHub arb bots focus on same-market rebalancing (YES + NO < $1), not LLM-based combinatorial detection. Your implementation would be differentiated.

### Alpha decay risk is LOW because:
- Each new market creates new arbitrage potential
- The relationship detection requires ongoing ML work (not a one-time setup)
- Most competitors lack the NLP expertise to replicate this effectively

---

## Why Don't More People Do This?

1. **NLP expertise required**: You need to build and maintain semantic similarity systems, LLM classification pipelines, and embedding models. This is a specialized skill set.

2. **Multi-leg execution complexity**: Combinatorial arb requires executing 2-3 trades simultaneously. Partial fills create unhedged directional exposure.

3. **False positive risk**: LLMs can hallucinate relationships that don't actually exist. A false positive means you take a directional bet thinking it's an arb.

4. **Resolution ambiguity**: Two markets that SEEM logically related may have subtly different resolution criteria that invalidate the relationship.

5. **Capital requirements per opportunity**: Each arb requires positions in 2-3 markets. With $500-2K capital, you can only run a few simultaneous arbs.

6. **Not many people know about the IMDEA methodology**: The academic paper is recent and fairly niche. Most retail traders and even most bot developers haven't read it.

---

## Possible Exposure (Risk)

| Risk | Severity | Mitigation |
|------|----------|------------|
| **False relationship detection** | HIGH | Use multiple verification steps: LLM + embedding similarity + manual rules. Require high confidence threshold (>0.9). |
| **Resolution ambiguity** | HIGH | Read resolution criteria for BOTH markets. Only trade pairs with identical or clearly nested resolution sources. |
| **Multi-leg execution** | MEDIUM | Use limit orders. Execute the harder-to-fill leg first. Have partial-fill handling. |
| **LLM hallucination** | MEDIUM | Cross-validate with rule-based checks. Use ensemble of LLMs. Human review for first 50 trades. |
| **Market impact** | LOW-MEDIUM | With small capital, your orders won't move the market. But in thin markets, slippage matters. |
| **Capital lock-up** | MEDIUM | Positions lock until both markets resolve (could be different dates). Prioritize markets with similar resolution dates. |

### Expected P&L Profile
With $1,000 capital, 3-5 opportunities/month:
- Average profit per arb: $30-80 (3-8% on ~$500 positions)
- False positive cost: -$50-100 (directional loss on misclassified pair)
- Monthly P&L: $50-200 (5-20% monthly)
- Worst month: -$100 to -$200 (multiple false positives or resolution surprises)

---

## Additional Considerations

### Implementation Architecture

```
┌─────────────────────────────────────────────────┐
│                Pipeline Overview                  │
├─────────────────────────────────────────────────┤
│                                                   │
│  1. EMBED: All active markets → vector space      │
│     ├─ sentence-transformers (local)              │
│     └─ Store in ChromaDB                          │
│                                                   │
│  2. CLUSTER: Find similar market pairs            │
│     ├─ Cosine similarity > 0.8                    │
│     └─ Temporal proximity filter                  │
│                                                   │
│  3. CLASSIFY: LLM determines relationship         │
│     ├─ "A implies B" / "mutually exclusive" / etc │
│     ├─ Confidence score                           │
│     └─ Cross-validate with rule-based checks      │
│                                                   │
│  4. DETECT: Check for price violations            │
│     ├─ If "A implies B" and P(A) > P(B) → ARB    │
│     ├─ If "exhaustive" and sum > 100% → ARB       │
│     └─ Calculate profit after fees                │
│                                                   │
│  5. EXECUTE: Multi-leg order placement            │
│     ├─ Harder leg first                           │
│     ├─ Partial fill handling                      │
│     └─ Position monitoring                        │
│                                                   │
└─────────────────────────────────────────────────┘
```

### Fine-Tuning Opportunity

The IMDEA study used general-purpose LLMs (DeepSeek). You could gain an edge by:

1. **Collecting labeled data**: Manually label 200-500 market pairs with their true relationships
2. **Fine-tuning a small model**: LoRA fine-tune a 7B parameter model on this labeled data
3. **Deploying locally**: Run inference locally for speed and cost savings
4. **Continuous improvement**: As you validate relationships through resolution, feed outcomes back into training data

This creates a compounding advantage — your model gets better over time, while competitors using general LLMs stay static.

### Graph-Based Arbitrage Detection

Beyond pairwise analysis, model all market relationships as a directed graph:

```
"Trump wins" → "Republican wins" → "GOP controls White House"
"Trump wins" ⊕ "Biden wins" (mutually exclusive)
```

Then use graph algorithms (cycle detection, constraint propagation) to find multi-hop arbitrage that pairwise analysis misses.

### Your Dependencies Are Already in requirements.txt

The codebase already includes the key dependencies:
- `chromadb>=0.4.0` — Vector database
- `sentence-transformers>=2.2.0` — Embedding models
- The scanner already has a stub for combinatorial arbitrage

This means the infrastructure is partially built — you'd be extending, not starting from scratch.

### References
- [IMDEA: "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"](https://arxiv.org/abs/2508.03474)
- [Full IMDEA Paper PDF](https://suarez-tangil.networks.imdea.org/papers/2025aft-arbitrage.pdf)
- [Polymarket Agents (Official AI Trading Framework)](https://github.com/Polymarket/agents)
- [QuantVPS: Polymarket HFT and AI Arbitrage](https://www.quantvps.com/blog/polymarket-hft-traders-use-ai-arbitrage-mispricing)
- [ChainCatcher: Polymarket 2025 Six Major Profit Models](https://www.chaincatcher.com/en/article/2233047)

---

## Verdict

**Worth investing time: STRONGLY YES**

This is the highest-ROI strategy for your specific skill set. It directly leverages your NLP/deep learning expertise, has the least competition (high complexity barrier), and the IMDEA research proves $40M+ was extractable over one year. The alpha is NOT arbitraged away because:
1. Few people have the NLP skills to build the detection pipeline
2. New markets constantly create new relationships
3. Your fine-tuned models would improve over time (compounding advantage)

This should be your **primary focus** alongside Strategy 1 (probability arbitrage). The two are complementary:
- Combinatorial arb gives you near-risk-free opportunities (when relationships are correctly identified)
- Probability arb gives you directional edge (when your model is well-calibrated)

**Time to first results**: 3-5 weeks (embedding pipeline + LLM classification + backtesting)
**Capital efficiency**: Good (near-risk-free when correctly identified)
**Scalability**: Grows with number of active markets on Polymarket

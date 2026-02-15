# LLM-Based Relationship Classification for Combinatorial Arbitrage

## Research Summary

This document synthesizes methodology from three academic papers, current LLM pricing/benchmarks, and practical fine-tuning approaches for classifying logical relationships between Polymarket questions. All methodology details for the IMDEA paper are extracted directly from the full-text HTML version of the paper (arxiv 2508.03474v1), including their exact LLM usage, prompt design, validation pipeline, and quantitative results.

---

## 1. The IMDEA Methodology (Saguillo et al., 2025)

**Paper**: ["Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"](https://arxiv.org/abs/2508.03474)
**Published**: AFT 2025 (Advances in Financial Technologies), supported by Flashbots Research Proposal FRP-51
**Authors**: Oriol Saguillo, Vahid Ghafouri, Lucianna Kiffer, Guillermo Suarez-Tangil (IMDEA Networks, Madrid)
**Data**: 86 million Polymarket bids (OrderFilled events), Apr 2024 - Apr 2025
**Dataset**: 8,659 single-condition markets + 1,578 multi-condition markets (8,559 conditions total)

### 1.1 The Core Problem: Combinatorial Explosion

Formally, two markets are **dependent** if |V1 x V2| < n * m -- that is, the number of valid joint resolution vectors is strictly less than the product of individual resolution counts. This means the outcome of one market constrains the outcome of another.

With N markets and M conditions, exhaustively checking all pairwise dependencies requires O(2^{n+m}) comparisons per pair. For the Nov 5, 2024 U.S. election snapshot alone, there were **46,360 market pairs** to analyze in the Politics category. Brute force is infeasible.

### 1.2 Their Three-Stage Pipeline

#### Stage 1: Heuristic Reduction (Embedding + Topic Filtering)

**Model**: Linq-Embed-Mistral (7B parameter embedding model)
- Ranked #1 on MTEB retrieval leaderboard at time of use (average score 68.2 across 56 datasets)
- Generated vector embeddings for both market questions AND topic labels

**Topic Classification Process**:
1. Define 7 predefined topic categories matching Polymarket's website: **Politics, Economy, Technology, Crypto, Twitter, Culture, Sports**
2. Embed all market question texts into vector space using Linq-Embed-Mistral
3. Embed each of the 7 topic labels into the same vector space
4. For each market, compute cosine similarity between its question embedding and all 7 topic embeddings
5. Assign the market to the topic with the highest cosine similarity
6. **Validation**: Random sampling of 100 instances yielded **92% accuracy** on topic assignment
7. **Known limitations**: Weather-related markets and contextually ambiguous markets were sometimes misclassified

**Filtering Heuristics** (applied BEFORE LLM classification):
- **Temporal filtering**: Only consider pairs of markets that share the same end date. End date is computed as the most frequent end date among conditions within the same market ID.
- **Topical filtering**: Only consider pairs within the same topic AND same end date. This limits the search space to markets about the same event/domain.
- **Condition reduction**: Markets are reduced to a maximum of 5 conditions (top 4 by trading volume plus a catch-all "Other" condition). Justification: 90% of all liquidity in a market resides in the top 4 conditions.

This reduces the candidate set from millions of pairs down to ~46,360 (for the Politics/Nov 5 snapshot).

#### Stage 2: LLM State Space Enumeration (NOT Simple Classification)

**Model**: DeepSeek-R1-Distill-Qwen-32B (32B parameter reasoning model)
- Distilled from DeepSeek-R1 into Qwen-32B architecture
- Key advantage: strong chain-of-thought reasoning at moderate parameter count

**Critical insight: The IMDEA approach is NOT a simple "classify the relationship" prompt.** Instead, they use the LLM to **exhaustively enumerate the joint state space** of valid resolution combinations. The approach works in two modes:

**Mode 1: Single-Market Inference (Section 5.1)**

For a single market with conditions C1, C2, C3, the LLM outputs all n possible resolution vectors where exactly one condition is true:
```
[True, False, False]  # C1 wins
[False, True, False]  # C2 wins
[False, False, True]  # C3 wins
```

Instead of making n separate LLM calls, they compose queries so that the entire outcome space is computed in a single call. Accuracy on single-market inference: **81.45%** (101 out of 128 markets met all consistency conditions).

**Mode 2: Multi-Market Joint Inference (Section 5.2)**

For two markets, they UNION the conditions from both markets into a single set, pass them to the LLM as numbered statements, and ask for ALL valid joint resolution vectors.

**Input format**: Conditions are formatted as numbered statements:
```
(0) Trump wins the 2024 election
(1) Harris wins the 2024 election
(2) Other candidate wins the 2024 election
(3) Republican wins the 2024 election
(4) Democrat wins the 2024 election
(5) Other party wins the 2024 election
```

**The LLM prompt** (described in Appendix B) instructs the model to:
1. Determine ALL valid logical combinations of truth values for the given questions
2. Output results as **JSON arrays** where each entry represents one possible resolution
3. Ensure **exactly one true condition per market's condition set**

**Example output** (JSON array of resolution vectors):
```json
[
  [true, false, false, true, false, false],   // Trump wins -> Republican wins
  [false, true, false, false, true, false],   // Harris wins -> Democrat wins
  [false, false, true, false, false, true]    // Other -> Other party
]
```

If the number of valid joint vectors is less than n * m (the product of individual market condition counts), the markets are **dependent**. If equal to n * m, they are **independent**.

#### Stage 2b: Three-Step Output Validation

Every LLM response goes through three automated consistency checks:
1. **Valid JSON returned**: The response must parse as valid JSON
2. **Exactly one true value per market's condition set**: Each resolution vector must have exactly one True among Market A's conditions and exactly one True among Market B's conditions
3. **Output vector count constraint**: The number of resolution vectors must be <= n + m (for reduced market pairs of sizes n and m)

**Failure rates on 46,360 pairs (Politics, Nov 5, 2024)**:
- 353 pairs: no JSON returned at all
- 4,374 pairs: failed consistency checks
- 40,057 pairs: classified as independent
- 1,576 pairs: classified as dependent by the LLM
- **374 pairs**: survived subset filtering (pairs where one market's conditions are a logical subset of another's)
- **13 pairs**: survived manual verification as genuinely dependent

#### Stage 3: Manual Verification + Arbitrage Detection

From the 41,031 successfully LLM-classified pairs, researchers manually checked the 374 pairs that passed subset filtering. They identified **11 NegRisk-NegRisk pairs** and **2 NegRisk-Single pairs** satisfying the formal combinatorial arbitrage definition.

**Known LLM error modes**:
- 8 specific markets contributed to 1,469 invalid pairs due to inherent ambiguity (listed in Appendix E of the paper)
- The LLM struggles with markets that have too many conditions
- The LLM sometimes conflates related but distinct concepts (e.g., popular vote vs. electoral college)

### 1.3 Reconstructed Prompt Template

The paper describes the prompt in Appendix B but does not reproduce it verbatim. Based on the described methodology (state space enumeration, JSON output, per-market exclusivity constraint), the prompt structure is:

```
Given the following questions, determine all valid logical combinations of
truth values. Each question is part of a group. Within each group, exactly
one question must be true and all others must be false.

Group 1 (Market A):
(0) {condition_0_text}
(1) {condition_1_text}
(2) {condition_2_text}

Group 2 (Market B):
(3) {condition_3_text}
(4) {condition_4_text}
(5) {condition_5_text}

List ALL possible valid resolution states as a JSON array.
Each state is an array of boolean values corresponding to questions (0)-(5).
Constraints:
- Exactly one value in Group 1 must be true
- Exactly one value in Group 2 must be true
- The combination must be logically possible in the real world

Output only the JSON array, no explanation.
```

**Why this approach matters**: Unlike a simple "classify the relationship" prompt, the state space enumeration approach:
1. Makes the reasoning verifiable (you can check each resolution vector)
2. Naturally handles complex multi-condition dependencies
3. Produces structured output that can be automatically validated
4. Catches partial dependencies (e.g., "condition 2 of Market A implies condition 4 of Market B" without a full market-level implication)

### 1.4 IMDEA Quantitative Results

**LLM Classification Pipeline**:
- 46,360 market pairs analyzed (Politics category, Nov 5, 2024 snapshot)
- 353 pairs (0.8%): LLM returned no valid JSON
- 4,374 pairs (9.4%): Failed automated consistency checks
- 40,057 pairs (86.4%): Classified as independent
- 1,576 pairs (3.4%): Classified as dependent
- 374 pairs: Survived subset filtering
- **13 pairs: Confirmed genuinely dependent** after manual verification
- **False positive rate: ~97.3%** of LLM-detected "dependent" pairs were actually independent (1,563/1,576)

**Arbitrage Extraction**:
- 5 of 13 confirmed dependent pairs generated realized arbitrage profits: **$95,157 total**
- 8 of 13 pairs failed to yield profit despite correct dependency detection
- Combinatorial arbitrage = **0.24%** of total arbitrage profits
- Single-market rebalancing = **$10.58M** (buying below $1.00: $5.90M, selling above $1.00: $4.68M)
- **Total arbitrage extracted across all types: $39.59M** over Apr 2024 - Apr 2025
- 41% of conditions showed arbitrage opportunities at some point
- Top 3 wallets: $4.2M combined from 10,200 trades

**Confirmed Dependent Pairs (U.S. Election 2024)**:
- Popular vote winner + popular vote winner becoming president
- GOP presidential win margin (appears in pairs 1 and 2)
- Balance of power among presidency, House, and Senate
- 11 NegRisk-NegRisk pairs, 2 NegRisk-Single pairs

**LLM Error Examples**:
- Swing state winner vs. overall election winner: LLM conflated these as dependent when they are only correlated
- Popular vote vs. electoral college: LLM could not distinguish these distinct mechanisms
- Markets with 10+ conditions: LLM accuracy degraded significantly

---

## 2. The Semantic Trading Approach (Capponi et al., 2025)

**Paper**: ["Semantic Trading: Agentic AI for Clustering and Relationship Discovery in Prediction Markets"](https://arxiv.org/abs/2512.02436)
**Authors**: Columbia University + IBM Research (Dec 2025)
**Dataset**: Historical resolved markets on Polymarket

### 2.1 Key Differences from IMDEA

This paper takes a fundamentally different approach:
- Uses an **agentic LLM pipeline** (multi-step, not single-shot)
- Does NOT enumerate state spaces; instead classifies relationships semantically
- Focuses on **same-outcome** (correlated) and **different-outcome** (anti-correlated) relationships
- Validates relationships **statistically** using resolved market outcomes, not just semantic analysis
- Achieved ~**60-70% accuracy** on relationship prediction
- Trading strategy: **~20% average returns** over week-long horizons

### 2.2 Their Pipeline

1. **Clustering**: LLM reads contract text + metadata, groups markets into coherent topical clusters using NLP
2. **Within-Cluster Discovery**: For each cluster, LLM proposes market pairs that should have strong outcome dependence
3. **Statistical Validation**: Check proposed relationships against historical resolved outcomes
4. **Trading Signal**: If relationship is empirically reliable, use divergence from expected relationship as trading signal

### 2.3 Critical Insight: 60-70% Accuracy Is Enough

Even at 60-70% relationship detection accuracy, the trading strategy was profitable because:
- True positives generate near-risk-free profit (price convergence is guaranteed for valid relationships)
- False positives generate random directional exposure (roughly 50/50 win/loss)
- Net expected value is positive as long as accuracy exceeds ~55%

**This is the most important practical insight**: You do NOT need 95%+ accuracy to be profitable. The asymmetry between true positives (guaranteed convergence) and false positives (random noise) means even a mediocre classifier generates positive expected value.

---

## 3. The Lead-Lag Approach (Feb 2026)

**Paper**: ["LLM as a Risk Manager: LLM Semantic Filtering for Lead-Lag Trading"](https://arxiv.org/abs/2602.07048)
**Dataset**: 554 Kalshi Economics markets, Oct 2021 - Nov 2025, 18 rolling windows

### 3.1 The Hybrid Two-Stage Architecture

**Stage 1 (Statistical)**: Granger causality testing across all 554 markets identifies candidate leader-follower pairs. Retains top K=100 directed pairs ranked by p-value significance. Time series preprocessing: daily YES contract prices transformed via log-odds (l = log(p/(100-p))), ADF stationarity testing, first differencing when needed, lag lengths swept across {1,2,3,4,5}.

**Stage 2 (Semantic)**: **GPT-4-nano** re-ranks the 100 statistical candidates based on mechanistic plausibility. The LLM prompt (Figure 3 of paper) presents a directed event pair and asks whether "a plausible economic transmission mechanism exists" beyond mere correlation. It requests a strength level assessment and predicts the expected sign of co-movement. Output: structured JSON. Final portfolio: top M=20 pairs after LLM re-ranking.

**Robustness validation**: Also tested with GPT-4-mini; results consistent.

### 3.2 Trading Protocol

- Leader-triggered entry: when daily price change exceeds threshold theta (default theta=0)
- Fixed position size: $100 per contract
- Follower entry direction: d_t = sign(r_leader,t) * s(Leader->Follower)
- Exit after h days (tested across {1,3,5,7,10,14,21} day horizons)

### 3.3 Results (7-Day Holding Period)

| Metric | Statistical Only | Hybrid (Statistical + LLM) | Improvement |
|---|---|---|---|
| Win rate | 51.4% | 54.5% | +3.1 pp |
| Average loss magnitude | -$649 | -$347 | **-46.5%** |
| Total PnL | $4,100 | $12,500 | **+205%** |

**Segmented results**:
- Same-event pairs: 42.9% loss reduction
- Different-event pairs: 48.1% loss reduction
- Large leader moves (>10pt): Win rate improved from 53.8% to **71.4%** (+17.6 pp)
- Loss reduction persisted across ALL holding periods (mean 36.2% reduction)

**Key example**: Japan Recession -> U.S. GDP Growth pair ranked #71 statistically but #5 after LLM filtering, yielding +$700 PnL. The LLM identified "cross-border trade, financial linkages, and policy spillovers" as the transmission mechanism.

### 3.4 Key Takeaway

LLM semantic understanding provides genuine alpha beyond pure statistical methods. The primary value is in **loss reduction** (filtering out spurious statistical correlations) rather than in finding new opportunities. The LLM acts as a risk manager, not an alpha generator.

---

## 4. Complete Relationship Taxonomy

For a production system, you need to detect these relationship types:

### 4.1 Core Relationships

| Relationship | Definition | Arbitrage Rule | Example |
|---|---|---|---|
| **A implies B (subset)** | P(A) must be <= P(B) | If P(A) > P(B): buy B, sell A | "Trump wins" implies "Republican wins" |
| **B implies A (superset)** | P(B) must be <= P(A) | If P(B) > P(A): buy A, sell B | Reverse of above |
| **Mutually exclusive** | P(A) + P(B) must be <= 1 | If sum > 1: sell both | "Trump wins" vs "Harris wins" (same election) |
| **Exhaustive partition** | Sum of all must equal 1 | If sum != 1: buy/sell spread | All candidates in same race |
| **Temporal consistency** | P(short) <= P(long) | If P(Feb) > P(Year): sell Feb, buy Year | "BTC >100k Feb" vs "BTC >100k 2026" |
| **Equivalent** | P(A) must equal P(B) | If prices diverge: buy cheap, sell expensive | Same question on different platforms |
| **Lead-lag** | Price of A predicts price of B | Trade B when A moves | Japan recession -> US GDP |
| **Independent** | No constraint | No arbitrage | Unrelated events |

### 4.2 Detection Priority (by Practical Value)

| Priority | Relationship | Detection Method | Frequency | Avg Spread |
|---|---|---|---|---|
| 1 | Exhaustive partition | Rule-based (same market group) | Very high | 2-5% |
| 2 | Temporal consistency | Regex + date parsing | High | 3-8% |
| 3 | Subset/superset | LLM classification | Medium | 5-15% |
| 4 | Mutually exclusive | LLM classification | Medium | 3-10% |
| 5 | Lead-lag | Granger causality + LLM | Low-medium | Variable |
| 6 | Equivalent | Cross-platform matching | Low | 1-3% |

**Important**: Priorities 1 and 2 do NOT require an LLM at all. Rule-based detection for exhaustive partitions (conditions within the same Polymarket market must sum to $1.00) and temporal consistency (regex matching on dates) should be implemented first, as they are free, fast, and high-frequency.

### 4.3 The IMDEA Approach vs. Simple Classification

There are two fundamentally different ways to use an LLM for this task:

**Approach A: Direct Classification** (simpler, faster, less accurate)
```
"Is Market A a subset of Market B? Answer: SUBSET / SUPERSET / EXCLUSIVE / INDEPENDENT"
```
Pros: Fast, cheap, works with any LLM including small models
Cons: No verification mechanism, higher hallucination rate

**Approach B: State Space Enumeration** (IMDEA approach, more robust)
```
"List ALL valid joint resolution vectors as JSON"
```
Then compute dependency programmatically from the output.
Pros: Verifiable, catches partial dependencies, structured output
Cons: Requires more tokens, LLM must reason about combinatorics, 81% single-market accuracy

**Recommendation**: Use Approach A for daily scanning (fast, cheap) and Approach B for final verification of detected arbitrage opportunities (thorough, verifiable).

---

## 5. LLM Model Comparison for This Task

### 5.1 Cost Analysis Per 1,000 Classification Calls

Assumptions: ~800 input tokens per call (two market descriptions), ~200 output tokens (reasoning + label). Pricing as of February 2026.

| Model | Input $/M tokens | Output $/M tokens | Cost per 1K calls | Speed | Notes |
|---|---|---|---|---|---|
| **DeepSeek-R1-Distill** (DeepSeek API) | $0.12 | $0.20 | **$0.14** | Moderate | What IMDEA used; cheapest option; 75% off-peak discount |
| **GPT-4o-mini** | $0.15 | $0.60 | **$0.24** | Fast | Best cost/performance for structured tasks |
| **DeepSeek-R1-Distill** (DeepInfra) | ~$0.36 | ~$0.36 | **$0.36** | Moderate | Third-party hosting, higher availability |
| **Claude 4.5 Haiku** | $1.00 | $5.00 | **$1.80** | Very fast | Good reasoning at moderate cost |
| **GPT-4o** | $2.50 | $10.00 | **$4.00** | Fast | Strong but expensive for batch work |
| **Claude 4.5 Sonnet** | $3.00 | $15.00 | **$5.40** | Moderate | Best reasoning of mid-tier models |
| **Llama 3.1 8B** (local GGUF) | $0 | $0 | **$0** | ~15 tok/s CPU | Free after one-time fine-tuning cost |

**Batch API savings**: OpenAI Batch API = 50% off. Anthropic Batch API = 50% off. DeepSeek off-peak = 75% off. For a daily scan that can tolerate 24-hour latency, batch pricing cuts costs in half.

### 5.2 Expected Accuracy by Model

Based on: (a) IMDEA's 81.45% single-market accuracy with DeepSeek-R1-Distill-32B, (b) the Semantic Trading paper's 60-70% with unspecified LLM, (c) general classification benchmarks where GPT-4o-mini trails GPT-4o by ~10-15% on reasoning tasks, and (d) fine-tuned GPT-4o-mini achieving 96-97% on binary classification after training.

| Model | Zero-Shot | With Prompt Engineering | Fine-Tuned | Notes |
|---|---|---|---|---|
| **GPT-4o** | ~80-85% | ~85-90% | ~92-95% (FT available) | Best zero-shot reasoning |
| **Claude 4.5 Sonnet** | ~80-85% | ~85-90% | N/A | Comparable to GPT-4o |
| **DeepSeek-R1-Distill-32B** | ~78-83% | ~83-88% | Open weights | **81.45% empirically (IMDEA)** |
| **GPT-4o-mini** | ~70-78% | ~78-84% | ~90-95% (OpenAI FT) | Best fine-tuning ROI |
| **Claude 4.5 Haiku** | ~72-80% | ~80-86% | N/A | Fast but no fine-tuning |
| **Llama 3.1 8B (base)** | ~55-65% | ~65-75% | N/A | Too weak without fine-tuning |
| **Llama 3.1 8B (LoRA fine-tuned)** | N/A | N/A | ~83-90% | Best local option |

**Critical benchmark from the IMDEA paper**: DeepSeek-R1-Distill-Qwen-32B achieved **81.45% accuracy on single-market state space enumeration** (101/128 markets). For the harder task of joint multi-market enumeration, their automated validation rejected 9.4% of outputs (4,374/46,360) and classified 97.3% of "dependent" outputs as false positives after manual review. This sets a realistic baseline: even a 32B reasoning model makes substantial errors on this task.

**Key insight from Semantic Trading paper**: Even 60-70% accuracy is profitable. The asymmetric payoff (guaranteed convergence on true positives vs. random outcomes on false positives) means net expected value is positive above ~55% accuracy.

### 5.3 Recommendation: Tiered Approach

**Phase 1 (Prototype, weeks 1-3)**: GPT-4o-mini or DeepSeek API
- Cheapest option for rapid iteration ($0.14-$0.24 per 1K calls)
- Build the full pipeline, collect labeled data from corrections
- Scan ~500 candidate pairs daily = $0.07-$0.12/day
- Use DeepSeek off-peak hours (16:30-00:30 GMT) for 75% savings

**Phase 2 (Production, weeks 4-8)**: Fine-tuned Llama 3.1 8B (local) OR fine-tuned GPT-4o-mini
- **Option A**: Fine-tune GPT-4o-mini via OpenAI API ($3 per 1M training tokens). Pros: easy, high accuracy (90%+), still cheap at scale. Cons: API dependency.
- **Option B**: Fine-tune Llama 3.1 8B with QLoRA, quantize to GGUF, deploy locally. Pros: zero marginal cost, full control. Cons: more setup work, lower baseline accuracy.

**Phase 3 (Verification layer)**: GPT-4o or Claude 4.5 Sonnet for state space enumeration
- Use IMDEA approach (Approach B) for final verification of detected arbitrage
- ~5-10 calls/day for actual trading decisions = $0.02-0.05/day
- This is where accuracy matters most -- use the best model available

---

## 6. Fine-Tuning Approach

### 6.1 Training Data Requirements

| Dataset Size | Expected Outcome | Time to Label |
|---|---|---|
| **50-100 examples** | Marginal improvement; model learns output format but not nuance | ~2-3 hours |
| **200-500 examples** | Significant improvement; handles common patterns well | ~8-15 hours |
| **500-1000 examples** | Strong performance; handles edge cases | ~20-30 hours |
| **1000-2000 examples** | Near-optimal; diminishing returns beyond this | ~40-60 hours |

**Recommendation**: Start with 200-300 carefully labeled examples, then grow to 500+ using active learning.

### 6.2 Training Data Format

Use the chat/instruction format in JSONL. Each line is one training example:

```jsonl
{"messages": [{"role": "system", "content": "You classify logical relationships between prediction market questions. Output a JSON object with keys: classification, confidence, reasoning."}, {"role": "user", "content": "Market A: 'Will Donald Trump win the 2024 presidential election?'\nConditions: Yes, No\nResolution: Resolves Yes if Trump wins the 2024 general election per AP.\n\nMarket B: 'Will a Republican win the 2024 presidential election?'\nConditions: Yes, No\nResolution: Resolves Yes if the Republican nominee wins the 2024 general election per AP.\n\nWhat is the logical relationship between Market A (Yes) and Market B (Yes)?"}, {"role": "assistant", "content": "{\"classification\": \"SUBSET\", \"confidence\": \"HIGH\", \"reasoning\": \"Trump winning necessarily means a Republican wins (Trump is the Republican nominee). A=Yes implies B=Yes. Constraint: P(Trump wins) <= P(Republican wins).\"}"}]}
```

For the IMDEA-style state space enumeration approach:

```jsonl
{"messages": [{"role": "system", "content": "Given prediction market conditions grouped by market, enumerate all logically valid joint resolution states as a JSON array of boolean arrays. Exactly one condition per group must be true."}, {"role": "user", "content": "Group 1 (Market A):\n(0) Trump wins the 2024 presidential election\n(1) Harris wins the 2024 presidential election\n(2) Another candidate wins\n\nGroup 2 (Market B):\n(3) Republican wins the 2024 presidential election\n(4) Democrat wins the 2024 presidential election\n(5) Other party wins\n\nList all valid joint resolution states."}, {"role": "assistant", "content": "[[true,false,false,true,false,false],[false,true,false,false,true,false],[false,false,true,false,false,true]]"}]}
```

### 6.3 Labeling Strategy: Bootstrap from LLM + Human Correction

1. **Generate initial labels**: Run GPT-4o on 500 market pairs, collecting full reasoning. Cost: ~$2.00.
2. **Human review**: Review all labels, correct errors. Expect ~15-25% error rate from GPT-4o zero-shot.
3. **Create training set**: Use corrected labels as ground truth.
4. **Active learning loop**: Fine-tune Llama 8B or GPT-4o-mini, run on new pairs, correct errors, retrain.
5. **Resolution validation**: When markets resolve, compare predictions to outcomes. Automatically add confirmed relationships to training data.

This approach means you only need to manually label the corrections (~75-125 out of 500), not all 500 from scratch.

### 6.4 Fine-Tuning GPT-4o-mini (Easiest Path)

OpenAI supports fine-tuning GPT-4o-mini directly:
- **Training cost**: $3.00 per 1M training tokens (~$0.50 for 500 examples)
- **Inference cost**: Same as base GPT-4o-mini ($0.15/$0.60 per M tokens)
- **Expected accuracy lift**: From ~75% zero-shot to ~90-95% fine-tuned (based on similar classification benchmarks; one study showed 47% -> 96% on safety hazard classification)
- **Process**: Upload JSONL to OpenAI API, fine-tune via dashboard, deploy as custom model
- **Turnaround**: ~30-60 minutes for 500 examples

This is the path of least resistance. No local hardware needed, no GGUF conversion, no llama.cpp setup.

### 6.5 Fine-Tuning Llama 3.1 8B with LoRA (Zero Marginal Cost Path)

#### Hardware Requirements

| Approach | VRAM/RAM | Training Time (500 examples) | Inference Speed |
|---|---|---|---|
| **QLoRA on GPU** (RTX 3060 12GB) | 8-12 GB VRAM | ~1-2 hours | ~30-50 tok/s |
| **QLoRA on GPU** (RTX 3090 24GB) | 12-16 GB VRAM | ~30-60 min | ~50-80 tok/s |
| **LoRA on CPU** (LLaMA-Factory) | 16-20 GB RAM | **2-5 days** | ~5-15 tok/s |
| **QLoRA on CPU** (4-bit quantized) | 8-12 GB RAM | **3-7 days** | ~10-20 tok/s |

#### CPU-Only Fine-Tuning: Feasible But Slow

**Yes, CPU-only LoRA fine-tuning is feasible**. LLaMA-Factory 0.9.x has been tested on:
- Intel i5 laptop with 20 GB RAM (Windows 10/11)
- Intel i7 laptop with 16 GB RAM

However, expect:
- **Training**: 2-7 days for 500 examples on a typical consumer CPU
- **Inference**: ~10-20 tokens/second with Q4_K_M quantization via llama.cpp
- A single classification call (~200 output tokens) takes ~10-20 seconds on CPU

**Practical recommendation**: Train on a cheap cloud GPU (vast.ai ~$0.20/hr for RTX 3060, total cost ~$0.50 for the entire fine-tune), then deploy the quantized GGUF model for inference on your local CPU. This gives you the best of both worlds: fast training, free inference.

#### LoRA Configuration for This Task

```python
# Recommended LoRA config for relationship classification
from peft import LoraConfig

lora_config = LoraConfig(
    r=16,                    # Rank 16 sufficient for classification
    lora_alpha=32,           # Alpha = 2 * rank is standard
    lora_dropout=0.05,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
    task_type="CAUSAL_LM",
)

# Training hyperparameters
from transformers import TrainingArguments

training_args = TrainingArguments(
    output_dir="./lora_output",
    num_train_epochs=3,
    per_device_train_batch_size=4,    # Reduce to 1 for CPU
    gradient_accumulation_steps=4,     # Effective batch = 16
    learning_rate=2e-4,
    warmup_steps=10,
    logging_steps=10,
    save_strategy="epoch",
    bf16=True,                         # Use fp32 on CPU
    optim="adamw_torch",               # Use "adamw_bnb_8bit" for QLoRA
)
```

#### Quantized Inference with llama.cpp

After fine-tuning, merge LoRA weights and quantize to GGUF:

```bash
# Merge LoRA adapter into base model
python -m peft.merge_and_unload \
  --base_model meta-llama/Llama-3.1-8B-Instruct \
  --adapter_path ./lora_output \
  --output_dir ./merged_model

# Convert to GGUF format
python convert_hf_to_gguf.py ./merged_model --outfile model.gguf

# Quantize to Q4_K_M for CPU inference
./llama-quantize model.gguf model-q4km.gguf Q4_K_M

# Inference: ~10-20 tok/s on modern CPU
./llama-cli -m model-q4km.gguf \
  -p "<|begin_of_text|><|start_header_id|>system<|end_header_id|>..." \
  --temp 0.1 --top_p 0.9
```

Expected inference performance (Q4_K_M, Llama 3.1 8B):
- **Apple M1/M2**: ~20-30 tok/s
- **Intel i7/i9 (AVX2)**: ~10-15 tok/s
- **AMD Ryzen 7/9**: ~12-18 tok/s
- **Snapdragon X Elite**: ~15-25 tok/s

At 200 output tokens per classification, that is 10-20 seconds per pair. For scanning 500 pairs daily, total runtime is ~1.5-2.5 hours. Acceptable for a daily scan, though not for real-time monitoring.

---

## 7. Recommended Implementation Plan

### Phase 1: Rule-Based Detection (Week 1)

Before any LLM work, implement the free, high-frequency detection methods:

```
1. Intra-market rebalancing: Check if YES + NO < $1.00 or > $1.00 for each condition
2. Exhaustive partition: For multi-condition markets, check if sum of all condition prices != $1.00
3. Temporal consistency: Regex-match markets with time variants (Feb/Q1/2026) and check P(short) <= P(long)

Cost: $0
Compute: Trivial (API calls + arithmetic)
Expected opportunities: 5-15 per day (based on IMDEA finding that 41% of conditions show arbitrage at some point)
```

### Phase 2: LLM Pipeline Prototype (Weeks 2-3)

```
Pipeline:
  Gamma API (all active markets) →
  Embed with sentence-transformers (all-MiniLM-L6-v2 or similar) →
  ChromaDB: cosine similarity > 0.7, same topic, overlapping dates →
  GPT-4o-mini / DeepSeek API: classify relationship (Approach A) →
  Constraint graph (NetworkX) →
  Price violation detection →
  Alert system

Cost: ~$5-10/month API costs
Output: Working pipeline, initial labeled dataset of ~500 classified pairs
```

### Phase 3: Data Collection + Fine-Tuning (Weeks 4-6)

```
1. Run pipeline on all active markets for 2-3 weeks
2. Collect 300-500 classified pairs with full LLM reasoning
3. Human-review all classifications (correct ~20%, ~8-15 hours)
4. Choose fine-tuning path:
   a. GPT-4o-mini via OpenAI API ($0.50, 30 min, easiest)
   b. Llama 3.1 8B via QLoRA on cloud GPU ($0.50, 1-2 hours, zero ongoing cost)
5. Validate fine-tuned model against base model on held-out 20% test set
6. Deploy winner

Cost: ~$5 one-time + human review time
Output: Fine-tuned model with ~85-92% accuracy
```

### Phase 4: Production System (Weeks 6+)

```
Pipeline:
  Gamma API (poll every 5 min for price updates, daily for new markets) →
  Embed new markets locally (sentence-transformers) →
  ChromaDB similarity search (< 1 second) →
  Classification:
    - Rule-based checks first (free, instant)
    - Local Llama 8B or fine-tuned GPT-4o-mini for LLM classification
    - For detected arbs: GPT-4o state space enumeration (IMDEA Approach B) for verification
  Constraint graph (NetworkX) →
  Pre-trade filters:
    - Orderbook depth > $500 both legs
    - Resolution dates within 7 days
    - Spread > 5% after fees
    - LLM confidence HIGH
  Execution via Polymarket CLOB API

Cost: ~$3-5/month (verification calls only)
Output: Fully autonomous detection pipeline
```

### Phase 5: Continuous Improvement (Ongoing)

```
1. Track ALL classified relationships through market resolution
2. When markets resolve, compute ground truth: was the relationship valid?
3. Add confirmed relationships (positive AND negative) to training data
4. Retrain monthly: 30-60 minutes on cloud GPU, or re-submit to OpenAI fine-tuning
5. Track accuracy metrics over time:
   - True positive rate (correctly identified dependencies)
   - False positive rate (hallucinated dependencies)
   - Profitability per trade
6. Model improves over time -- compounding advantage vs. competitors using static prompts
```

---

## 8. Key Risk: The Sobering Reality of Combinatorial Arbitrage

### 8.1 The Numbers That Matter

From the IMDEA paper and Navnoor Bawa's analysis:

| Metric | Value | Implication |
|---|---|---|
| LLM-detected "dependent" pairs | 1,576 | LLM is over-confident about dependencies |
| Actually dependent after manual review | 13 | **97.3% false positive rate** |
| Generated profit out of 13 | 5 | **62% execution failure rate** |
| Combinatorial arb profits | $95,157 | 0.24% of total arb profits |
| Single-market rebalancing profits | $10.58M | **111x more profitable** |
| Total arb profits (all types) | $39.59M | Rebalancing dominates |

### 8.2 Failure Modes

| Failure Mode | Frequency | Mitigation |
|---|---|---|
| **LLM false positive** (hallucinated dependency) | Very High (97.3%) | Use state space enumeration (Approach B) for verification; require automated consistency checks to pass |
| **Liquidity asymmetry** | High | Check orderbook depth before executing; require >$500 available on both legs |
| **Non-atomic execution** (leg risk) | High | Execute harder-to-fill leg first; use aggressive limit orders; implement partial-fill unwinding |
| **Temporal mismatch** | Medium | Only trade pairs resolving within 7 days of each other |
| **Resolution ambiguity** | Medium | Read resolution criteria verbatim; reject if resolution sources differ; check Polymarket resolution docs |
| **Transaction cost compression** | Medium | Require spread >5% after Polymarket 2% fee + gas costs on Polygon |

### 8.3 The Honest Assessment

**Combinatorial arbitrage is intellectually fascinating but economically marginal compared to simpler strategies.**

The IMDEA data shows that single-market rebalancing (YES + NO != $1.00) generated **111x more profit** than combinatorial arbitrage. The LLM-based dependency detection had a 97.3% false positive rate before manual review.

**However**, there are reasons to still pursue this:

1. **The IMDEA study used a general-purpose LLM with no fine-tuning**. A fine-tuned model with domain-specific training data could dramatically reduce the false positive rate.

2. **They only analyzed one snapshot (Nov 5, 2024)**. Continuous monitoring would catch more opportunities.

3. **Their manual review bottleneck** (374 pairs reviewed by humans) would not exist in an automated system with better LLM accuracy.

4. **The Semantic Trading paper achieved profitability** at 60-70% accuracy, suggesting the approach works when integrated into a broader trading strategy (not just pure arbitrage).

5. **New markets create new relationships daily**. The opportunity set is constantly refreshed.

### 8.4 The Mitigation Strategy: Detect Broadly, Execute Conservatively

Use the LLM to find ALL plausible relationships (cast a wide net), but only trade those that pass every filter:

1. LLM classification confidence is HIGH
2. State space enumeration (Approach B) confirms dependency with valid JSON
3. All three automated consistency checks pass
4. Both legs have >$500 orderbook depth
5. Resolution dates within 7 days of each other
6. Resolution sources are identical or clearly nested
7. Spread exceeds 5% after all fees
8. No known ambiguity flags (check against IMDEA's Appendix E list of problematic market types)

If a pair passes all 8 filters, the false positive rate should drop from 97% to well under 10%.

---

## 9. Comparison: Three Approaches to LLM + Prediction Market Trading

| Dimension | IMDEA (AFT 2025) | Semantic Trading (Dec 2025) | Lead-Lag (Feb 2026) |
|---|---|---|---|
| **Goal** | Pure arbitrage (risk-free) | Relationship trading | Lead-lag trading |
| **LLM role** | State space enumeration | Clustering + relationship discovery | Semantic filtering of statistical pairs |
| **LLM model** | DeepSeek-R1-Distill-32B | Not specified | GPT-4-nano |
| **Platform** | Polymarket | Polymarket | Kalshi |
| **Accuracy** | 81.45% (single market) | 60-70% | N/A (measured via PnL) |
| **Returns** | $95K from 5 pairs | ~20% weekly | +205% PnL improvement |
| **Key innovation** | Joint state space enumeration | Agentic multi-step pipeline | Hybrid stat + semantic |
| **Biggest weakness** | 97.3% false positive rate | Low accuracy | Requires price history |
| **Best insight** | Verifiable structured output | 60-70% accuracy suffices | LLM as risk manager |

---

## 10. References

### Academic Papers
- [Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets (IMDEA, AFT 2025)](https://arxiv.org/abs/2508.03474)
- [Full IMDEA Paper HTML](https://arxiv.org/html/2508.03474v1)
- [Full IMDEA Paper PDF](https://suarez-tangil.networks.imdea.org/papers/2025aft-arbitrage.pdf)
- [Semantic Trading: Agentic AI for Clustering and Relationship Discovery (Columbia/IBM, Dec 2025)](https://arxiv.org/abs/2512.02436)
- [LLM as a Risk Manager: Semantic Filtering for Lead-Lag Trading (Feb 2026)](https://arxiv.org/abs/2602.07048)
- [Semantic Non-Fungibility and Violations of the Law of One Price](https://arxiv.org/html/2601.01706)

### Analysis & Commentary
- [Combinatorial Arbitrage: Why 62% of LLM-Detected Dependencies Fail (Navnoor Bawa)](https://medium.com/@navnoorbawa/combinatorial-arbitrage-in-prediction-markets-why-62-of-llm-detected-dependencies-fail-to-26f614804e8d)
- [Prediction Market Arbitrage: How Quants Extracted $40M (Navnoor Bawa)](https://navnoorbawa.substack.com/p/prediction-market-arbitrage-how-quants)
- [Building a Prediction Market Arbitrage Bot: Technical Implementation](https://navnoorbawa.substack.com/p/building-a-prediction-market-arbitrage)
- [Flashbots: Arbitrage in Prediction Markets - Strategies, Impact and Open Questions](https://collective.flashbots.net/t/arbitrage-in-prediction-markets-strategies-impact-and-open-questions/5198)

### Fine-Tuning Resources
- [Fine-Tuning Llama 3 with LoRA: Step-by-Step Guide (Neptune.ai)](https://neptune.ai/blog/fine-tuning-llama-3-with-lora)
- [Fine-Tuning GPT-4o-mini: Step-by-Step Guide (DataCamp)](https://www.datacamp.com/tutorial/fine-tuning-gpt-4o-mini)
- [LLaMA-Factory CPU-Only LoRA Fine-Tuning Guide](https://medium.com/@contact_30070/step-by-step-guide-for-fine-tuning-your-llm-with-llama-factory-using-the-cpu-only-96b2fc6a80b0)
- [LoRA Fine-Tuning LLMs for Text Classification (SUSE)](https://www.suse.com/c/lora-fine-tuning-llms-for-text-classification/)
- [LLaMA-Factory GitHub (Unified Fine-Tuning of 100+ LLMs)](https://github.com/hiyouga/LlamaFactory)
- [Hugging Face PEFT Library (LoRA Implementation)](https://huggingface.co/docs/peft)
- [Llama.cpp (Local GGUF Inference)](https://github.com/ggml-org/llama.cpp)

### Model Pricing (as of Feb 2026)
- [OpenAI API Pricing](https://openai.com/api/pricing/) -- GPT-4o: $2.50/$10.00/M; GPT-4o-mini: $0.15/$0.60/M
- [Anthropic Claude Pricing](https://platform.claude.com/docs/en/about-claude/pricing) -- Haiku 4.5: $1/$5/M; Sonnet 4.5: $3/$15/M
- [DeepSeek API Pricing](https://api-docs.deepseek.com/quick_start/pricing) -- R1-Distill: $0.12/$0.20/M; 75% off-peak discount
- [DeepInfra Pricing](https://deepinfra.com/pricing) -- DeepSeek-R1-Distill-32B: ~$0.36/M blended

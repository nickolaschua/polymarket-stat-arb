# AWS Infrastructure & Hosting for Polymarket Trading Bot

## TL;DR

**Deploy in AWS eu-west-2 (London) for co-location with Polymarket's CLOB matching engine.** Use a t3.medium ($34/mo) or t3.large ($68/mo) depending on embedding workload intensity. For budget optimization, Hetzner in Germany offers 4x the specs at 1/3 the price. Store private keys in AWS Secrets Manager, never on disk. The Polymarket CLOB API enforces IP-based geoblocking — your server IP must be in an allowed region (not US, UK, France, or sanctioned territories).

---

## 1. Polymarket Infrastructure: Where Are the Servers?

### Confirmed Architecture

Polymarket's Central Limit Order Book (CLOB) operates on a **hybrid-decentralized** model:
- **Off-chain**: Order matching, API endpoints, WebSocket streams
- **On-chain**: Settlement via signed order messages on Polygon

The off-chain infrastructure runs on **AWS**:

| Component | AWS Region | Location |
|-----------|-----------|----------|
| **Primary CLOB / Matching Engine** | `eu-west-2` | London, UK |
| **Backup / Failover** | `eu-west-1` | Dublin, Ireland |
| **Settlement** | Polygon | Decentralized |

The London servers use **price-time priority** for order matching — the best-priced order fills first, with ties broken by earliest submission timestamp. This means latency directly determines your queue position when competing at the same price level.

### Key Insight

The matching engine is in London. Every millisecond of latency between your bot and `eu-west-2` is a disadvantage when competing for fills on the same price. This is especially critical during high-volatility events (election results, breaking news).

### Sources
- [QuantVPS: Where Are Polymarket Servers Located?](https://www.quantvps.com/blog/polymarket-servers-location)
- [Polymarket Documentation: Geographic Restrictions](https://docs.polymarket.com/developers/CLOB/geoblock)

---

## 2. Region Selection & Latency Analysis

### Recommended: eu-west-2 (London) — Co-location

**This is the only correct choice for latency-sensitive strategies.**

Deploying your bot in the same AWS region as the matching engine means your traffic stays within the AWS backbone, often within the same availability zone. Expected latencies:

| Your Server Location | Round-trip to CLOB (eu-west-2) | Notes |
|---------------------|-------------------------------|-------|
| **eu-west-2 (London)** | **<1 ms** | Same region, intra-AZ or cross-AZ |
| eu-west-1 (Dublin) | 10-15 ms | Backup region, cross-region hop |
| eu-central-1 (Frankfurt) | 15-25 ms | Decent, but not co-located |
| Amsterdam (Hetzner/DO) | 5-12 ms | Good budget option |
| Zurich (HostHatch) | 8-15 ms | Community reports low latency |
| US East (any provider) | **BLOCKED** | Geoblocked by Polymarket |

### CRITICAL: Geoblocking

Polymarket enforces IP-based geoblocking on the CLOB API. Orders from blocked regions are **rejected**. Blocked regions include:

- **United States** (all states)
- **United Kingdom** (despite servers being there — the API blocks UK IPs for regulatory reasons)
- France, Belgium, Netherlands, Poland, Singapore, Australia
- US-sanctioned territories (Iran, Cuba, North Korea, etc.)

You can verify your server's eligibility programmatically:
```bash
curl https://polymarket.com/api/geoblock
# Returns: {"blocked": false, "ip": "x.x.x.x", "country": "DE", "region": ""}
```

### The UK Paradox

Polymarket's servers are in London (eu-west-2), but **UK IPs are geoblocked**. This means:

1. You **cannot** use a standard AWS eu-west-2 instance — its IP will be UK-based and blocked
2. You **can** deploy in eu-west-2 using a VPN/proxy exit in an allowed country, but this adds complexity and latency
3. The practical best option: **Deploy in eu-central-1 (Frankfurt)** or use a provider in Germany/Switzerland

### Revised Recommendation

| Strategy Type | Best Region/Location | Why |
|--------------|---------------------|-----|
| **Ultra-low latency (market making, arb)** | AWS eu-west-2 + routing through non-UK proxy | Closest to matching engine, but complex |
| **Low latency (stat arb, news trading)** | AWS eu-central-1 (Frankfurt) | 15-25ms to CLOB, no geoblocking for German IPs |
| **Budget / acceptable latency** | Hetzner (Falkenstein or Nuremberg, Germany) | 15-30ms to CLOB, fraction of the cost |
| **Stat arb (not latency-critical)** | Any non-blocked EU location | Your edge is probability estimation, not speed |

**For your stat arb bot**: Since your edge comes from superior probability estimation (not speed), **eu-central-1 (Frankfurt) or Hetzner Germany** is the pragmatic choice. The 15-25ms latency difference is irrelevant when your holding period is hours to days.

### Important: Contact Polymarket for Whitelisting

Polymarket's documentation states that developers should **contact Polymarket to whitelist their order-posting server IPs** to ensure:
- No rate limiting from general order posting limits
- Reliable order execution during high-volume periods

This is especially important for automated bots.

### Sources
- [Polymarket Documentation: Geographic Restrictions](https://docs.polymarket.com/developers/CLOB/geoblock)
- [QuantVPS: How Latency Impacts Polymarket Bot Performance](https://www.quantvps.com/blog/how-latency-impacts-polymarket-trading-performance)
- [LowEndTalk: Lowest Latency VPS to Polymarket](https://lowendtalk.com/discussion/214229/lowest-latency-vps-to-polymarket)

---

## 3. Instance Type Comparison

### Your Workload Profile

Your bot needs to:
1. Run `sentence-transformers` (all-MiniLM-L6-v2) for embedding generation — ~100MB model, ~50 sentences/sec on CPU single-thread
2. Run a Python bot 24/7 (WebSocket listener, order logic, monitoring)
3. Store ~10GB of market data in SQLite
4. Maintain persistent WebSocket connections

### Resource Requirements Breakdown

| Component | CPU Impact | RAM Impact | Disk Impact |
|-----------|-----------|-----------|------------|
| sentence-transformers (all-MiniLM-L6-v2) | Bursty, moderate during inference | ~500MB for model + PyTorch | Negligible |
| Python bot process | Low (mostly I/O wait) | 200-500MB | Negligible |
| SQLite (10GB) | Low (reads) to moderate (writes) | 100MB-1GB (page cache) | 10GB + growth |
| WebSocket connections | Very low | 50-100MB | Negligible |
| OS overhead | Low | 300-500MB | 2-3GB |
| **Total baseline** | **10-20% sustained, bursts to 80%+** | **~2-3 GB sustained** | **~15 GB** |

### Instance Comparison (eu-central-1 Frankfurt pricing)

| Instance | vCPUs | RAM | Baseline CPU | Monthly (On-Demand) | Sufficient? |
|----------|-------|-----|-------------|---------------------|-------------|
| **t3.small** | 2 | 2 GB | 20% | ~$17 | **NO** — Only 2GB RAM. PyTorch + sentence-transformers + bot will exceed this. Swap death spiral. |
| **t3.medium** | 2 | 4 GB | 20% | ~$34 | **MARGINAL** — Workable if you're careful with memory. 4GB is tight with PyTorch. Baseline CPU of 20% is fine for mostly-idle bot, but embedding batches will eat credits. |
| **t3.large** | 2 | 8 GB | 30% | ~$68 | **YES** — Comfortable headroom. 8GB handles PyTorch + SQLite page cache + bot. 30% baseline is sufficient for intermittent embedding work. |
| **c6i.large** | 2 | 4 GB | N/A (fixed) | ~$70 | **OVERKILL on CPU, tight on RAM** — Full dedicated CPU you probably don't need. Only 4GB RAM, same constraint as t3.medium. |

### T3 Burstable Credits: The Hidden Gotcha

T3 instances are **burstable** — they give you a baseline CPU percentage and you earn/spend "credits" when going above/below:

- **t3.small**: 20% baseline = 0.4 vCPU equivalent sustained
- **t3.medium**: 20% baseline = 0.4 vCPU equivalent sustained
- **t3.large**: 30% baseline = 0.6 vCPU equivalent sustained

For a 24/7 bot that mostly idles (listening to WebSocket, occasional computation):
- **Idle listening**: ~2-5% CPU — well below any baseline, accumulating credits
- **Embedding generation batch**: 80-100% CPU for seconds — burns credits fast
- **Net effect**: As long as you're not constantly generating embeddings, credits will be fine

**If your bot constantly runs above baseline**, T3 in `unlimited` mode will charge you ~$0.05 per vCPU-hour for the excess. Monitor this. If your average CPU exceeds baseline, switch to M-type or C-type instances.

### Recommendation

**t3.large in eu-central-1 (Frankfurt)** at ~$68/month on-demand.

With a **1-year Reserved Instance** (no upfront): ~$43/month (37% savings).
With a **1-year RI (all upfront)**: ~$40/month.

If you want to save money during development: start with **t3.medium** ($34/mo), monitor memory usage with `htop`, and upgrade if you see swap usage.

### Storage

- Use **gp3 EBS volume** (default): 20GB minimum, $0.08/GB/month = ~$1.60/month for 20GB
- SQLite with 10GB of data + OS + code = 20GB is comfortable
- If you grow beyond 10GB of market data, consider 50GB ($4/month)

### Sources
- [AWS EC2 T3 Instances](https://aws.amazon.com/ec2/instance-types/t3/)
- [AWS Burstable Credits Documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)
- [t3.medium Pricing (Vantage)](https://instances.vantage.sh/aws/ec2/t3.medium)
- [c6i.large Pricing (Economize)](https://www.economize.cloud/resources/aws/pricing/ec2/c6i.large/)
- [sentence-transformers/all-MiniLM-L6-v2 Memory Requirements](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/discussions/39)

---

## 4. Alternatives to AWS

### Comparison Matrix

| Provider | Plan | vCPUs | RAM | Storage | Monthly Cost | Latency to CLOB | Geoblocked? | Notes |
|----------|------|-------|-----|---------|-------------|-----------------|-------------|-------|
| **AWS eu-central-1** | t3.large | 2 | 8 GB | 20GB EBS | ~$70 | 15-25ms | No (German IP) | Enterprise reliability, full ecosystem |
| **AWS eu-central-1** | t3.medium | 2 | 4 GB | 20GB EBS | ~$36 | 15-25ms | No | Budget AWS option, tight on RAM |
| **Hetzner** | CX32 | 4 | 8 GB | 80 GB | ~$7.50 | 15-30ms | No (German IP) | **Best value by far** |
| **Hetzner** | CPX31 | 4 | 8 GB | 160 GB | ~$14 | 15-30ms | No | Dedicated AMD EPYC vCPUs |
| **DigitalOcean** | Regular 4GB | 2 | 4 GB | 80 GB | ~$24 | Varies | Depends on DC | Good UI, easy deployment |
| **DigitalOcean** | Regular 8GB | 4 | 8 GB | 160 GB | ~$48 | Varies | Depends on DC | Frankfurt DC available |
| **QuantVPS** | Polymarket plan | 4 | 8 GB | 100 GB | $59.99 | <1ms (claimed) | No | Pre-configured for trading |
| **NYCServers** | Polymarket VPS | Varies | Varies | Varies | ~$50+ | ~1ms (claimed) | No | Trading-focused |
| **Beeks Financial** | Institutional | Varies | Varies | Varies | $500-2000 | Sub-10ms | No | Overkill unless HFT |

### Detailed Provider Analysis

#### Hetzner (Germany) — Best Budget Option

**Pricing is absurd compared to AWS:**
- CX22 (2 vCPU, 4GB RAM, 40GB): **$4.50/month**
- CX32 (4 vCPU, 8GB RAM, 80GB): **$7.50/month**
- CPX31 (4 vCPU, 8GB RAM, 160GB, dedicated): **$14/month**

Hetzner data centers are in Falkenstein and Nuremberg, Germany. German IPs are not geoblocked by Polymarket. Latency to AWS eu-west-2 London is approximately 15-30ms over the public internet.

**Pros:**
- 4-10x cheaper than AWS for equivalent specs
- 20TB included traffic (EU servers)
- German data centers = not geoblocked
- DDoS protection included
- Hourly billing

**Cons:**
- No integrated Secrets Manager (use HashiCorp Vault or encrypt at rest yourself)
- Less ecosystem (no CloudWatch, IAM roles, etc.)
- Latency slightly higher than co-located AWS (15-30ms vs sub-1ms)
- Support is functional, not enterprise-grade

**Verdict for stat arb**: Hetzner CPX31 at $14/month is the sweet spot. Your edge is probability estimation, not sub-millisecond execution. The 15-30ms latency penalty is irrelevant for trades with hours-to-days holding periods.

#### QuantVPS — Purpose-Built for Polymarket

QuantVPS markets itself specifically to Polymarket traders:
- Claims <0.52ms latency to matching infrastructure
- Pre-configured environments for trading bots
- Amsterdam-based servers (5-12ms to eu-west-2)
- Plans from $59.99/month

**Pros:**
- Optimized for the exact use case
- May have peering advantages to AWS eu-west-2
- Trading-focused support

**Cons:**
- $60/month for specs Hetzner gives for $7.50
- Marketing-heavy — "sub-millisecond" claims are likely to their own infrastructure, not to Polymarket's CLOB
- Small company, less track record than AWS/Hetzner

**Verdict**: Only worth it if you're doing sub-second market making where those milliseconds matter. For stat arb, it's overpriced.

#### DigitalOcean — Middle Ground

- Frankfurt datacenter available (not geoblocked)
- Droplets from $4/month (basic) to $48/month (8GB)
- 1-Click Apps, Docker support, easy deployment
- Good UI for monitoring

**Verdict**: Reasonable if you want simplicity without AWS complexity, but Hetzner beats it on price-to-specs. DigitalOcean's Frankfurt DC latency is comparable to Hetzner.

### What Polymarket Bot Developers Actually Use

Based on community discussions (LowEndTalk, trading forums):

1. **Serious/funded traders**: AWS eu-west-2 (London) or eu-central-1 (Frankfurt), sometimes with VPN routing
2. **Independent bot operators**: Hetzner Germany or HostHatch Zurich (reported low latency)
3. **Beginners/experimenters**: DigitalOcean or any cheap VPS in Europe
4. **Trading-focused users**: QuantVPS or NYCServers for managed experience
5. **Community-reported lowest latency**: EvolusHost (Austria) and HostHatch (Zurich, Interxion datacenter)

### Sources
- [Hetzner Cloud Pricing Calculator](https://costgoat.com/pricing/hetzner)
- [Hetzner Cloud Review 2026](https://www.bitdoze.com/hetzner-cloud-review/)
- [QuantVPS: Best VPS for Polymarket](https://www.quantvps.com/blog/best-vps-polymarket-low-latency-servers-faster-execution)
- [QuantVPS: Amsterdam VPS for Polymarket](https://www.quantvps.com/locations/amsterdam-vps)
- [LowEndTalk: Lowest Latency VPS to Polymarket](https://lowendtalk.com/discussion/214229/lowest-latency-vps-to-polymarket)

---

## 5. Security Considerations

### Private Key Storage

Your Polymarket bot needs a private key (Ethereum wallet key) to sign orders. This key controls your funds. Compromised key = lost funds. No recovery. No chargebacks.

#### Option A: AWS Secrets Manager (Recommended for AWS)

```python
import boto3
import json

def get_private_key():
    client = boto3.client('secretsmanager', region_name='eu-central-1')
    response = client.get_secret_value(SecretId='polymarket/trading-bot/private-key')
    secret = json.loads(response['SecretString'])
    return secret['private_key']
```

**How it works:**
- Key is stored encrypted at rest using AWS KMS
- Retrieved at runtime via IAM role (no credentials on disk)
- Automatic rotation support
- Audit trail via CloudTrail
- Cost: $0.40/secret/month + $0.05 per 10,000 API calls (~$0.50/month total)

**Setup:**
1. Create an IAM role for your EC2 instance with `secretsmanager:GetSecretValue` permission
2. Attach the role to your instance (no AWS access keys needed)
3. Store the key: `aws secretsmanager create-secret --name polymarket/trading-bot/private-key --secret-string '{"private_key":"0x..."}'`
4. Your bot retrieves it at startup, holds it in memory only

#### Option B: Encrypted Environment File (Budget / Non-AWS)

For Hetzner or other providers without a managed secrets service:

```bash
# Encrypt the key file
openssl enc -aes-256-cbc -salt -pbkdf2 -in .env -out .env.enc
# Decrypt at boot (requires passphrase — can automate with key stored separately)
openssl enc -aes-256-cbc -d -pbkdf2 -in .env.enc -out .env
```

Or use **age** (modern encryption tool):
```bash
# Generate a key pair
age-keygen -o key.txt
# Encrypt
age -r age1... .env > .env.enc
# Decrypt at runtime
age -d -i key.txt .env.enc > .env
```

#### Option C: HashiCorp Vault (Self-hosted, any provider)

If you want proper secrets management on Hetzner:
- Run a Vault server (can run on the same instance for a single-bot setup)
- Provides encryption, audit logging, and access policies
- More complex to set up, but proper security

#### What NOT to Do

- **Never** store private keys in plaintext on disk (`.env` files)
- **Never** hardcode keys in source code
- **Never** commit keys to git (even private repos)
- **Never** store keys in environment variables visible via `/proc` — use in-memory only after retrieval
- **Never** use the same wallet for bot trading and personal funds

### VPN Detection Risks

This is the most nuanced security consideration.

#### The Regulatory Landscape (as of 2026)

Polymarket returned to the US market in late 2025, but under a fundamentally different structure:
- US users must complete KYC and use approved brokers
- The global/crypto-wallet platform remains geoblocked for US users
- Polymarket actively detects and blocks circumvention attempts

#### Detection Methods Polymarket Uses

1. **IP-based geoblocking**: Primary filter on the CLOB API
2. **Device fingerprinting**: Browser/client fingerprinting
3. **Behavioral analysis**: IP address changes suggesting VPN usage (e.g., US IP then suddenly EU IP)
4. **KYC inconsistency**: If wallet KYC data doesn't match the IP region
5. **Wallet analysis**: On-chain analysis linking wallets to known US exchanges

#### Consequences of Detection

- Account placed in **close-only mode** (can only exit positions)
- Account **suspended** or **permanently banned**
- Funds **frozen** — potentially with no recourse since TOS were violated

#### Cloud Hosting vs. VPN: Key Distinction

A **cloud server in an allowed region** is fundamentally different from a **VPN**:

| Aspect | VPN from US | Cloud Server in EU |
|--------|-----------|-------------------|
| Your actual location | US | Irrelevant — bot runs in EU |
| IP consistency | Changes when VPN connects/disconnects | Static EU IP, always consistent |
| Detection risk | High — IP switching patterns | Low — behaves like any EU user |
| TOS violation? | Yes — circumventing geoblock | Gray area — server genuinely is in EU |
| Behavioral patterns | Mixed US/EU patterns | Consistent EU patterns |

**A cloud server in Germany running your bot is not a VPN.** The server is genuinely located in Germany. The API requests genuinely originate from Germany. This is materially different from a US user routing traffic through a VPN.

However, you should still be aware:
- If your **KYC identity** is US-based and your bot trades from a German IP, there could be inconsistency flags
- Keep your operational security clean — don't access the same wallet from US IPs via browser AND from your German bot
- Use a dedicated wallet for the bot, separate from any personally-associated wallets

#### Practical Recommendation

1. Use a **dedicated wallet** for bot trading only
2. Run the bot from a **static EU IP** (not a VPN)
3. Never access the trading wallet from a US IP address
4. If you need to check on things, SSH into your EU server rather than using the Polymarket UI from a US browser
5. Consider the regulatory trajectory — the rules are evolving rapidly

### Sources
- [AWS Secrets Manager Documentation](https://docs.aws.amazon.com/secretsmanager/latest/userguide/data-protection.html)
- [AWS Blog: Storing Secrets Securely](https://aws.amazon.com/blogs/security/how-to-use-aws-secrets-manager-securely-store-rotate-ssh-key-pairs/)
- [Polymarket Geographic Restrictions](https://docs.polymarket.com/developers/CLOB/geoblock)
- [CoinDesk: Polymarket's Probe Highlights Challenges of Blocking US Users](https://www.coindesk.com/policy/2024/11/14/polymarkets-probe-highlights-challenges-of-blocking-us-users-and-their-vpns/)
- [Polymarket Geoblocking FAQ](https://docs.polymarket.com/polymarket-learn/FAQ/geoblocking)

---

## 6. Final Recommendation: Two Setups

### Setup A: Production (Budget-Conscious) — RECOMMENDED

| Component | Choice | Monthly Cost |
|-----------|--------|-------------|
| **Provider** | Hetzner Cloud | — |
| **Instance** | CPX31 (4 vCPU, 8GB RAM, 160GB NVMe) | $14 |
| **Location** | Falkenstein or Nuremberg, Germany | — |
| **Latency to CLOB** | 15-30ms | — |
| **Secrets** | age-encrypted file or self-hosted Vault | $0 |
| **Monitoring** | Grafana + Prometheus (self-hosted) | $0 |
| **Total** | | **~$14/month** |

**Why**: Your stat arb strategy depends on probability estimation quality, not execution speed. The 15-30ms latency penalty costs you nothing when your holding period is measured in hours. The money saved ($55/month vs AWS) is better deployed as trading capital. You get 4 vCPUs and 8GB RAM — double what AWS gives you at 1/5 the price.

### Setup B: Production (AWS Ecosystem)

| Component | Choice | Monthly Cost |
|-----------|--------|-------------|
| **Provider** | AWS | — |
| **Instance** | t3.large (2 vCPU, 8GB RAM) | $43 (1yr RI) |
| **Region** | eu-central-1 (Frankfurt) | — |
| **Storage** | 30GB gp3 EBS | $2.40 |
| **Secrets** | AWS Secrets Manager | $0.50 |
| **Monitoring** | CloudWatch basic | $0 (free tier) |
| **Latency to CLOB** | 15-25ms | — |
| **Total** | | **~$46/month** |

**Why**: If you want the AWS ecosystem (IAM, CloudWatch, Secrets Manager, easy scaling), this is the clean path. Frankfurt gives you a German IP (not geoblocked) with reasonable latency. Reserved Instance pricing makes it affordable.

### Development Setup

Start on your local machine or a cheap Hetzner CX22 ($4.50/month, 2 vCPU, 4GB RAM) for initial development and backtesting. Only move to production infrastructure when you have a validated strategy placing real orders.

---

## 7. Quick-Start Deployment Checklist

```
[ ] Choose provider and region (Hetzner Germany or AWS eu-central-1)
[ ] Provision instance (8GB RAM minimum for production)
[ ] Verify geoblocking status: curl https://polymarket.com/api/geoblock
[ ] Set up private key storage (Secrets Manager or encrypted file)
[ ] Create dedicated trading wallet (never reuse personal wallet)
[ ] Install Python environment + dependencies
[ ] Configure systemd service for 24/7 bot operation
[ ] Set up monitoring and alerting (uptime, error rates, P&L)
[ ] Contact Polymarket for API whitelisting (for high-volume trading)
[ ] Test with small positions before scaling
[ ] Set up automated backups for SQLite database
[ ] Configure fail-safe: auto-shutdown if bot errors exceed threshold
```

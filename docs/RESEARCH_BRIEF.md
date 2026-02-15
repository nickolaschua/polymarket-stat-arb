# Polymarket Research Brief

## Purpose

This document lists every Polymarket-specific detail that needs to be researched and verified from **primary sources** (official Polymarket docs, GitHub repos, on-chain data). The output should be a single comprehensive MD file that serves as the ground truth for our bot implementation.

**Primary sources to check:**
- https://docs.polymarket.com (official developer docs)
- https://github.com/Polymarket/py-clob-client (Python client — README, source code, issues)
- https://github.com/Polymarket/clob-client (TypeScript client — often has more up-to-date docs)
- https://github.com/Polymarket/rs-clob-client (Rust client — heartbeat implementation details)
- https://github.com/Polymarket/agents (official AI trading agent framework)
- https://github.com/Polymarket/poly-market-maker (official market maker bot)
- Polymarket GitHub issues (especially py-clob-client issues for known bugs/limitations)
- Polygonscan contract pages for on-chain verification of addresses

---

## Section 1: Rate Limits (CRITICAL — verify exact numbers)

Our retry module uses these numbers but they came from docs that may be outdated.

**Questions to answer:**
1. What are the exact rate limits for the Gamma API (`gamma-api.polymarket.com`)? Per-IP? Per-minute/hour?
2. What are the exact rate limits for CLOB public endpoints (`clob.polymarket.com` — /book, /midpoint, /price, etc.)?
3. What are the exact rate limits for CLOB authenticated/trading endpoints (/order, /cancel, etc.)?
4. Is rate limiting done via Cloudflare? What happens when you hit the limit — 429 response? Throttling/queuing? Temporary IP ban?
5. Is there a `Retry-After` header in 429 responses? What format (seconds? datetime?)?
6. Are there different limits for burst vs sustained traffic?
7. Are WebSocket connections rate-limited differently than REST?
8. What is the official docs URL for rate limits? (We reference `https://docs.polymarket.com/quickstart/introduction/rate-limits` — is this still valid?)

**What we currently assume:**
- Gamma API: ~1,000 req/hour
- CLOB trading: ~60 orders/min
- CLOB read: ~3,000 req/10 min
- Enforcement: Cloudflare throttling, then 429

---

## Section 2: Historical Data & Resolved Markets

Our training data pipeline depends on being able to fetch resolved market data. Need to verify what actually works.

**Questions to answer:**
1. Does `GET /markets?closed=true` on the Gamma API actually return resolved markets? What fields are populated vs null?
2. Is there an explicit "resolution outcome" field (e.g., `resolution: "Yes"`)? Or must we infer from final prices?
3. For resolved markets, what does the `outcomePrices` field show — the final settlement prices (0.00/1.00) or the last traded prices?
4. Does `GET /prices-history` still return empty data for resolved markets at fidelity < 720 (12 hours)? (GitHub issue #216) Has this been fixed?
5. Does `GET /trades?market={condition_id}` work for resolved/closed markets? How far back does trade data go?
6. Is there a `GET /prices-history` endpoint that works with `interval=max` for resolved markets?
7. Are there any **new** historical data endpoints not covered in the current docs (data-api.polymarket.com, subgraph, etc.)?
8. What is the maximum `limit` value for Gamma API pagination? (We use 100 — is higher possible?)
9. How many total resolved markets exist on Polymarket approximately?
10. Is there a bulk export or data dump available anywhere (official or community)?

---

## Section 3: CLOB API Endpoints — Complete & Current

Need to verify the full endpoint list and any additions since our docs were written.

**Questions to answer:**
1. Full list of public (no auth) REST endpoints with current URL patterns and parameters
2. Full list of authenticated (L2) REST endpoints
3. Are there any new endpoints added in 2025-2026 not in our current reference?
4. `GET /tick-size` — what does this return exactly? How does tick size vary by market?
5. `GET /spread` — response format?
6. `GET /last-trade-price` — response format?
7. Batch order endpoint — what is the current max batch size? (We have "15" — is this still correct?)
8. `DELETE /cancel-market-orders` — does this take a condition_id or market_id?
9. `GET /rewards/*` endpoints — are these still active? What do they return?
10. Is there a `GET /positions` or similar endpoint to check current holdings?

---

## Section 4: Order Types & Precision

Need exact precision rules to avoid order rejections.

**Questions to answer:**
1. What are the exact precision requirements for GTC orders? (price decimals, size decimals)
2. What are the exact precision requirements for FOK orders?
3. How does tick size affect order pricing? (e.g., if tick size is 0.01, can you place at 0.555?)
4. What is the minimum order size in USD?
5. What is the maximum order size?
6. `post_only` flag — exact behavior? Does it return an error or silently cancel if it would take?
7. GTD orders — what format is the expiration? Unix timestamp? Is there a minimum/maximum?
8. Nonce handling — when is a nonce required? Auto-generated by py-clob-client?
9. What does the order response look like on success? On failure?
10. What are the possible order status values? (open, filled, partially_filled, cancelled, expired, etc.)

---

## Section 5: WebSocket

Need exact subscription format and behavior for the real-time data pipeline.

**Questions to answer:**
1. Market channel (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) — exact subscription message format
2. What are all possible event types on the market channel? (`book`, `price_change`, `last_trade_price`, `trade` — any others?)
3. What does each event type's payload look like? (exact JSON schema)
4. User channel — subscription format with authentication
5. What events come on the user channel? Order fills, cancellations, position updates?
6. Ping/pong behavior — does the server send pings? What's the timeout before disconnect?
7. Reconnection behavior — does the server drop connections periodically? Any auth token refresh needed?
8. Can you subscribe to multiple markets on one connection? How?
9. `wss://ws-live-data.polymarket.com` — is this a separate service? What does it provide vs the CLOB WebSocket?
10. Max number of simultaneous WebSocket connections per IP/API key?

---

## Section 6: Authentication

Need to verify the auth flow hasn't changed.

**Questions to answer:**
1. Is the two-level auth (L1 private key → L2 API key) still the current model?
2. `create_or_derive_api_creds()` — does this create new creds each time or deterministically derive from the private key?
3. Do API credentials expire? If so, after how long?
4. What are the exact headers required for authenticated requests? (`POLY_API_KEY`, `POLY_TIMESTAMP`, `POLY_SIGNATURE`, `POLY_PASSPHRASE`, `POLY_NONCE` — all still current?)
5. What signature algorithm is used? (HMAC-SHA256 — still correct?)
6. Signature type 0 (EOA) vs 1 (proxy/Magic) — any changes?
7. Is there a `funder` address required for EOA wallets or only for proxy wallets?
8. Any new authentication methods or changes in recent py-clob-client versions?

---

## Section 7: Heartbeat System

Already well-researched but worth a quick verify.

**Questions to answer:**
1. Is the 10-second heartbeat interval still the requirement?
2. Does `post_heartbeat(heartbeat_id)` still accept a string session ID?
3. What does the heartbeat response look like?
4. Is there a way to check heartbeat status without sending one?
5. Scope of cancellation — is it ALL orders for the account, or just orders placed during that heartbeat session?
6. Can you have multiple heartbeat sessions for the same account?

---

## Section 8: Contract Addresses & Token Approvals

These are in our wallet onboarding doc. Wrong addresses = approving the wrong contracts.

**Questions to answer (verify on Polygonscan):**
1. USDC.e (bridged USDC on Polygon): `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` — still the token Polymarket uses?
2. Has Polymarket migrated to native USDC (`0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359`)? Any announcements?
3. Conditional Tokens Framework: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` — still correct?
4. CTF Exchange: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` — still the active exchange?
5. Neg Risk CTF Exchange: `0xC5d563A36AE78145C45a50134d48A1215220f80a` — still correct?
6. Neg Risk Adapter: `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` — still correct?
7. Are there any NEW contracts that need approval (e.g., a v2 exchange)?
8. Is `max uint256` approval still the recommended approach, or has Polymarket moved to exact approvals?
9. What is the actual number of approvals needed? (We say 6: 2 tokens × 3 contracts)
10. Does `py-clob-client`'s `update_balance_allowance()` handle all approvals, or only some?

---

## Section 9: Negative Risk (NegRisk) Events

Critical for combinatorial arbitrage strategy.

**Questions to answer:**
1. How exactly do negRisk events work? What makes them different from regular events?
2. What is the Neg Risk Adapter's role in execution?
3. For a negRisk event with N outcomes, how many conditional tokens exist?
4. When buying YES on one outcome in a negRisk event, what happens to collateral efficiency?
5. Can you buy YES on multiple outcomes in the same negRisk event simultaneously? Is collateral shared?
6. What are `negRiskFeeBips`? How are fees calculated for negRisk trades?
7. How is settlement handled for negRisk events vs regular events?
8. Can you construct a "buy all outcomes" position in a negRisk event? What does it cost? (Should be exactly $1.00 minus fees)
9. How do you identify which markets belong to the same negRisk group? (`negRiskMarketID` field?)
10. Any edge cases or gotchas with negRisk trading?

---

## Section 10: Fees

Need accurate fee model for P&L calculations.

**Questions to answer:**
1. What is the standard trading fee on Polymarket? (Is it 0%? Maker/taker split?)
2. Are there reward/rebate programs for market makers? How do they work?
3. What are the negRisk-specific fees (`negRiskFeeBips`)?
4. Are there different fee tiers based on volume?
5. Gas costs — what does the bot actually pay gas for? (Only approvals? Or also order settlement?)
6. Is order signing free (off-chain)? Is order submission free?
7. What about redemption fees when a market resolves?
8. `fee_rate_bps` parameter in `OrderArgs` — what values are valid? Default?

---

## Section 11: Geoblocking & Compliance

**Questions to answer:**
1. Current list of blocked countries/regions
2. API endpoint to check block status: `curl https://polymarket.com/api/geoblock` — still works? Response format?
3. Is blocking at the API level (CLOB rejects requests from blocked IPs) or just the frontend?
4. Does the Gamma API (read-only) have the same geoblocking as the CLOB (trading)?
5. Any known VPN/proxy detection?
6. Is there a Terms of Service page with the current restricted jurisdictions list?

---

## Section 12: py-clob-client Library

**Questions to answer:**
1. Current latest version number
2. Any breaking changes in recent versions?
3. Known open issues that affect our use case (check GitHub issues)
4. Does it support async natively, or is everything synchronous? (We wrap with `run_in_executor`)
5. `BalanceAllowanceParams` and `AssetType` — still the correct types for checking/setting approvals?
6. `OpenOrderParams` — what filter fields are available?
7. `TradeParams` — what filter fields are available?
8. Is there a method to get current positions/balances?
9. Any undocumented methods or features discovered in source code?
10. Compatibility with Python 3.11/3.12/3.13?

---

## Output Format

Please produce a single markdown file (`docs/POLYMARKET_VERIFIED_REFERENCE.md`) structured by the sections above, with:
- Each answer clearly labeled
- Source URL for each piece of information
- "UNVERIFIED" tag on anything that couldn't be confirmed from primary sources
- "CHANGED" tag on anything that differs from our current docs
- "NEW" tag on any information not in our current docs at all
- Date of research at the top of the file

# External Integrations

**Analysis Date:** 2026-02-16

## APIs & External Services

**Polymarket Gamma API (Market Discovery):**
- Purpose: Fetch events, markets, prices, metadata
- Base URL: `gamma-api.polymarket.com` (`src/config.py`, `src/utils/client.py`)
- Auth: None required (public read-only)
- Rate limit: 300 req/10s (bot uses 200/10s = 70% safety margin) (`src/utils/retry.py`)
- Endpoints used: `/events` with pagination (`src/utils/client.py`)
- Returns stringified JSON arrays for prices/tokens (requires `json.loads()` parsing)

**Polymarket CLOB API (Trading):**
- Purpose: Orderbooks, order placement, positions, heartbeat
- Base URL: `clob.polymarket.com` (`src/config.py`, `src/utils/client.py`)
- Auth: L2 signature derived from wallet private key
- Rate limit: 1500 req/10s read, 60 req/s trade (bot uses 70% margins) (`src/utils/retry.py`)
- SDK: py-clob-client >=0.18.0 (official Polymarket Python client)
- Key requirement: Heartbeat every 10s or all orders cancel (`src/utils/heartbeat.py`)

**Polymarket Data API (Analytics):**
- Purpose: Historical positions, analytics
- Base URL: `data-api.polymarket.com` (`src/config.py`)
- Auth: None required
- Usage: Referenced in config but not actively called yet

**Polymarket WebSocket (Real-time):**
- Purpose: Real-time order and trade updates
- Base URL: `ws-subscriptions-clob.polymarket.com` (`src/config.py`)
- Auth: Authenticated connection
- Usage: Planned for trade listener collector (not yet implemented)

## Data Storage

**Databases:**
- SQLite via aiosqlite (listed in `requirements.txt`, not yet used)
- TimescaleDB (planned, documented in `docs/HANDOFF_DATA_DAEMON.md`)
  - Connection: asyncpg directly (not SQLAlchemy ORM)
  - Planned URL: `postgresql://polymarket:polymarket@localhost:5432/polymarket`
  - Migrations: Numbered SQL files (planned)

**File Storage:**
- Circuit breaker state: JSON file on disk (`src/utils/circuit_breaker.py`)
- Config: YAML file (`config.example.yaml`)

**Caching:**
- None currently
- In-memory rate limiter token buckets (`src/utils/retry.py`)

## Authentication & Identity

**Wallet Authentication:**
- Polygon wallet private key for CLOB API signing (`src/config.py`)
- Env var: `POLY_PRIVATE_KEY` (never stored in config file)
- Funder address: configured in `config.example.yaml`
- Signature types: 0=EOA, 1=Magic, 2=Gnosis Safe (`src/config.py`)
- API credentials derived at runtime: `create_or_derive_api_creds()` (`src/utils/client.py`)

## Monitoring & Observability

**Error Tracking:**
- None (Python logging only)

**Analytics:**
- None

**Logs:**
- Python `logging` module to stdout/file
- Rich console for CLI-facing output
- Log level configurable via `config.example.yaml`
- Log rotation configurable (max bytes, backup count)

**Alerts:**
- Telegram bot (planned) - `python-telegram-bot >=20.0` in `requirements.txt`
- Env var: `TELEGRAM_BOT_TOKEN` (`src/config.py`)
- Not yet actively wired up

## CI/CD & Deployment

**Hosting:**
- Target: AWS or Hetzner server (US IP required)
- Documented in `docs/AWS_INFRASTRUCTURE.md`
- Docker for TimescaleDB (planned)

**CI Pipeline:**
- None configured (no GitHub Actions, no CI files)

## Environment Configuration

**Development:**
- Required: `config.yaml` (copy from `config.example.yaml`)
- Secrets: `POLY_PRIVATE_KEY` env var (for authenticated operations)
- Optional: `TELEGRAM_BOT_TOKEN` env var (for alerts)
- Paper trading mode enabled by default (no real money risk)

**Production:**
- Same config structure, different values
- `paper_trading: false` to enable real trading
- US-based server for unrestricted Polymarket API access
- Docker for TimescaleDB database

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- Telegram alerts (planned, not yet implemented)

## Blockchain Integration

**Polygon Network:**
- web3 >=6.0.0 in `requirements.txt`
- Used indirectly through py-clob-client for transaction signing
- USDC token transfers on Polygon for market positions

---

*Integration audit: 2026-02-16*
*Update when adding/removing external services*

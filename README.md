# Polymarket Statistical Arbitrage Bot

Automated arbitrage detection and execution for Polymarket prediction markets.

## Overview

This bot runs on AWS (or any server with US/unrestricted IP) to interface with Polymarket's CLOB API, identifying and executing arbitrage opportunities across prediction markets.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     AWS Instance                        │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │  Scanner    │  │  Executor   │  │  Monitor        │  │
│  │  - Markets  │→ │  - Orders   │→ │  - Positions    │  │
│  │  - Prices   │  │  - Signing  │  │  - Alerts       │  │
│  │  - Arb Det. │  │  - Risk     │  │  - P&L          │  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Arbitrage Types

1. **Same-Market Rebalancing** - When YES + NO < $1.00
2. **Combinatorial Arbitrage** - Logically related markets mispriced
3. **Cross-Platform** - Polymarket vs Kalshi discrepancies (future)

## Quick Start

```bash
# Clone
git clone https://github.com/nickolaschua/polymarket-stat-arb.git
cd polymarket-stat-arb

# Install dependencies
pip install -r requirements.txt

# Copy config
cp config.example.yaml config.yaml
# Edit config.yaml with your settings

# Run scanner (read-only, no trading)
python -m src.scanner.main

# Run bot (with trading)
python -m src.main --live
```

## Configuration

```yaml
# config.yaml
polymarket:
  host: "https://clob.polymarket.com"
  chain_id: 137

wallet:
  # NEVER commit real keys! Use environment variables
  private_key_env: "POLY_PRIVATE_KEY"
  funder_address: "0x..."

strategy:
  min_spread: 0.02        # Minimum 2% spread to trade
  max_position: 100       # Max $100 per position
  max_total_exposure: 500 # Max $500 total

alerts:
  telegram_bot_token_env: "TELEGRAM_BOT_TOKEN"
  telegram_chat_id: "..."
```

## Project Structure

```
polymarket-stat-arb/
├── src/
│   ├── scanner/        # Market scanning & opportunity detection
│   ├── executor/       # Order execution & signing
│   ├── monitor/        # Position tracking & alerts
│   └── utils/          # Shared utilities
├── tests/              # Unit & integration tests
├── scripts/            # Deployment & utility scripts
├── docs/               # Documentation
├── config.example.yaml
├── requirements.txt
└── README.md
```

## API Reference

| API | Endpoint | Purpose |
|-----|----------|---------|
| Gamma | `gamma-api.polymarket.com` | Market discovery |
| CLOB | `clob.polymarket.com` | Trading & orderbooks |
| Data | `data-api.polymarket.com` | Positions & history |
| WebSocket | `ws-subscriptions-clob.polymarket.com` | Real-time updates |

## Rate Limits

- Orders: 500/s burst, 60/s sustained
- Market data: 150/s
- Gamma API: 30-50/s per endpoint

## Security

⚠️ **Never commit private keys or secrets**

- Use environment variables for sensitive data
- Use a dedicated wallet with limited funds
- Start with paper trading before going live

## License

MIT

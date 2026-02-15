# Technology Stack

**Analysis Date:** 2026-02-16

## Languages

**Primary:**
- Python 3.x - All application code (`src/`, `scripts/`)

**Secondary:**
- SQL - Database migrations (planned, not yet implemented)
- YAML - Configuration (`config.example.yaml`)

## Runtime

**Environment:**
- Python 3.x (no `.python-version` or version pin detected)
- asyncio event loop (async-first architecture)
- Windows requires `WindowsSelectorEventLoopPolicy` for asyncpg compatibility

**Package Manager:**
- pip
- Lockfile: No `requirements.lock` or `Pipfile.lock` — only `requirements.txt`

## Frameworks

**Core:**
- Click 8.x - CLI framework (`src/main.py`)
- asyncio - Async runtime (throughout `src/`)

**Testing:**
- pytest 7.x - Test runner (`requirements.txt`)
- pytest-asyncio 0.21.x - Async test support (`requirements.txt`)

**Build/Dev:**
- No build step (pure Python, no compilation)
- No bundling or transpilation

## Key Dependencies

**Critical:**
- py-clob-client >=0.18.0 - Official Polymarket CLOB API client (`src/utils/client.py`)
- httpx >=0.27.0 - Async HTTP client for API calls (`src/utils/client.py`, `src/scanner/main.py`)
- web3 >=6.0.0 - Polygon blockchain interaction (`requirements.txt`)
- pydantic >=2.0.0 - Configuration validation and data models (`src/config.py`)

**Infrastructure:**
- aiohttp >=3.9.0 - Async HTTP (WebSocket support) (`requirements.txt`)
- websockets >=12.0 - Real-time market data (`requirements.txt`)
- sqlalchemy >=2.0.0 - Database ORM (imported but not yet used) (`requirements.txt`)
- aiosqlite >=0.19.0 - Async SQLite driver (`requirements.txt`)

**Data/ML (listed but not yet actively used):**
- pandas >=2.0.0 - Data analysis (`requirements.txt`)
- numpy >=1.24.0 - Numerical computation (`requirements.txt`)
- chromadb >=0.4.0 - Vector search for market similarity (`requirements.txt`)
- sentence-transformers >=2.2.0 - Embeddings for market grouping (`requirements.txt`)

**Utilities:**
- rich >=13.0.0 - Pretty CLI output, tables (`src/scanner/main.py`)
- pyyaml >=6.0 - YAML config parsing (`src/config.py`)
- python-telegram-bot >=20.0 - Alert notifications (`requirements.txt`)

## Configuration

**Environment:**
- YAML config files (`config.example.yaml`)
- Environment variables for secrets: `POLY_PRIVATE_KEY`, `TELEGRAM_BOT_TOKEN`
- Pydantic BaseModel for typed config validation (`src/config.py`)

**Build:**
- No build configuration (pure Python)
- No pyproject.toml or setup.py

## Platform Requirements

**Development:**
- Any platform with Python 3.x (Windows, macOS, Linux)
- Docker for TimescaleDB (planned, `docker-compose.yml` not yet created)

**Production:**
- AWS or Hetzner server (US IP required for unrestricted Polymarket API access)
- Docker for TimescaleDB (planned)

---

*Stack analysis: 2026-02-16*
*Update after major dependency changes*

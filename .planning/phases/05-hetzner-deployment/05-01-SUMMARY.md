---
phase: 05-hetzner-deployment
plan: 01
subsystem: infra
tags: [docker, systemd, age-encryption, bash, deployment, hetzner]

# Dependency graph
requires:
  - phase: 04-daemon-supervisor-cli
    provides: collector daemon with run/stop lifecycle and CLI entry point
provides:
  - production Docker Compose for TimescaleDB (localhost-only, env-var credentials)
  - systemd service with auto-restart and age-encrypted key management
  - idempotent server bootstrap script (deploy.sh)
  - database migration runner for standalone execution
  - production config template with documented settings
affects: [05-02 server provisioning and deployment]

# Tech tracking
tech-stack:
  added: [age (encryption)]
  patterns: [systemd service wrapper with exec, age keypair encryption for secrets, idempotent bash bootstrap, localhost-only Docker binding]

key-files:
  created:
    - deploy/docker-compose.prod.yml
    - deploy/polymarket-collector.service
    - deploy/deploy.sh
    - deploy/run-migrations.py
    - deploy/encrypt-key.sh
    - deploy/decrypt-key.sh
    - deploy/start-collector.sh
    - config.prod.yaml
    - .env.production.example
  modified: []

key-decisions:
  - "start-collector.sh wrapper pattern: decrypt key + source env + exec Python so systemd tracks Python PID directly"
  - "age keypair encryption over GPG: simpler CLI, single binary, no keyring complexity"
  - "deploy.sh idempotent with checks before each step: safe to re-run on updates"
  - "localhost-only Docker port binding (127.0.0.1:5432) to prevent DB exposure"

patterns-established:
  - "Wrapper script pattern: decrypt secrets in memory -> exec main process (never write plaintext to disk)"
  - "9-step idempotent bootstrap: deps -> user -> repo -> venv -> config -> db -> migrations -> systemd -> permissions"

issues-created: []

# Metrics
duration: 5min
completed: 2026-02-18
---

# Phase 5 Plan 1: Production Deployment Artifacts Summary

**Complete deploy/ directory with Docker Compose, systemd service, age-encrypted key management, idempotent bootstrap script, and production config for Hetzner CPX31**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-18T10:34:51Z
- **Completed:** 2026-02-18T10:39:34Z
- **Tasks:** 3
- **Files created:** 9

## Accomplishments
- Production Docker Compose with env-var credentials, resource limits (2GB/1CPU), localhost-only binding, health check, and telemetry disabled
- systemd service with auto-restart, journald logging, and start-collector.sh wrapper that decrypts age-encrypted wallet key at runtime
- Idempotent 9-step deploy.sh bootstrap script covering full Ubuntu/Debian server provisioning from apt packages through systemd service enablement
- age encryption workflow: encrypt-key.sh reads private key from stdin (never touches disk), decrypt-key.sh exports to env var, start-collector.sh orchestrates at service start

## Task Commits

Each task was committed atomically:

1. **Task 1: Production Docker Compose + config template** - `498ad71` (feat)
2. **Task 2: systemd service + deploy script** - `34961bd` (feat)
3. **Task 3: age encryption scripts + environment template** - `3dfa995` (feat)

## Files Created/Modified
- `deploy/docker-compose.prod.yml` - Production TimescaleDB container (env-var creds, localhost binding, resource limits, health check)
- `deploy/polymarket-collector.service` - systemd unit file (Type=simple, User=polymarket, Restart=always, RestartSec=10)
- `deploy/deploy.sh` - Idempotent server bootstrap (9 steps: deps, user, repo, venv, config, TimescaleDB, migrations, systemd, permissions)
- `deploy/run-migrations.py` - Standalone migration runner using existing get_pool() + run_migrations()
- `deploy/encrypt-key.sh` - Encrypts wallet private key with age (reads from stdin)
- `deploy/decrypt-key.sh` - Sourceable script exporting decrypted POLY_PRIVATE_KEY
- `deploy/start-collector.sh` - systemd entry point (source env, decrypt key, exec Python)
- `config.prod.yaml` - Production config template (INFO logging, /opt paths, paper_trading: true)
- `.env.production.example` - Documented env var template with usage instructions

## Decisions Made
- start-collector.sh wrapper pattern: sources .env.production, decrypts age key, then exec's Python so systemd tracks the Python PID directly (no intermediate shell)
- age encryption over GPG: simpler single-binary tool, no keyring complexity
- deploy.sh checks idempotency at every step (user exists? repo cloned? venv created? config copied?)
- Docker binds 127.0.0.1:5432 only — database never exposed to internet

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness
- All deployment artifacts ready for Phase 5 Plan 2 (server provisioning)
- deploy.sh can bootstrap a fresh Hetzner CPX31 from zero to running service
- No blockers — ready for server provisioning + deployment + smoke test

---
*Phase: 05-hetzner-deployment*
*Completed: 2026-02-18*

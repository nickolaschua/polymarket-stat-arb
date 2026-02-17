# Phase 3: WebSocket Trades + Resolution Tracker - Context

**Gathered:** 2026-02-17
**Status:** Ready for planning

<vision>
## How This Should Work

A continuous, autonomous trade listener and resolution tracker that runs 24/7 without intervention. Connects to Polymarket's WebSocket trade stream, subscribes to active markets, and silently streams every trade into TimescaleDB. Resolution tracker polls for closed markets and records winners.

It should feel production-grade from day 1 — this is the first always-on component and it's capturing irreplaceable data. Proper error handling, graceful shutdown, no data corruption on restart.

Observability is key: structured logging for connection events, trade throughput, reconnections, and resolution detections. Queryable health state so you can ask "how many trades in the last hour" or "when was last reconnect." Eventually Telegram alerts for critical events (disconnected >60s, resolution detected), but that wiring comes later.

The core contract: connect, subscribe, stream, store. Never silently fail. If something goes wrong, log it clearly and reconnect.

</vision>

<essential>
## What Must Be Nailed

- **Never miss trades** — Reconnection logic, buffering during disconnects, guaranteed delivery to DB. Losing trade data defeats the entire purpose of the data daemon.
- **Correct resolution tracking** — Winner inference must be right. Bad resolution labels corrupt all downstream training data. Better to leave unresolved than record wrong.
- **Structured observability** — Logs and queryable health state. Must be able to verify the system is healthy without guessing.

</essential>

<boundaries>
## What's Out of Scope

- Telegram alerts — belongs in Phase 4 (daemon supervisor) or later
- Advanced reconnection strategies — basic reconnect is sufficient for now, no exponential backoff across multiple connections
- Historical backfill — no backfilling missed trades from REST API, accept gaps and move forward
- Daemon orchestration — this phase builds the individual components, Phase 4 wires them together

</boundaries>

<specifics>
## Specific Ideas

- Production-grade from day 1: proper error handling, graceful shutdown, no data corruption on restart
- Should support queryable health state (trade counts per interval, last reconnect time, connection status)
- Structured logging for all significant events: connections, disconnections, reconnections, trade batch inserts, resolution detections
- Accept that geoblocking means all local tests must mock the WebSocket — real testing only from Hetzner

</specifics>

<notes>
## Additional Context

Research is complete (03-RESEARCH.md) with key technical decisions already made:
- websockets v16.0 async iterator with built-in reconnect
- CLOB Market Channel (no auth needed) for trade stream
- Gamma API polling for resolution tracking (WebSocket market_resolved is unreliable)
- asyncio.Queue producer-consumer buffering
- Connection pooling (500 instruments per WS connection)
- App-level PING every 10s
- No trade_id in WS events — NULL in trades table

This is architecturally different from Phase 2's periodic poll-and-insert collectors. It's a long-running listener with more complex async patterns.

</notes>

---

*Phase: 03-websocket-trades*
*Context gathered: 2026-02-17*

"""Circuit breaker and kill switch for trading risk management.

Automatically halts trading when risk thresholds are breached.
State persists to disk so breaker trips survive bot restarts.

Usage:
    breaker = CircuitBreaker(config)
    breaker.load_state()  # Restore from disk

    # Before every trade:
    if not breaker.allow_trade(trade_size_usd=50.0):
        logger.warning("Circuit breaker OPEN — trade blocked")
        return

    # After every trade settles:
    breaker.record_trade(pnl=-12.50, size_usd=50.0)

    # Manual kill switch:
    breaker.trip("Manual shutdown for maintenance")
    breaker.reset()  # Re-enable trading
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Defaults — can be overridden via config
DEFAULT_MAX_DAILY_LOSS_USD = 50.0
DEFAULT_MAX_POSITION_USD = 100.0
DEFAULT_MAX_TOTAL_EXPOSURE_USD = 500.0
DEFAULT_MAX_DRAWDOWN_PCT = 20.0
DEFAULT_MAX_CONSECUTIVE_LOSSES = 5
DEFAULT_STATE_FILE = "data/circuit_breaker_state.json"


@dataclass
class CircuitBreakerState:
    """Persisted state for the circuit breaker."""

    is_open: bool = False
    trip_reason: str = ""
    trip_time: Optional[float] = None

    # Daily tracking (resets at UTC midnight)
    daily_pnl_usd: float = 0.0
    daily_trade_count: int = 0
    daily_reset_date: str = ""  # YYYY-MM-DD in UTC

    # Running stats
    consecutive_losses: int = 0
    total_exposure_usd: float = 0.0
    peak_balance_usd: float = 0.0
    current_balance_usd: float = 0.0


class CircuitBreaker:
    """Trading circuit breaker with automatic and manual trip modes.

    Checks performed before each trade:
    - Daily loss limit not exceeded
    - Max position size respected
    - Total exposure within bounds
    - Consecutive loss streak within limit
    - Drawdown from peak within threshold
    - Manual kill switch not engaged
    """

    def __init__(
        self,
        max_daily_loss_usd: float = DEFAULT_MAX_DAILY_LOSS_USD,
        max_position_usd: float = DEFAULT_MAX_POSITION_USD,
        max_total_exposure_usd: float = DEFAULT_MAX_TOTAL_EXPOSURE_USD,
        max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
        max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
        starting_balance_usd: float = 0.0,
        state_file: str = DEFAULT_STATE_FILE,
    ):
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_position_usd = max_position_usd
        self.max_total_exposure_usd = max_total_exposure_usd
        self.max_drawdown_pct = max_drawdown_pct
        self.max_consecutive_losses = max_consecutive_losses
        self._state_file = Path(state_file)

        self.state = CircuitBreakerState(
            peak_balance_usd=starting_balance_usd,
            current_balance_usd=starting_balance_usd,
        )

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def allow_trade(self, trade_size_usd: float = 0.0) -> bool:
        """Check if a trade is permitted. Returns False if breaker is open."""
        self._maybe_reset_daily()

        if self.state.is_open:
            logger.warning(
                "Trade blocked — circuit breaker OPEN: %s", self.state.trip_reason
            )
            return False

        # Check daily loss
        if self.state.daily_pnl_usd <= -self.max_daily_loss_usd:
            self.trip(f"Daily loss limit hit: ${self.state.daily_pnl_usd:.2f}")
            return False

        # Check position size
        if trade_size_usd > self.max_position_usd:
            logger.warning(
                "Trade size $%.2f exceeds max $%.2f",
                trade_size_usd,
                self.max_position_usd,
            )
            return False

        # Check total exposure
        if self.state.total_exposure_usd + trade_size_usd > self.max_total_exposure_usd:
            logger.warning(
                "Would exceed max exposure: current=$%.2f + new=$%.2f > max=$%.2f",
                self.state.total_exposure_usd,
                trade_size_usd,
                self.max_total_exposure_usd,
            )
            return False

        # Check consecutive losses
        if self.state.consecutive_losses >= self.max_consecutive_losses:
            self.trip(
                f"Consecutive loss streak: {self.state.consecutive_losses}"
            )
            return False

        # Check drawdown from peak
        if self.state.peak_balance_usd > 0:
            drawdown_pct = (
                (self.state.peak_balance_usd - self.state.current_balance_usd)
                / self.state.peak_balance_usd
                * 100
            )
            if drawdown_pct >= self.max_drawdown_pct:
                self.trip(f"Max drawdown hit: {drawdown_pct:.1f}%")
                return False

        return True

    def record_trade(self, pnl: float, size_usd: float = 0.0):
        """Record a completed trade's P&L and update state."""
        self._maybe_reset_daily()

        self.state.daily_pnl_usd += pnl
        self.state.daily_trade_count += 1
        self.state.current_balance_usd += pnl

        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

        if self.state.current_balance_usd > self.state.peak_balance_usd:
            self.state.peak_balance_usd = self.state.current_balance_usd

        self.save_state()

        logger.info(
            "Trade recorded: pnl=$%.2f daily=$%.2f streak=%d balance=$%.2f",
            pnl,
            self.state.daily_pnl_usd,
            self.state.consecutive_losses,
            self.state.current_balance_usd,
        )

    def update_exposure(self, total_exposure_usd: float):
        """Update current total exposure (sum of all open position sizes)."""
        self.state.total_exposure_usd = total_exposure_usd

    def trip(self, reason: str):
        """Manually or automatically trip the circuit breaker."""
        self.state.is_open = True
        self.state.trip_reason = reason
        self.state.trip_time = time.time()
        self.save_state()
        logger.critical("CIRCUIT BREAKER TRIPPED: %s", reason)

    def reset(self):
        """Reset the circuit breaker to allow trading again."""
        self.state.is_open = False
        self.state.trip_reason = ""
        self.state.trip_time = None
        self.state.consecutive_losses = 0
        self.save_state()
        logger.info("Circuit breaker RESET — trading enabled")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self):
        """Persist state to disk."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    def load_state(self):
        """Load state from disk. No-op if file doesn't exist."""
        if not self._state_file.exists():
            return
        try:
            with open(self._state_file) as f:
                data = json.load(f)
            self.state = CircuitBreakerState(**data)
            logger.info(
                "Loaded circuit breaker state: open=%s daily_pnl=$%.2f",
                self.state.is_open,
                self.state.daily_pnl_usd,
            )
        except Exception as e:
            logger.error("Failed to load circuit breaker state: %s", e)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def status(self) -> dict:
        """Return current breaker status for monitoring."""
        self._maybe_reset_daily()
        return {
            "is_open": self.state.is_open,
            "trip_reason": self.state.trip_reason,
            "daily_pnl_usd": self.state.daily_pnl_usd,
            "daily_trade_count": self.state.daily_trade_count,
            "consecutive_losses": self.state.consecutive_losses,
            "total_exposure_usd": self.state.total_exposure_usd,
            "current_balance_usd": self.state.current_balance_usd,
            "peak_balance_usd": self.state.peak_balance_usd,
            "remaining_daily_loss_usd": max(
                0, self.max_daily_loss_usd + self.state.daily_pnl_usd
            ),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_reset_daily(self):
        """Reset daily counters if the UTC date has changed."""
        import datetime

        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        if self.state.daily_reset_date != today:
            self.state.daily_pnl_usd = 0.0
            self.state.daily_trade_count = 0
            self.state.daily_reset_date = today

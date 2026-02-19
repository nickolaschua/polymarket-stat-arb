"""Retry and error handling utilities for API calls.

Provides:
- Exponential backoff decorator for sync and async functions
- Rate limit tracker for Gamma and CLOB APIs
- Error classification (retryable vs fatal)

Usage:
    @retry(max_attempts=3, retryable_exceptions=(httpx.TimeoutException,))
    async def fetch_markets():
        ...

    rate_limiter = RateLimiter(max_requests=60, window_seconds=60)
    await rate_limiter.acquire()
    response = await client.get(url)
    rate_limiter.record_response(response)
"""

import asyncio
import functools
import logging
import time
from collections import deque
from typing import Callable, Optional, Sequence, Type

import httpx

logger = logging.getLogger(__name__)

# HTTP status codes that indicate retryable errors
RETRYABLE_STATUS_CODES = {
    408,  # Request Timeout
    429,  # Too Many Requests (rate limited)
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

# HTTP status codes that are fatal — do not retry
FATAL_STATUS_CODES = {
    400,  # Bad Request (malformed)
    401,  # Unauthorized (bad credentials)
    403,  # Forbidden (geoblocked or banned)
    404,  # Not Found
    422,  # Unprocessable Entity
}

# Exceptions that are always worth retrying
RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    ConnectionError,
    OSError,
)

# Exceptions that should never be retried
FATAL_EXCEPTIONS = (
    KeyboardInterrupt,
    SystemExit,
    MemoryError,
)


def is_retryable_status(status_code: int) -> bool:
    """Check if an HTTP status code is retryable."""
    return status_code in RETRYABLE_STATUS_CODES


def is_fatal_status(status_code: int) -> bool:
    """Check if an HTTP status code is fatal (do not retry)."""
    return status_code in FATAL_STATUS_CODES


class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, last_exception: Exception, attempts: int):
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(
            f"All {attempts} retry attempts exhausted. Last error: {last_exception}"
        )


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: Sequence[Type[Exception]] = RETRYABLE_EXCEPTIONS,
    on_retry: Optional[Callable] = None,
):
    """Decorator for retrying async functions with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Multiplier for each successive retry.
        retryable_exceptions: Tuple of exception types to retry on.
        on_retry: Optional callback(attempt, exception, delay) called before each retry.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except FATAL_EXCEPTIONS:
                    raise
                except tuple(retryable_exceptions) as e:
                    last_exception = e

                    if attempt == max_attempts:
                        break

                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay,
                    )

                    logger.warning(
                        "%s attempt %d/%d failed: %s — retrying in %.1fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        e,
                        delay,
                    )

                    if on_retry:
                        on_retry(attempt, e, delay)

                    await asyncio.sleep(delay)
                except httpx.HTTPStatusError as e:
                    if is_retryable_status(e.response.status_code):
                        last_exception = e

                        if attempt == max_attempts:
                            break

                        delay = _delay_for_status(
                            e.response, base_delay, exponential_base, attempt, max_delay
                        )

                        logger.warning(
                            "%s attempt %d/%d got HTTP %d — retrying in %.1fs",
                            func.__name__,
                            attempt,
                            max_attempts,
                            e.response.status_code,
                            delay,
                        )

                        if on_retry:
                            on_retry(attempt, e, delay)

                        await asyncio.sleep(delay)
                    else:
                        raise

            raise RetryExhausted(last_exception, max_attempts)

        return wrapper

    return decorator


def retry_sync(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: Sequence[Type[Exception]] = RETRYABLE_EXCEPTIONS,
):
    """Decorator for retrying synchronous functions with exponential backoff."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except FATAL_EXCEPTIONS:
                    raise
                except tuple(retryable_exceptions) as e:
                    last_exception = e

                    if attempt == max_attempts:
                        break

                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay,
                    )

                    logger.warning(
                        "%s attempt %d/%d failed: %s — retrying in %.1fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        e,
                        delay,
                    )

                    time.sleep(delay)

            raise RetryExhausted(last_exception, max_attempts)

        return wrapper

    return decorator


class RateLimiter:
    """Token-bucket rate limiter for API calls.

    Tracks request timestamps in a sliding window and blocks (async sleep)
    when the limit is reached. Also respects Retry-After headers.

    Usage:
        limiter = RateLimiter(max_requests=60, window_seconds=60)

        async def call_api():
            await limiter.acquire()
            response = await client.get(url)
            limiter.record_response(response)
            return response
    """

    def __init__(self, max_requests: int, window_seconds: float, name: str = ""):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name or f"limiter-{max_requests}/{window_seconds}s"
        self._timestamps: deque = deque()
        self._retry_after: float = 0.0

    async def acquire(self):
        """Wait until a request slot is available."""
        # Respect Retry-After from previous 429 response
        if self._retry_after > time.time():
            wait = self._retry_after - time.time()
            logger.info(
                "%s: Retry-After active, waiting %.1fs", self.name, wait
            )
            await asyncio.sleep(wait)

        now = time.time()
        cutoff = now - self.window_seconds

        # Remove expired timestamps
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        # If at capacity, wait for the oldest request to expire
        if len(self._timestamps) >= self.max_requests:
            wait = self._timestamps[0] - cutoff + 0.05  # 50ms buffer
            logger.debug(
                "%s: Rate limit reached (%d/%d), waiting %.2fs",
                self.name,
                len(self._timestamps),
                self.max_requests,
                wait,
            )
            await asyncio.sleep(max(0, wait))

        self._timestamps.append(time.time())

    def record_response(self, response: httpx.Response):
        """Record response headers to adjust rate limiting."""
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    self._retry_after = time.time() + float(retry_after)
                    logger.warning(
                        "%s: Got 429, Retry-After=%ss", self.name, retry_after
                    )
                except ValueError:
                    self._retry_after = time.time() + 5.0

    @property
    def available_requests(self) -> int:
        """Number of requests available in the current window."""
        now = time.time()
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        return max(0, self.max_requests - len(self._timestamps))


# Pre-configured rate limiters for Polymarket APIs
# All limits from docs/POLYMARKET_VERIFIED_REFERENCE.md (verified 2026-02-15)
# We use ~70% of documented limits as safety margin.

# Gamma API: /markets 300/10s, /events 500/10s → conservative at 200/10s
gamma_limiter = RateLimiter(max_requests=200, window_seconds=10, name="gamma")

# CLOB public endpoints: /book 1500/10s, general 9000/10s → conservative at 1000/10s
clob_read_limiter = RateLimiter(max_requests=1000, window_seconds=10, name="clob-read")

# CLOB trading: POST /order 36000/10min sustained (60/s) → conservative at 400/10s
clob_trade_limiter = RateLimiter(max_requests=400, window_seconds=10, name="clob-trade")


def _delay_for_status(
    response: httpx.Response,
    base_delay: float,
    exponential_base: float,
    attempt: int,
    max_delay: float,
) -> float:
    """Calculate retry delay, respecting Retry-After header for 429s."""
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), max_delay)
            except ValueError:
                pass
    return min(base_delay * (exponential_base ** (attempt - 1)), max_delay)

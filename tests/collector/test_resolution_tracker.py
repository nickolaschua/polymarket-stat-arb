"""Tests for resolution winner inference and ResolutionTracker collector.

Unit tests verify infer_winner() logic without DB or HTTP.
Integration tests use respx to mock the Gamma API and migrated_pool
for real database writes via ResolutionTracker.collect_once().
"""

from datetime import datetime, timezone

import httpx
import respx

from src.collector.resolution_tracker import ResolutionTracker, infer_winner
from src.config import CollectorConfig
from src.db.queries.markets import get_market, upsert_market
from src.db.queries.resolutions import get_resolution, upsert_resolution


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_market(
    condition_id: str = "0xabc123",
    outcome_prices: str = '["1","0"]',
    outcomes: str = '["Yes","No"]',
    clob_token_ids: str = '["tok_a","tok_b"]',
    **overrides,
) -> dict:
    """Build a sample Gamma API market dict for resolution testing."""
    base = {
        "conditionId": condition_id,
        "outcomePrices": outcome_prices,
        "outcomes": outcomes,
        "clobTokenIds": clob_token_ids,
    }
    base.update(overrides)
    return base


# =========================================================================
# Unit tests — infer_winner()
# =========================================================================


class TestInferWinnerResolved:
    """Tests for markets that ARE resolved (outcomePrices contains 1.0)."""

    def test_first_outcome_wins(self) -> None:
        """outcomePrices '["1","0"]' -> first outcome (Yes) wins."""
        raw = _make_raw_market()
        result = infer_winner(raw)

        assert result is not None
        assert result["condition_id"] == "0xabc123"
        assert result["outcome"] == "Yes"
        assert result["winner_token_id"] == "tok_a"
        assert result["payout_price"] == 1.0
        assert result["detection_method"] == "gamma_api_polling"
        assert isinstance(result["resolved_at"], datetime)
        assert result["resolved_at"].tzinfo == timezone.utc

    def test_second_outcome_wins(self) -> None:
        """outcomePrices '["0","1"]' -> second outcome (No) wins."""
        raw = _make_raw_market(outcome_prices='["0","1"]')
        result = infer_winner(raw)

        assert result is not None
        assert result["condition_id"] == "0xabc123"
        assert result["outcome"] == "No"
        assert result["winner_token_id"] == "tok_b"
        assert result["payout_price"] == 1.0

    def test_float_string_one_point_zero(self) -> None:
        """outcomePrices '["1.0","0.0"]' -> "1.0" parsed as float 1.0."""
        raw = _make_raw_market(outcome_prices='["1.0","0.0"]')
        result = infer_winner(raw)

        assert result is not None
        assert result["outcome"] == "Yes"
        assert result["winner_token_id"] == "tok_a"
        assert result["payout_price"] == 1.0

    def test_three_outcome_market(self) -> None:
        """3-outcome market: first outcome wins."""
        raw = _make_raw_market(
            outcome_prices='["1","0","0"]',
            outcomes='["A","B","C"]',
            clob_token_ids='["t1","t2","t3"]',
        )
        result = infer_winner(raw)

        assert result is not None
        assert result["outcome"] == "A"
        assert result["winner_token_id"] == "t1"
        assert result["payout_price"] == 1.0

    def test_three_outcome_market_third_wins(self) -> None:
        """3-outcome market: third outcome wins."""
        raw = _make_raw_market(
            outcome_prices='["0","0","1"]',
            outcomes='["A","B","C"]',
            clob_token_ids='["t1","t2","t3"]',
        )
        result = infer_winner(raw)

        assert result is not None
        assert result["outcome"] == "C"
        assert result["winner_token_id"] == "t3"


class TestInferWinnerUnresolved:
    """Tests for markets that are NOT resolved -> returns None."""

    def test_not_resolved(self) -> None:
        """outcomePrices '["0.52","0.48"]' -> None (not resolved)."""
        raw = _make_raw_market(outcome_prices='["0.52","0.48"]')
        result = infer_winner(raw)

        assert result is None

    def test_no_winner_both_zero(self) -> None:
        """outcomePrices '["0","0"]' -> None (no winner)."""
        raw = _make_raw_market(outcome_prices='["0","0"]')
        result = infer_winner(raw)

        assert result is None

    def test_empty_outcome_prices_array(self) -> None:
        """outcomePrices '[]' -> None (empty array)."""
        raw = _make_raw_market(outcome_prices='[]')
        result = infer_winner(raw)

        assert result is None


class TestInferWinnerEdgeCases:
    """Edge cases: missing fields, bad JSON, native types, etc."""

    def test_outcome_prices_missing(self) -> None:
        """outcomePrices key missing entirely -> None."""
        raw = {
            "conditionId": "0xabc",
            "outcomes": '["Yes","No"]',
            "clobTokenIds": '["tok_a","tok_b"]',
        }
        result = infer_winner(raw)

        assert result is None

    def test_outcome_prices_invalid_json(self) -> None:
        """outcomePrices is invalid JSON -> None."""
        raw = _make_raw_market(outcome_prices="not-json")
        result = infer_winner(raw)

        assert result is None

    def test_outcomes_missing_still_returns_result(self) -> None:
        """outcomes missing -> result returned with outcome=None."""
        raw = {
            "conditionId": "0xabc",
            "outcomePrices": '["1","0"]',
            "clobTokenIds": '["tok_a","tok_b"]',
        }
        result = infer_winner(raw)

        assert result is not None
        assert result["condition_id"] == "0xabc"
        assert result["outcome"] is None
        assert result["winner_token_id"] == "tok_a"

    def test_clob_token_ids_missing_still_returns_result(self) -> None:
        """clobTokenIds missing -> result with winner_token_id=None."""
        raw = {
            "conditionId": "0xabc",
            "outcomePrices": '["1","0"]',
            "outcomes": '["Yes","No"]',
        }
        result = infer_winner(raw)

        assert result is not None
        assert result["outcome"] == "Yes"
        assert result["winner_token_id"] is None

    def test_native_list_types(self) -> None:
        """outcomePrices, outcomes, clobTokenIds as native lists (not JSON strings)."""
        raw = {
            "conditionId": "0xnative",
            "outcomePrices": ["1", "0"],
            "outcomes": ["Yes", "No"],
            "clobTokenIds": ["tok_a", "tok_b"],
        }
        result = infer_winner(raw)

        assert result is not None
        assert result["condition_id"] == "0xnative"
        assert result["outcome"] == "Yes"
        assert result["winner_token_id"] == "tok_a"

    def test_snake_case_condition_id(self) -> None:
        """condition_id (snake_case) accepted instead of conditionId."""
        raw = {
            "condition_id": "0xsnake",
            "outcomePrices": '["0","1"]',
            "outcomes": '["Yes","No"]',
            "clobTokenIds": '["tok_a","tok_b"]',
        }
        result = infer_winner(raw)

        assert result is not None
        assert result["condition_id"] == "0xsnake"
        assert result["outcome"] == "No"

    def test_never_raises_on_garbage_input(self) -> None:
        """Totally garbage input -> None, never raises."""
        assert infer_winner({}) is None
        assert infer_winner({"outcomePrices": 42}) is None
        assert infer_winner({"outcomePrices": None}) is None
        assert infer_winner({"outcomePrices": '["bad"]', "conditionId": "x"}) is None

    def test_never_raises_on_non_numeric_prices(self) -> None:
        """Non-numeric price strings -> None, never raises."""
        raw = _make_raw_market(outcome_prices='["abc","def"]')
        result = infer_winner(raw)

        assert result is None

    def test_condition_id_missing_entirely(self) -> None:
        """No condition_id at all -> result still returned if resolved, condition_id is empty string."""
        raw = {
            "outcomePrices": '["1","0"]',
            "outcomes": '["Yes","No"]',
            "clobTokenIds": '["tok_a","tok_b"]',
        }
        result = infer_winner(raw)

        # Should still return a result (condition_id empty string is acceptable;
        # upsert_resolution will handle validation)
        assert result is not None
        assert result["condition_id"] == ""
        assert result["outcome"] == "Yes"

    def test_resolved_at_is_recent_utc(self) -> None:
        """resolved_at is a recent UTC datetime."""
        before = datetime.now(timezone.utc)
        raw = _make_raw_market()
        result = infer_winner(raw)
        after = datetime.now(timezone.utc)

        assert result is not None
        assert before <= result["resolved_at"] <= after


# ---------------------------------------------------------------------------
# Integration test helpers
# ---------------------------------------------------------------------------

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"


def _make_event(markets: list[dict], event_id: str = "evt_1") -> dict:
    """Wrap market dicts in an event structure."""
    return {"id": event_id, "markets": markets}


def _tracker(pool) -> ResolutionTracker:
    """Create a ResolutionTracker with default config."""
    return ResolutionTracker(pool=pool, config=CollectorConfig())


# =========================================================================
# Integration tests — ResolutionTracker.collect_once()
# =========================================================================


class TestResolutionTrackerCollectOnce:
    """Integration tests for ResolutionTracker using respx + migrated_pool."""

    @respx.mock
    async def test_collect_once_detects_resolution(
        self, migrated_pool,
    ) -> None:
        """Resolved market (outcomePrices '["1","0"]') -> upserted to DB."""
        events = [
            _make_event([
                _make_raw_market(
                    condition_id="0xresolved_1",
                    outcome_prices='["1","0"]',
                    outcomes='["Yes","No"]',
                    clob_token_ids='["tok_yes","tok_no"]',
                ),
            ]),
        ]

        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(200, json=events),
        )

        # Pre-insert the market so that closed sync has something to update
        await upsert_market(migrated_pool, {
            "condition_id": "0xresolved_1",
            "question": "Will it resolve?",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_yes", "tok_no"],
            "active": True,
            "closed": False,
        })

        tracker = _tracker(migrated_pool)
        try:
            count = await tracker.collect_once()
        finally:
            await tracker.close()

        assert count == 1

        # Verify resolution persisted
        res = await get_resolution(migrated_pool, "0xresolved_1")
        assert res is not None
        assert res.outcome == "Yes"
        assert res.winner_token_id == "tok_yes"
        assert res.payout_price == 1.0
        assert res.detection_method == "gamma_api_polling"

        # Verify market.closed synced to true
        market = await get_market(migrated_pool, "0xresolved_1")
        assert market is not None
        assert market.closed is True

    @respx.mock
    async def test_collect_once_skips_unresolved(
        self, migrated_pool,
    ) -> None:
        """Unresolved market (outcomePrices '["0.95","0.05"]') -> no resolution."""
        events = [
            _make_event([
                _make_raw_market(
                    condition_id="0xunresolved_1",
                    outcome_prices='["0.95","0.05"]',
                ),
            ]),
        ]

        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(200, json=events),
        )

        tracker = _tracker(migrated_pool)
        try:
            count = await tracker.collect_once()
        finally:
            await tracker.close()

        assert count == 0

        res = await get_resolution(migrated_pool, "0xunresolved_1")
        assert res is None

    @respx.mock
    async def test_collect_once_skips_already_resolved(
        self, migrated_pool,
    ) -> None:
        """Pre-existing resolution -> not re-upserted (count stays 0)."""
        # Pre-insert a resolution
        await upsert_resolution(migrated_pool, {
            "condition_id": "0xalready_done",
            "outcome": "Yes",
            "winner_token_id": "tok_yes",
            "payout_price": 1.0,
            "detection_method": "gamma_api_polling",
            "resolved_at": datetime.now(timezone.utc),
        })

        events = [
            _make_event([
                _make_raw_market(
                    condition_id="0xalready_done",
                    outcome_prices='["1","0"]',
                ),
            ]),
        ]

        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(200, json=events),
        )

        tracker = _tracker(migrated_pool)
        try:
            count = await tracker.collect_once()
        finally:
            await tracker.close()

        assert count == 0

    @respx.mock
    async def test_collect_once_paginates(
        self, migrated_pool,
    ) -> None:
        """Multiple pages of closed events are all processed."""
        # Page 1: exactly 100 events (triggers next page)
        page_1_events = [
            _make_event(
                [_make_raw_market(
                    condition_id=f"0xpg1_{i}",
                    outcome_prices='["0.6","0.4"]',  # unresolved
                )],
                event_id=f"evt_p1_{i}",
            )
            for i in range(100)
        ]

        # Page 2: 50 events (< 100, stops pagination)
        page_2_events = [
            _make_event(
                [_make_raw_market(
                    condition_id=f"0xpg2_{i}",
                    outcome_prices='["0.6","0.4"]',  # unresolved
                )],
                event_id=f"evt_p2_{i}",
            )
            for i in range(50)
        ]

        call_count = 0

        def gamma_side_effect(request):
            nonlocal call_count
            call_count += 1
            offset = int(request.url.params.get("offset", 0))
            if offset == 0:
                return httpx.Response(200, json=page_1_events)
            elif offset == 100:
                return httpx.Response(200, json=page_2_events)
            else:
                return httpx.Response(200, json=[])

        respx.get(GAMMA_EVENTS_URL).mock(side_effect=gamma_side_effect)

        tracker = _tracker(migrated_pool)
        try:
            count = await tracker.collect_once()
        finally:
            await tracker.close()

        # None resolved, but both pages fetched
        assert count == 0
        # Should have made exactly 2 API calls (page 1 + page 2, page 2 < limit)
        assert call_count == 2

    @respx.mock
    async def test_collect_once_api_error_returns_zero(
        self, migrated_pool,
    ) -> None:
        """Gamma API 500 error -> returns 0, no exception raised."""
        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(500),
        )

        tracker = _tracker(migrated_pool)
        try:
            count = await tracker.collect_once()
        finally:
            await tracker.close()

        assert count == 0

    @respx.mock
    async def test_collect_once_updates_market_closed(
        self, migrated_pool,
    ) -> None:
        """Closed event syncs market.closed = true even if not resolved."""
        # Pre-insert market with closed=false
        await upsert_market(migrated_pool, {
            "condition_id": "0xclose_sync",
            "question": "Close sync test?",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_a", "tok_b"],
            "active": True,
            "closed": False,
        })

        events = [
            _make_event([
                _make_raw_market(
                    condition_id="0xclose_sync",
                    outcome_prices='["0.7","0.3"]',  # NOT resolved
                ),
            ]),
        ]

        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(200, json=events),
        )

        tracker = _tracker(migrated_pool)
        try:
            count = await tracker.collect_once()
        finally:
            await tracker.close()

        assert count == 0  # not resolved

        # But market.closed should now be true
        market = await get_market(migrated_pool, "0xclose_sync")
        assert market is not None
        assert market.closed is True

"""Tests for resolution winner inference.

Unit tests verify infer_winner() logic without DB or HTTP.
The function takes raw Gamma API market dicts and returns
resolution_data dicts suitable for upsert_resolution(), or None
if the market is not resolved.
"""

from datetime import datetime, timezone

from src.collector.resolution_tracker import infer_winner


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

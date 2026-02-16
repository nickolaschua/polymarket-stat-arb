"""Pydantic models for database records.

Each model maps to a table in the TimescaleDB schema and serves as the
return type for query functions.  Fields match the SQL column definitions
in migrations 002-006.

Usage::

    row = await conn.fetchrow("SELECT * FROM markets WHERE condition_id = $1", cid)
    market = record_to_model(row, MarketRecord)
"""

from datetime import datetime
from typing import Any, Optional

import asyncpg
from pydantic import BaseModel


class MarketRecord(BaseModel):
    """A Polymarket prediction market (regular table, not a hypertable)."""

    condition_id: str
    question: str
    slug: Optional[str] = None
    market_type: Optional[str] = None
    outcomes: list[str] = []
    clob_token_ids: list[str] = []
    active: bool = True
    closed: bool = False
    end_date_iso: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PriceSnapshot(BaseModel):
    """A point-in-time price observation for a token (hypertable)."""

    ts: datetime
    token_id: str
    price: float
    volume_24h: Optional[float] = None


class OrderbookSnapshot(BaseModel):
    """A point-in-time orderbook snapshot for a token (hypertable)."""

    ts: datetime
    token_id: str
    bids: Optional[Any] = None  # JSONB — list of [price, size] pairs
    asks: Optional[Any] = None  # JSONB — list of [price, size] pairs
    spread: Optional[float] = None
    midpoint: Optional[float] = None


class TradeRecord(BaseModel):
    """A single trade execution (hypertable)."""

    ts: datetime
    token_id: str
    side: str
    price: float
    size: float
    trade_id: Optional[str] = None


class ResolutionRecord(BaseModel):
    """The final resolution of a prediction market."""

    condition_id: str
    outcome: Optional[str] = None
    winner_token_id: Optional[str] = None
    resolved_at: Optional[datetime] = None
    payout_price: Optional[float] = None
    detection_method: Optional[str] = None
    created_at: datetime


def record_to_model(record: asyncpg.Record, model_cls: type[BaseModel]) -> BaseModel:
    """Convert an asyncpg Record to a Pydantic model instance.

    Parameters
    ----------
    record:
        A single row returned by asyncpg (``fetchrow`` / iteration over
        ``fetch``).
    model_cls:
        The Pydantic model class to instantiate.

    Returns
    -------
    BaseModel
        An instance of *model_cls* populated from the record's fields.
    """
    return model_cls(**dict(record))

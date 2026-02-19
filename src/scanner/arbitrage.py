"""Arbitrage opportunity detection."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage opportunity."""
    
    opportunity_type: str  # "same_market", "combinatorial", "cross_platform"
    market_id: str
    market_question: str
    
    # Prices
    yes_price: float
    no_price: float
    combined_cost: float
    spread_pct: float
    
    # Token IDs for execution
    yes_token_id: str
    no_token_id: str
    
    # Liquidity
    yes_liquidity: float
    no_liquidity: float
    max_executable_usd: float
    
    # Metadata
    detected_at: datetime
    event_id: Optional[str] = None
    
    @property
    def profit_per_dollar(self) -> float:
        """Expected profit per dollar invested."""
        return 1.0 - self.combined_cost
    
    @property
    def is_valid(self) -> bool:
        """Check if opportunity is still valid (combined cost < 1)."""
        return self.combined_cost < 1.0


@dataclass
class Market:
    """Simplified market representation."""
    
    market_id: str
    event_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume_24h: float
    end_date: Optional[datetime] = None


class ArbitrageScanner:
    """Scans markets for arbitrage opportunities."""

    def __init__(self, min_spread_pct: float = 2.0, min_liquidity: float = 100.0):
        self.min_spread_pct = min_spread_pct
        self.min_liquidity = min_liquidity

    def scan_same_market(
        self,
        markets: List[Market],
        orderbooks: Optional[Dict[str, dict]] = None
    ) -> List[ArbitrageOpportunity]:
        """
        Scan for same-market arbitrage (YES + NO < $1.00).
        
        This is the simplest form of arbitrage but opportunities
        are typically very short-lived (<200ms).
        """
        opportunities = []
        
        for market in markets:
            combined = market.yes_price + market.no_price
            
            # Check if there's a spread
            if combined >= 1.0:
                continue
            
            spread_pct = (1.0 - combined) * 100
            
            # Filter by minimum spread
            if spread_pct < self.min_spread_pct:
                continue
            
            # Calculate executable liquidity
            yes_liq = 0.0
            no_liq = 0.0
            
            if orderbooks:
                yes_book = orderbooks.get(market.yes_token_id, {})
                no_book = orderbooks.get(market.no_token_id, {})
                yes_liq = self._calculate_liquidity(yes_book, "asks")
                no_liq = self._calculate_liquidity(no_book, "asks")
            
            max_executable = min(yes_liq, no_liq) if yes_liq and no_liq else 0.0
            
            if max_executable < self.min_liquidity:
                continue
            
            opp = ArbitrageOpportunity(
                opportunity_type="same_market",
                market_id=market.market_id,
                market_question=market.question,
                yes_price=market.yes_price,
                no_price=market.no_price,
                combined_cost=combined,
                spread_pct=spread_pct,
                yes_token_id=market.yes_token_id,
                no_token_id=market.no_token_id,
                yes_liquidity=yes_liq,
                no_liquidity=no_liq,
                max_executable_usd=max_executable,
                detected_at=datetime.now(timezone.utc),
                event_id=market.event_id
            )
            
            opportunities.append(opp)
            logger.info(
                f"Found same-market arb: {market.question[:50]}... "
                f"spread={spread_pct:.2f}% executable=${max_executable:.2f}"
            )
        
        return opportunities

    def scan_combinatorial(
        self,
        markets: List[Market],
        similarity_groups: Dict[str, List[str]]
    ) -> List[ArbitrageOpportunity]:
        """
        Scan for combinatorial arbitrage across related markets.
        
        This looks for logical inconsistencies like:
        - "Trump wins" at 55% but "Republican wins" at 50%
        
        Requires semantic understanding of market relationships.
        """
        opportunities = []
        
        # TODO: Implement vector similarity grouping
        # For now, we look at markets within the same event
        
        markets_by_event: Dict[str, List[Market]] = {}
        for m in markets:
            if m.event_id not in markets_by_event:
                markets_by_event[m.event_id] = []
            markets_by_event[m.event_id].append(m)
        
        for event_id, event_markets in markets_by_event.items():
            if len(event_markets) < 2:
                continue
            
            # Check if probabilities sum to more than 100% (impossible)
            # or less than 100% for mutually exclusive outcomes
            total_yes_prob = sum(m.yes_price for m in event_markets)
            
            # For mutually exclusive outcomes, sum should equal 1.0
            # If sum < 1.0, there's potential arbitrage
            if total_yes_prob < 1.0 - (self.min_spread_pct / 100):
                spread_pct = (1.0 - total_yes_prob) * 100
                
                logger.info(
                    f"Found combinatorial arb in event {event_id}: "
                    f"sum of YES = {total_yes_prob:.2f}, spread={spread_pct:.2f}%"
                )
                
                # TODO: Create proper opportunity objects for multi-leg trades
        
        return opportunities

    def _calculate_liquidity(
        self,
        orderbook: dict,
        side: str = "asks"
    ) -> float:
        """Calculate total liquidity on one side of the book."""
        orders = orderbook.get(side, [])
        total = 0.0
        
        for order in orders:
            price = float(order.get("price", 0))
            size = float(order.get("size", 0))
            total += price * size
        
        return total


def _parse_stringified_json_array(raw: str, fallback: list) -> list:
    """Parse a stringified JSON array from the Gamma API.

    The Gamma API returns fields like outcomePrices and clobTokenIds as
    stringified JSON arrays, e.g. '["0.52","0.48"]' — NOT comma-separated
    values.  This helper handles both formats defensively.
    """
    if not raw:
        return fallback
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: try comma-split for unexpected formats
    logger.warning("Unexpected non-JSON array format, falling back to comma-split: %r", raw)
    parts = [p.strip().strip('"') for p in raw.split(",")]
    return parts if len(parts) >= len(fallback) else fallback


def _parse_end_date(raw_data: dict) -> Optional[datetime]:
    """Parse endDate from various Gamma API formats."""
    for field in ("endDate", "endDateIso", "end_date_iso"):
        val = raw_data.get(field)
        if not val:
            continue
        try:
            # Handle ISO format with or without timezone
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
    return None


def parse_market_data(raw_data: dict) -> Optional[Market]:
    """Parse raw API market data into Market object.

    The Gamma API returns outcomePrices and clobTokenIds as **stringified
    JSON arrays** (e.g. '["0.52","0.48"]'), not native arrays or
    comma-separated strings.  This function handles that correctly.
    """
    try:
        tokens = _parse_stringified_json_array(
            raw_data.get("clobTokenIds", ""), ["", ""]
        )
        prices = _parse_stringified_json_array(
            raw_data.get("outcomePrices", ""), ["0.5", "0.5"]
        )

        # Ensure we have at least 2 elements
        if len(tokens) < 2:
            tokens = tokens + [""] * (2 - len(tokens))
        if len(prices) < 2:
            prices = prices + ["0.5"] * (2 - len(prices))

        yes_token = str(tokens[0]).strip()
        no_token = str(tokens[1]).strip()
        yes_price = float(prices[0]) if prices[0] else 0.5
        no_price = float(prices[1]) if prices[1] else 0.5

        return Market(
            market_id=raw_data.get("id", raw_data.get("conditionId", "")),
            event_id=raw_data.get("event_id", ""),
            question=raw_data.get("question", ""),
            yes_token_id=yes_token,
            no_token_id=no_token,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=float(raw_data.get("volume24hr", 0) or 0),
            end_date=_parse_end_date(raw_data),
        )
    except Exception as e:
        logger.warning(f"Failed to parse market data: {e}")
        return None

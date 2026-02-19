"""Main scanner loop for detecting arbitrage opportunities."""

import asyncio
import logging
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from src.config import get_config
from src.utils.client import PolymarketClient
from src.scanner.arbitrage import (
    ArbitrageOpportunity,
    ArbitrageScanner,
    Market,
    parse_market_data
)

logger = logging.getLogger(__name__)
console = Console()


class MarketScanner:
    """Main scanner that continuously monitors markets for opportunities."""

    def __init__(self):
        self.config = get_config()
        self.client = PolymarketClient(self.config)
        self.arb_scanner = ArbitrageScanner(
            min_spread_pct=self.config.strategy.min_spread_pct,
            min_liquidity=self.config.strategy.min_liquidity_usd
        )
        self.markets: list[Market] = []
        self.opportunities: list[ArbitrageOpportunity] = []
        self._running = False

    async def refresh_markets(self):
        """Fetch and parse all active markets."""
        logger.info("Refreshing market data...")
        
        try:
            events = await self.client.get_all_active_markets()
            
            self.markets = []
            for event in events:
                # Events contain nested markets
                raw_markets = event.get("markets", [])
                for raw_market in raw_markets:
                    raw_market["event_id"] = event.get("id", "")
                    market = parse_market_data(raw_market)
                    if market and market.yes_token_id:
                        self.markets.append(market)
            
            logger.info(f"Loaded {len(self.markets)} markets from {len(events)} events")
            
        except Exception as e:
            logger.error(f"Failed to refresh markets: {e}")

    def scan_for_opportunities(self) -> list[ArbitrageOpportunity]:
        """Run all arbitrage scans on current market data."""
        opportunities = []
        
        # Same-market arbitrage
        same_market_opps = self.arb_scanner.scan_same_market(self.markets)
        opportunities.extend(same_market_opps)
        
        # Combinatorial arbitrage (if enabled)
        if self.config.strategy.enable_combinatorial:
            combo_opps = self.arb_scanner.scan_combinatorial(self.markets, {})
            opportunities.extend(combo_opps)
        
        self.opportunities = opportunities
        return opportunities

    def display_opportunities(self, opportunities: list[ArbitrageOpportunity]):
        """Display opportunities in a nice table."""
        if not opportunities:
            console.print("[dim]No arbitrage opportunities found[/dim]")
            return
        
        table = Table(title="Arbitrage Opportunities")
        table.add_column("Type", style="cyan")
        table.add_column("Market", style="white", max_width=40)
        table.add_column("YES", style="green")
        table.add_column("NO", style="red")
        table.add_column("Combined", style="yellow")
        table.add_column("Spread %", style="bold green")
        table.add_column("Max $", style="blue")
        
        for opp in sorted(opportunities, key=lambda x: -x.spread_pct):
            table.add_row(
                opp.opportunity_type[:10],
                opp.market_question[:40] + "...",
                f"${opp.yes_price:.3f}",
                f"${opp.no_price:.3f}",
                f"${opp.combined_cost:.3f}",
                f"{opp.spread_pct:.2f}%",
                f"${opp.max_executable_usd:.0f}"
            )
        
        console.print(table)

    async def run_once(self):
        """Run a single scan cycle."""
        console.print(f"\n[bold blue]{'='*60}[/bold blue]")
        console.print(f"[bold]Scan at {datetime.now(timezone.utc).isoformat()}[/bold]")
        
        await self.refresh_markets()
        opportunities = self.scan_for_opportunities()
        self.display_opportunities(opportunities)
        
        return opportunities

    async def run(self, interval_seconds: int = None):
        """Run continuous scanning loop."""
        interval = interval_seconds or self.config.scanner.price_check_interval
        self._running = True
        
        console.print(f"[bold green]Starting scanner (interval={interval}s)[/bold green]")
        console.print(f"[dim]Min spread: {self.config.strategy.min_spread_pct}%[/dim]")
        console.print(f"[dim]Paper trading: {self.config.paper_trading}[/dim]")
        
        try:
            while self._running:
                await self.run_once()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Scanner stopped")
        finally:
            await self.client.close()

    def stop(self):
        """Stop the scanning loop."""
        self._running = False


async def main():
    """Entry point for scanner."""
    import sys
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    scanner = MarketScanner()
    
    # Check for one-shot mode
    if "--once" in sys.argv:
        await scanner.run_once()
    else:
        await scanner.run()


if __name__ == "__main__":
    asyncio.run(main())

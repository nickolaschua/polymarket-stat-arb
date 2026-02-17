#!/usr/bin/env python3
"""
Polymarket Statistical Arbitrage Bot

Main entry point for the bot.
"""

import asyncio
import logging
import sys
from typing import Optional

import click
from rich.console import Console

from src.config import get_config, reload_config
from src.utils.client import PolymarketClient
from src.scanner.main import MarketScanner

console = Console()
logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    """Configure logging."""
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        from pathlib import Path
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers
    )


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Config file path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx, config: str, verbose: bool):
    """Polymarket Statistical Arbitrage Bot"""
    ctx.ensure_object(dict)
    
    cfg = reload_config(config)
    ctx.obj["config"] = cfg
    
    log_level = "DEBUG" if verbose else cfg.logging.level
    setup_logging(log_level, cfg.logging.file)


@cli.command()
@click.option("--once", is_flag=True, help="Run single scan then exit")
@click.option("--interval", "-i", type=int, help="Scan interval in seconds")
@click.pass_context
def scan(ctx, once: bool, interval: Optional[int]):
    """Scan markets for arbitrage opportunities (read-only)."""
    
    async def run():
        scanner = MarketScanner()
        
        if once:
            await scanner.run_once()
        else:
            await scanner.run(interval_seconds=interval)
    
    asyncio.run(run())


@cli.command()
@click.option("--live", is_flag=True, help="Enable live trading (requires auth)")
@click.pass_context
def run(ctx, live: bool):
    """Run the full arbitrage bot."""
    config = ctx.obj["config"]
    
    if live and config.paper_trading:
        console.print("[yellow]Warning: --live flag set but paper_trading=true in config[/yellow]")
        console.print("[yellow]Set paper_trading: false in config.yaml to enable real trades[/yellow]")
    
    async def run_bot():
        client = PolymarketClient()
        
        # Authenticate if live trading
        if live or not config.paper_trading:
            console.print("[bold]Authenticating with Polymarket...[/bold]")
            if not client.authenticate():
                console.print("[red]Authentication failed! Check your wallet config.[/red]")
                return
            console.print("[green]✓ Authenticated[/green]")
        
        # Run scanner with trading enabled
        scanner = MarketScanner()
        # TODO: Add executor integration for auto-trading
        await scanner.run()
    
    asyncio.run(run_bot())


@cli.command()
@click.pass_context
def check(ctx):
    """Check API connectivity and configuration."""
    config = ctx.obj["config"]
    
    async def run_check():
        console.print("[bold]Polymarket Stat Arb - System Check[/bold]\n")
        
        client = PolymarketClient(config)
        
        # Test CLOB API
        console.print("Testing CLOB API...", end=" ")
        try:
            ok = client.clob.get_ok()
            server_time = client.clob.get_server_time()
            console.print(f"[green]✓[/green] (server time: {server_time})")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
        
        # Test Gamma API
        console.print("Testing Gamma API...", end=" ")
        try:
            events = await client.get_events(limit=1)
            count = len(events) if isinstance(events, list) else len(events.get("data", []))
            console.print(f"[green]✓[/green] (fetched {count} events)")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
        
        # Check wallet config
        console.print("\nWallet Configuration:")
        if config.wallet.funder_address:
            console.print(f"  Funder: {config.wallet.funder_address}")
        else:
            console.print("  [yellow]Funder address not set[/yellow]")
        
        if config.wallet.private_key:
            console.print("  Private key: [green]✓ Found in env[/green]")
        else:
            console.print(f"  Private key: [yellow]✗ Not found ({config.wallet.private_key_env})[/yellow]")
        
        # Strategy settings
        console.print("\nStrategy Settings:")
        console.print(f"  Min spread: {config.strategy.min_spread_pct}%")
        console.print(f"  Max position: ${config.strategy.max_position_usd}")
        console.print(f"  Paper trading: {config.paper_trading}")
        
        await client.close()
    
    asyncio.run(run_check())


@cli.command()
@click.pass_context
def collect(ctx):
    """Start the data collection daemon (runs all collectors 24/7)."""

    async def run_daemon():
        from pathlib import Path
        from src.db.pool import get_pool, close_pool
        from src.db.migrations.runner import run_migrations
        from src.collector.daemon import CollectorDaemon

        config = get_config()

        logger.info("Starting collector daemon...")

        # Initialize database
        pool = await get_pool()
        migrations_dir = Path(__file__).resolve().parent / "db" / "migrations"
        applied = await run_migrations(pool, migrations_dir)
        if applied:
            logger.info("Applied %d migrations", len(applied))

        # Create client and daemon
        client = PolymarketClient(config)
        daemon = CollectorDaemon(pool, client, config.collector)

        try:
            await daemon.run()
        finally:
            await close_pool()
            logger.info("Collector daemon shut down")

    asyncio.run(run_daemon())


@cli.command()
@click.argument("token_id")
@click.pass_context
def price(ctx, token_id: str):
    """Get current price for a token."""
    client = PolymarketClient()
    
    try:
        mid = client.get_midpoint(token_id)
        buy = client.get_price(token_id, "BUY")
        sell = client.get_price(token_id, "SELL")
        
        console.print(f"Token: {token_id[:20]}...")
        console.print(f"  Midpoint: ${mid}")
        console.print(f"  Buy:      ${buy}")
        console.print(f"  Sell:     ${sell}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("token_id")
@click.pass_context
def book(ctx, token_id: str):
    """Get orderbook for a token."""
    client = PolymarketClient()
    
    try:
        orderbook = client.get_orderbook(token_id)
        
        console.print(f"[bold]Orderbook for {token_id[:20]}...[/bold]\n")
        
        # Asks (sell orders)
        console.print("[red]ASKS (Sell)[/red]")
        for order in orderbook.get("asks", [])[:5]:
            console.print(f"  ${order['price']} x {order['size']}")
        
        console.print()
        
        # Bids (buy orders)
        console.print("[green]BIDS (Buy)[/green]")
        for order in orderbook.get("bids", [])[:5]:
            console.print(f"  ${order['price']} x {order['size']}")
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    cli()

"""Configuration management for Polymarket Stat Arb bot."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class PolymarketConfig(BaseModel):
    clob_host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    data_host: str = "https://data-api.polymarket.com"
    ws_host: str = "wss://ws-subscriptions-clob.polymarket.com"
    chain_id: int = 137


class WalletConfig(BaseModel):
    private_key_env: str = "POLY_PRIVATE_KEY"
    funder_address: str = ""
    signature_type: int = 0  # 0=EOA, 1=Magic, 2=Gnosis

    @property
    def private_key(self) -> Optional[str]:
        """Get private key from environment variable."""
        return os.getenv(self.private_key_env)


class RiskConfig(BaseModel):
    max_daily_loss_usd: float = 50.0
    max_drawdown_pct: float = 20.0
    max_consecutive_losses: int = 5
    circuit_breaker_state_file: str = "data/circuit_breaker_state.json"


class StrategyConfig(BaseModel):
    # Arbitrage detection
    min_spread_pct: float = 2.0
    min_liquidity_usd: float = 100.0

    # Position sizing
    max_position_usd: float = 100.0
    max_total_exposure_usd: float = 500.0
    kelly_fraction: float = 0.25

    # Execution
    slippage_tolerance_pct: float = 0.5
    order_timeout_sec: int = 30

    # Combinatorial
    enable_combinatorial: bool = True
    similarity_threshold: float = 0.8


class ScannerConfig(BaseModel):
    market_refresh_interval: int = 60
    price_check_interval: int = 5
    websocket_reconnect_delay: int = 5
    min_volume_24h: float = 1000.0
    max_days_to_resolution: int = 30


class DatabaseConfig(BaseModel):
    url: str = "postgresql://polymarket:polymarket_dev@localhost:5432/polymarket"
    min_pool_size: int = 2
    max_pool_size: int = 10
    max_inactive_connection_lifetime: float = 300.0
    command_timeout: int = 60


class CollectorConfig(BaseModel):
    price_interval_sec: int = 60
    orderbook_interval_sec: int = 300
    metadata_interval_sec: int = 300
    resolution_check_interval_sec: int = 300
    trade_buffer_size: int = 1000
    max_markets: int = 10000
    ws_ping_interval_sec: int = 10
    ws_max_instruments_per_conn: int = 500
    trade_batch_drain_timeout_sec: float = 5.0


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id: str = ""

    @property
    def bot_token(self) -> Optional[str]:
        return os.getenv(self.bot_token_env)


class AlertsConfig(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    notify_on_opportunity: bool = True
    notify_on_trade: bool = True
    notify_min_spread_pct: float = 3.0


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/bot.log"
    max_size_mb: int = 10
    backup_count: int = 5


class Config(BaseModel):
    """Main configuration class."""
    
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    wallet: WalletConfig = Field(default_factory=WalletConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paper_trading: bool = True

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        """Load configuration from YAML file."""
        config_path = Path(path)
        
        if not config_path.exists():
            # Return defaults if no config file
            return cls()
        
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        
        return cls(**data)


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or load the global configuration."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config(path: str = "config.yaml") -> Config:
    """Reload configuration from file."""
    global _config
    _config = Config.load(path)
    return _config

"""Configuration loading for Trade-bot."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml


@dataclasses.dataclass
class ModelConfig:
    id: str = "claude-fable-5"
    fallback: str = "claude-opus-4-8"
    effort_signals: str = "high"
    effort_news: str = "medium"


@dataclasses.dataclass
class AccountConfig:
    equity: float = 25000.0
    open_exposure: float = 0.0


@dataclasses.dataclass
class RiskConfig:
    max_risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0
    max_total_exposure_pct: float = 60.0
    max_drawdown_pct: float = 10.0
    max_atr_pct: float = 8.0
    max_loss_per_trade_usd: float = 500.0


@dataclasses.dataclass
class NewsConfig:
    enabled: bool = True
    max_searches: int = 3


@dataclasses.dataclass
class BrokerConfig:
    enabled: bool = False
    paper: bool = True


@dataclasses.dataclass
class Config:
    model: ModelConfig
    account: AccountConfig
    risk: RiskConfig
    news: NewsConfig
    broker: BrokerConfig
    watchlist: list[str]
    interval_minutes: int = 30


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return Config(
        model=ModelConfig(**raw.get("model", {})),
        account=AccountConfig(**raw.get("account", {})),
        risk=RiskConfig(**raw.get("risk", {})),
        news=NewsConfig(**raw.get("news", {})),
        broker=BrokerConfig(**raw.get("broker", {})),
        watchlist=[str(s).upper() for s in raw.get("watchlist", [])],
        interval_minutes=int(raw.get("monitor", {}).get("interval_minutes", 30)),
    )

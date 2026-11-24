"""Deterministic setup rules — the backtestable core of the strategy.

The LLM analyst is expensive and non-reproducible, which makes it unusable for
measuring edge across thousands of historical bars. This module encodes the
same setup logic as plain arithmetic, so the backtest can run over years of
history for free — and so the LLM's contribution can be measured against a
baseline instead of assumed.

NO LOOKAHEAD: every indicator here is a trailing window, and `detect_setup`
reads only row `i`. Anything a caller does with rows after `i` is that
caller's bug, not this module's.
"""

from __future__ import annotations

import dataclasses

import pandas as pd


@dataclasses.dataclass
class StrategyParams:
    sma_fast: int = 20
    sma_slow: int = 50
    breakout_lookback: int = 20     # prior highs the breakout must clear
    volume_mult: float = 1.2        # volume vs 20d average to confirm
    atr_period: int = 14
    stop_atr: float = 1.5           # stop distance in ATRs
    target_atr: float = 3.0         # target distance in ATRs (2:1 reward/risk)
    min_atr_pct: float = 0.5        # skip symbols too quiet to pay for the risk
    max_atr_pct: float = 8.0        # skip symbols too wild (mirrors risk engine)
    max_hold_bars: int = 20         # give up on a trade after this many bars


@dataclasses.dataclass
class Setup:
    kind: str            # "breakout" | "pullback"
    direction: str       # "long"
    confidence: str      # "high" | "medium"
    atr: float           # used to derive stop/target from the actual fill


def add_indicators(frame: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    """Attach trailing indicators. Each row only ever sees itself and the past."""
    out = frame.copy()
    close, high, low = out["Close"], out["High"], out["Low"]

    out["sma_fast"] = close.rolling(p.sma_fast).mean()
    out["sma_slow"] = close.rolling(p.sma_slow).mean()
    out["avg_volume"] = out["Volume"].rolling(p.sma_fast).mean()

    prev_close = close.shift(1)
    true_range = (high - low).combine((high - prev_close).abs(), max).combine(
        (low - prev_close).abs(), max
    )
    out["atr"] = true_range.rolling(p.atr_period).mean()
    out["atr_pct"] = out["atr"] / close * 100

    # shift(1) so the breakout level excludes today's own high.
    out["prior_high"] = high.rolling(p.breakout_lookback).max().shift(1)
    return out


def warmup_bars(p: StrategyParams) -> int:
    """Rows at the start of the frame where indicators aren't valid yet."""
    return max(p.sma_slow, p.breakout_lookback + 1, p.atr_period) + 1


def detect_setup(frame: pd.DataFrame, i: int, p: StrategyParams) -> Setup | None:
    """Look for a setup using only data up to and including row `i`."""
    if i < warmup_bars(p) or i >= len(frame):
        return None

    row = frame.iloc[i]
    if row[["sma_fast", "sma_slow", "atr", "prior_high", "avg_volume"]].isna().any():
        return None
    if not (p.min_atr_pct <= row["atr_pct"] <= p.max_atr_pct):
        return None

    trend_up = row["Close"] > row["sma_fast"] > row["sma_slow"]
    if not trend_up:
        return None

    volume_ok = row["Volume"] > p.volume_mult * row["avg_volume"]

    # Breakout: clears the prior N-bar high on expanding volume.
    if row["Close"] > row["prior_high"] and volume_ok:
        return Setup("breakout", "long", "high", float(row["atr"]))

    # Pullback: dipped to the fast average and closed back above it.
    if row["Low"] <= row["sma_fast"] < row["Close"]:
        return Setup("pullback", "long", "medium", float(row["atr"]))

    return None


def levels_from_fill(fill: float, setup: Setup, p: StrategyParams) -> tuple[float, float]:
    """Stop and target derived from the actual fill price, not the signal bar."""
    stop = fill - p.stop_atr * setup.atr
    target = fill + p.target_atr * setup.atr
    return stop, target

"""SCAN stage — market data snapshot for a symbol.

Pulls daily OHLCV via yfinance and derives the indicators the analyst and the
risk engine need: last price, volume vs average, SMA trend, and ATR volatility.
"""

from __future__ import annotations

import dataclasses

import yfinance as yf


@dataclasses.dataclass
class MarketSnapshot:
    symbol: str
    price: float
    change_1d_pct: float
    change_5d_pct: float
    change_20d_pct: float
    volume: float
    avg_volume_20d: float
    volume_ratio: float          # today's volume / 20d average
    sma_20: float
    sma_50: float
    trend: str                   # "up" | "down" | "sideways"
    atr_14: float
    atr_pct: float               # ATR as % of price
    high_52w: float
    low_52w: float

    def summary(self) -> str:
        """Compact plain-text summary passed to the analyst."""
        return (
            f"{self.symbol}: price {self.price:.2f} "
            f"({self.change_1d_pct:+.2f}% 1d, {self.change_5d_pct:+.2f}% 5d, "
            f"{self.change_20d_pct:+.2f}% 20d), "
            f"volume {self.volume:,.0f} ({self.volume_ratio:.2f}x 20d avg), "
            f"SMA20 {self.sma_20:.2f}, SMA50 {self.sma_50:.2f}, trend {self.trend}, "
            f"ATR14 {self.atr_14:.2f} ({self.atr_pct:.2f}% of price), "
            f"52w range {self.low_52w:.2f}-{self.high_52w:.2f}"
        )


def fetch_snapshot(symbol: str) -> MarketSnapshot:
    """Fetch ~1 year of daily bars and compute the snapshot.

    Raises ValueError when the symbol returns no data.
    """
    hist = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty or len(hist) < 60:
        raise ValueError(f"insufficient price history for {symbol}")

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    price = float(close.iloc[-1])
    sma_20 = float(close.rolling(20).mean().iloc[-1])
    sma_50 = float(close.rolling(50).mean().iloc[-1])

    if price > sma_20 > sma_50:
        trend = "up"
    elif price < sma_20 < sma_50:
        trend = "down"
    else:
        trend = "sideways"

    prev_close = close.shift(1)
    true_range = (high - low).combine((high - prev_close).abs(), max).combine(
        (low - prev_close).abs(), max
    )
    atr_14 = float(true_range.rolling(14).mean().iloc[-1])

    avg_volume_20d = float(volume.rolling(20).mean().iloc[-1])

    def pct_change(days: int) -> float:
        return float((close.iloc[-1] / close.iloc[-1 - days] - 1) * 100)

    return MarketSnapshot(
        symbol=symbol,
        price=price,
        change_1d_pct=pct_change(1),
        change_5d_pct=pct_change(5),
        change_20d_pct=pct_change(20),
        volume=float(volume.iloc[-1]),
        avg_volume_20d=avg_volume_20d,
        volume_ratio=float(volume.iloc[-1]) / avg_volume_20d if avg_volume_20d else 0.0,
        sma_20=sma_20,
        sma_50=sma_50,
        trend=trend,
        atr_14=atr_14,
        atr_pct=atr_14 / price * 100 if price else 0.0,
        high_52w=float(high.max()),
        low_52w=float(low.min()),
    )

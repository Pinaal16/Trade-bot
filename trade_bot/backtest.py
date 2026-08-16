"""Backtest engine — measures whether the strategy actually has an edge.

Design decisions that keep the result honest:

  * No lookahead. A signal on bar i is filled at the OPEN of bar i+1. You
    cannot trade a close you have only just observed.
  * Pessimistic intrabar assumption. If a bar's range covers both the stop and
    the target, the stop is taken. Daily bars can't tell you which came first,
    so assume the worse one.
  * Gaps are honoured. If a bar opens through the stop, you exit at the open,
    not at the stop price. This is where real money actually leaks.
  * Slippage on both sides, configurable.
  * Portfolio-level capital. One position per symbol at a time, exposure caps
    enforced, and position sizing uses the SAME code as live trading.
  * Buy-and-hold benchmark. If the strategy can't beat holding the same
    symbols, it isn't a business.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pandas as pd

from .config import RiskConfig
from .risk import size_position
from .strategy import (
    Setup, StrategyParams, add_indicators, detect_setup, levels_from_fill,
    warmup_bars,
)


@dataclasses.dataclass
class Trade:
    symbol: str
    kind: str
    entry_date: dt.date
    entry_price: float
    shares: int
    stop: float
    target: float
    exit_date: dt.date
    exit_price: float
    outcome: str          # "target" | "stop" | "timeout"
    pnl: float
    r_multiple: float     # pnl measured in units of initial risk


@dataclasses.dataclass
class Metrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float          # average $ per trade
    expectancy_r: float        # average R per trade
    profit_factor: float
    total_pnl: float
    return_pct: float
    max_drawdown_pct: float
    buy_hold_pct: float
    start_equity: float
    end_equity: float


def _resolve_exit(frame: pd.DataFrame, entry_i: int, stop: float, target: float,
                  max_hold: int, slippage_bps: float) -> tuple[int, float, str]:
    """Walk forward from the entry bar to find where the bracket order exits."""
    slip = slippage_bps / 10_000
    last = min(entry_i + max_hold, len(frame) - 1)

    for j in range(entry_i, last + 1):
        bar = frame.iloc[j]
        # Gaps first: an open through a level fills at the open, not the level.
        if bar["Open"] <= stop:
            return j, float(bar["Open"]) * (1 - slip), "stop"
        if bar["Open"] >= target:
            return j, float(bar["Open"]) * (1 - slip), "target"
        # Intrabar: assume the stop is hit first when the bar spans both.
        if bar["Low"] <= stop:
            return j, stop * (1 - slip), "stop"
        if bar["High"] >= target:
            return j, target * (1 - slip), "target"

    return last, float(frame.iloc[last]["Close"]) * (1 - slip), "timeout"


def _candidates(symbol: str, frame: pd.DataFrame, p: StrategyParams,
                slippage_bps: float) -> list[dict]:
    """Every signal this symbol produced, with its outcome path resolved.

    Outcomes don't depend on position size, so they can be precomputed and the
    capital simulation applied afterwards.
    """
    frame = add_indicators(frame, p)
    out: list[dict] = []

    for i in range(warmup_bars(p), len(frame) - 1):
        setup: Setup | None = detect_setup(frame, i, p)
        if setup is None:
            continue

        entry_i = i + 1                        # fill at the NEXT bar's open
        fill = float(frame.iloc[entry_i]["Open"]) * (1 + slippage_bps / 10_000)
        stop, target = levels_from_fill(fill, setup, p)
        if stop >= fill:
            continue

        exit_i, exit_price, outcome = _resolve_exit(
            frame, entry_i, stop, target, p.max_hold_bars, slippage_bps
        )
        out.append({
            "symbol": symbol, "kind": setup.kind,
            "signal_i": i, "entry_i": entry_i, "exit_i": exit_i,
            "entry_date": frame.index[entry_i], "exit_date": frame.index[exit_i],
            "entry": fill, "exit": exit_price, "stop": stop, "target": target,
            "outcome": outcome,
        })
    return out


def run_backtest(history: dict[str, pd.DataFrame], risk: RiskConfig,
                 params: StrategyParams | None = None,
                 start_equity: float = 10_000.0,
                 slippage_bps: float = 5.0) -> tuple[list[Trade], Metrics]:
    """Simulate the strategy across symbols with shared capital."""
    p = params or StrategyParams()

    signals: list[dict] = []
    for symbol, frame in history.items():
        if frame is None or len(frame) < warmup_bars(p) + 5:
            continue
        signals.extend(_candidates(symbol, frame, p, slippage_bps))
    signals.sort(key=lambda s: s["entry_date"])

    equity = start_equity
    peak = start_equity
    max_dd = 0.0
    trades: list[Trade] = []
    busy_until: dict[str, object] = {}    # one position per symbol at a time
    open_value = 0.0
    closed: list[dict] = []

    for sig in signals:
        # Release capital from positions that closed before this entry.
        still_open = []
        for pos in closed:
            if pos["exit_date"] <= sig["entry_date"]:
                equity += pos["pnl"]
                open_value -= pos["value"]
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)
            else:
                still_open.append(pos)
        closed = still_open

        held_until = busy_until.get(sig["symbol"])
        if held_until is not None and held_until > sig["entry_date"]:
            continue   # already holding this symbol

        shares, _ = size_position(equity, sig["entry"], sig["stop"], risk)
        if shares < 1:
            continue

        value = shares * sig["entry"]
        if open_value + value > equity * risk.max_total_exposure_pct / 100:
            continue   # would breach the exposure cap

        per_share_risk = sig["entry"] - sig["stop"]
        pnl = (sig["exit"] - sig["entry"]) * shares
        trades.append(Trade(
            symbol=sig["symbol"], kind=sig["kind"],
            entry_date=sig["entry_date"], entry_price=sig["entry"],
            shares=shares, stop=sig["stop"], target=sig["target"],
            exit_date=sig["exit_date"], exit_price=sig["exit"],
            outcome=sig["outcome"], pnl=pnl,
            r_multiple=pnl / (per_share_risk * shares) if per_share_risk else 0.0,
        ))
        busy_until[sig["symbol"]] = sig["exit_date"]
        open_value += value
        closed.append({"exit_date": sig["exit_date"], "pnl": pnl, "value": value})

    for pos in closed:      # settle anything still open at the end
        equity += pos["pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)

    return trades, _metrics(trades, history, start_equity, equity, max_dd)


def _metrics(trades: list[Trade], history: dict[str, pd.DataFrame],
             start_equity: float, end_equity: float, max_dd: float) -> Metrics:
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))

    # Equal-weight buy and hold over the same period, as the benchmark.
    holds = []
    for frame in history.values():
        if frame is not None and len(frame) > 1:
            first, last = float(frame["Close"].iloc[0]), float(frame["Close"].iloc[-1])
            if first > 0:
                holds.append((last / first - 1) * 100)
    buy_hold = sum(holds) / len(holds) if holds else 0.0

    n = len(trades)
    return Metrics(
        trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / n * 100 if n else 0.0,
        avg_win=gross_win / len(wins) if wins else 0.0,
        avg_loss=gross_loss / len(losses) if losses else 0.0,
        expectancy=sum(t.pnl for t in trades) / n if n else 0.0,
        expectancy_r=sum(t.r_multiple for t in trades) / n if n else 0.0,
        profit_factor=gross_win / gross_loss if gross_loss else float("inf") if gross_win else 0.0,
        total_pnl=end_equity - start_equity,
        return_pct=(end_equity / start_equity - 1) * 100 if start_equity else 0.0,
        max_drawdown_pct=max_dd,
        buy_hold_pct=buy_hold,
        start_equity=start_equity,
        end_equity=end_equity,
    )


def verdict(m: Metrics) -> tuple[str, list[str]]:
    """Turn the numbers into a go / no-go call with the reasoning shown."""
    notes: list[str] = []

    if m.trades < 30:
        notes.append(f"Only {m.trades} trades — too few to conclude anything. "
                     "Widen the symbol list or lengthen the period.")
        return "INSUFFICIENT DATA", notes

    if m.expectancy_r <= 0:
        notes.append(f"Expectancy is {m.expectancy_r:+.3f}R per trade — you lose "
                     "money on average. Do not trade this.")
        return "NO EDGE", notes

    notes.append(f"Expectancy {m.expectancy_r:+.3f}R (${m.expectancy:+,.2f}) per trade.")

    if m.profit_factor < 1.2:
        notes.append(f"Profit factor {m.profit_factor:.2f} is too thin to survive "
                     "costs and slippage in the real world.")
        return "MARGINAL", notes

    if m.return_pct <= m.buy_hold_pct:
        notes.append(f"Strategy returned {m.return_pct:+.1f}% vs {m.buy_hold_pct:+.1f}% "
                     "for simply holding the same symbols — the work isn't paying.")
        return "UNDERPERFORMS BUY & HOLD", notes

    notes.append(f"Beats buy & hold ({m.return_pct:+.1f}% vs {m.buy_hold_pct:+.1f}%) "
                 f"with profit factor {m.profit_factor:.2f} and "
                 f"{m.max_drawdown_pct:.1f}% max drawdown.")
    return "PROMISING", notes


def format_report(trades: list[Trade], m: Metrics, symbols: list[str],
                  years: float) -> str:
    call, notes = verdict(m)
    by_kind: dict[str, list[Trade]] = {}
    for t in trades:
        by_kind.setdefault(t.kind, []).append(t)

    lines = [
        "",
        "=" * 62,
        f"  BACKTEST — {len(symbols)} symbols, {years:.1f} years",
        "=" * 62,
        "",
        f"  Trades            {m.trades}",
        f"  Win rate          {m.win_rate:.1f}%  ({m.wins}W / {m.losses}L)",
        f"  Average win       ${m.avg_win:,.2f}",
        f"  Average loss      ${m.avg_loss:,.2f}",
        f"  Expectancy        {m.expectancy_r:+.3f}R  (${m.expectancy:+,.2f} per trade)",
        f"  Profit factor     {m.profit_factor:.2f}",
        "",
        f"  Start equity      ${m.start_equity:,.2f}",
        f"  End equity        ${m.end_equity:,.2f}",
        f"  Return            {m.return_pct:+.1f}%",
        f"  Buy & hold        {m.buy_hold_pct:+.1f}%   <- the benchmark to beat",
        f"  Max drawdown      {m.max_drawdown_pct:.1f}%",
        "",
    ]

    if by_kind:
        lines.append("  By setup type:")
        for kind, group in sorted(by_kind.items()):
            w = sum(1 for t in group if t.pnl > 0)
            exp = sum(t.r_multiple for t in group) / len(group)
            lines.append(f"    {kind:<12} {len(group):>4} trades, "
                         f"{w / len(group) * 100:5.1f}% win, {exp:+.3f}R")
        lines.append("")

    lines += [f"  VERDICT: {call}", ""]
    lines += [f"    - {n}" for n in notes]
    lines += [
        "",
        "  Backtests are optimistic by nature: no emotions, perfect discipline,",
        "  and survivorship bias in whichever symbols you chose. Treat a good",
        "  result as permission to paper trade, not permission to go all in.",
        "=" * 62,
        "",
    ]
    return "\n".join(lines)

"""Backtest CLI — find out whether the strategy has an edge before risking money.

  python backtest.py                       # watchlist, 2 years
  python backtest.py --years 5             # longer history
  python backtest.py --symbols NVDA,AAPL   # specific symbols
  python backtest.py --universe sp100      # broader universe, more signals
  python backtest.py --equity 1500         # simulate your actual account size
  python backtest.py --trades trades.csv   # dump every trade for inspection
"""

from __future__ import annotations

import argparse
import csv
import dataclasses

from trade_bot.backtest import format_report, run_backtest
from trade_bot.config import load_config
from trade_bot.market_data import fetch_history
from trade_bot.strategy import StrategyParams

# A liquid, sector-spread sample. More symbols means more signals, which is
# what you need for the result to mean anything.
SP100_SAMPLE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "UNH", "XOM", "MA", "PG", "JNJ", "HD", "COST", "MRK", "ABBV", "CVX",
    "CRM", "AMD", "PEP", "KO", "ADBE", "WMT", "MCD", "CSCO", "ACN", "LIN",
    "TMO", "ABT", "ORCL", "DIS", "INTC", "QCOM", "TXN", "CAT", "GE", "BA",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest the trading strategy")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--symbols", help="comma-separated list (overrides watchlist)")
    parser.add_argument("--universe", choices=["watchlist", "sp100"], default="watchlist")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--equity", type=float, help="starting equity (default: config account equity)")
    parser.add_argument("--slippage-bps", type=float, default=5.0,
                        help="slippage per side in basis points (default 5)")
    parser.add_argument("--trades", help="write every trade to this CSV")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.universe == "sp100":
        symbols = SP100_SAMPLE
    else:
        symbols = config.watchlist

    print(f"Downloading {args.years:.0f}y of daily bars for {len(symbols)} symbols...")
    history = {}
    for i, symbol in enumerate(symbols, 1):
        try:
            frame = fetch_history(symbol, args.years)
        except Exception as exc:
            print(f"  [{i}/{len(symbols)}] {symbol}: failed ({exc})")
            continue
        if frame is None:
            print(f"  [{i}/{len(symbols)}] {symbol}: not enough history, skipped")
            continue
        history[symbol] = frame
        print(f"  [{i}/{len(symbols)}] {symbol}: {len(frame)} bars")

    if not history:
        print("\nNo usable price history — nothing to test.")
        return 1

    start_equity = args.equity if args.equity else config.account.equity
    trades, metrics = run_backtest(
        history, config.risk, StrategyParams(),
        start_equity=start_equity, slippage_bps=args.slippage_bps,
    )

    print(format_report(trades, metrics, list(history), args.years))

    if args.trades:
        with open(args.trades, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[f.name for f in dataclasses.fields(trades[0])] if trades else ["symbol"])
            writer.writeheader()
            for t in trades:
                writer.writerow(dataclasses.asdict(t))
        print(f"  Wrote {len(trades)} trades to {args.trades}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

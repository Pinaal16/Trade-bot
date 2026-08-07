"""Trade-bot CLI — AI trading research assistant (Claude Fable 5).

Usage:
  python main.py                 # one pipeline pass over the watchlist
  python main.py --loop          # 24/7 monitoring loop
  python main.py --symbol NVDA   # scan a single symbol
  python main.py --no-news       # skip the web-search news step
"""

from __future__ import annotations

import argparse
import os
import sys

from trade_bot.config import load_config
from trade_bot.monitor import monitor
from trade_bot.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="AI trading research assistant")
    parser.add_argument("--config", default="config.yaml", help="path to config file")
    parser.add_argument("--symbol", action="append", help="scan specific symbol(s) instead of the watchlist")
    parser.add_argument("--loop", action="store_true", help="run the 24/7 monitoring loop")
    parser.add_argument("--no-news", action="store_true", help="skip the news scan (no web search)")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print("Note: no ANTHROPIC_API_KEY set — the SDK will fall back to an "
              "`ant auth login` profile if one exists.", file=sys.stderr)

    config = load_config(args.config)
    news_enabled = False if args.no_news else None

    if args.symbol:
        symbols = [s.upper() for s in args.symbol]
        run_pipeline(config, symbols=symbols, news_enabled=news_enabled)
    elif args.loop:
        monitor(config, news_enabled=news_enabled)
    else:
        run_pipeline(config, news_enabled=news_enabled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

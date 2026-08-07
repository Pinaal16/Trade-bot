"""MONITOR stage — 24/7 loop around the pipeline."""

from __future__ import annotations

import datetime
import time

from .config import Config
from .pipeline import run_pipeline


def monitor(config: Config, news_enabled: bool | None = None, broker=None,
            approver=None) -> None:
    interval = config.interval_minutes * 60
    print(f"👀 Monitoring {len(config.watchlist)} symbols every "
          f"{config.interval_minutes} minutes. Ctrl-C to stop.")
    while True:
        started = datetime.datetime.now(datetime.timezone.utc)
        print(f"\n===== Pass started {started.isoformat(timespec='seconds')} =====")
        try:
            run_pipeline(config, news_enabled=news_enabled, broker=broker,
                         approver=approver)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"⚠️  Pass failed, will retry next interval: {exc}")
        print(f"\n⏰ Next pass in {config.interval_minutes} minutes.")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            return

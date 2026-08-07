"""Pipeline orchestration — SCAN → SIGNALS → PLAN → RISK → DECISION.

Runs the full workflow for each watchlist symbol and writes a JSON report.
"""

from __future__ import annotations

import datetime
import json
import traceback
from pathlib import Path

from .analyst import Analyst, RefusalError
from .config import Config
from .decision import Decision, decide
from .market_data import fetch_snapshot
from .risk import RiskEngine

REPORTS_DIR = Path("reports")


def run_pipeline(config: Config, symbols: list[str] | None = None,
                 news_enabled: bool | None = None) -> list[Decision]:
    symbols = symbols or config.watchlist
    use_news = config.news.enabled if news_enabled is None else news_enabled

    analyst = Analyst(config.model)
    risk_engine = RiskEngine(config.risk, config.account)

    results: list[dict] = []
    decisions: list[Decision] = []

    for symbol in symbols:
        print(f"\n🔍 Scanning {symbol}...")
        entry: dict = {"symbol": symbol}
        try:
            snapshot = fetch_snapshot(symbol)
            entry["snapshot"] = snapshot.summary()
            print(f"   {snapshot.summary()}")

            news = None
            if use_news:
                print("   📰 Checking news...")
                news = analyst.scan_news(symbol, config.news.max_searches)
                entry["news"] = news

            print("   📡 Analyzing for setups...")
            plan = analyst.build_plan(snapshot, news)
            entry["plan"] = plan

            risk = None
            if plan.get("has_setup") and plan.get("direction") != "none":
                print("   🛡️ Running risk checks...")
                risk = risk_engine.evaluate(plan, snapshot)
                entry["risk"] = risk.to_dict()

            decision = decide(symbol, plan, risk)
        except RefusalError as exc:
            decision = Decision(symbol, "NO_SETUP", f"analysis declined: {exc}")
        except Exception as exc:  # keep the loop alive for the other symbols
            traceback.print_exc()
            decision = Decision(symbol, "NO_SETUP", f"error: {exc}")

        entry["decision"] = {"verdict": decision.verdict, "reason": decision.reason}
        results.append(entry)
        decisions.append(decision)
        print(f"   {decision.line()}")

    report_path = _write_report(results)
    print(f"\n📝 Report written to {report_path}")
    print("\n=== DECISIONS ===")
    for decision in decisions:
        print(decision.line())
    print("\n⚠️  Human review required. Research output only — not financial advice.")
    return decisions


def _write_report(results: list[dict]) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"scan-{stamp}.json"
    path.write_text(json.dumps(results, indent=2))
    return path

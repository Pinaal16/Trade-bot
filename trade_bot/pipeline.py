"""Pipeline orchestration — SCAN → SIGNALS → PLAN → RISK → DECISION.

Runs the full workflow for each watchlist symbol and writes a JSON report.
"""

from __future__ import annotations

import datetime
import json
import traceback
from pathlib import Path

from .analyst import Analyst, RefusalError
from .broker import AlpacaBroker
from .config import Config
from .decision import APPROVED, Decision, decide
from .market_data import fetch_snapshot
from .risk import RiskEngine

REPORTS_DIR = Path("reports")


def run_pipeline(config: Config, symbols: list[str] | None = None,
                 news_enabled: bool | None = None,
                 broker: AlpacaBroker | None = None) -> list[Decision]:
    symbols = symbols or config.watchlist
    use_news = config.news.enabled if news_enabled is None else news_enabled

    if broker:
        # Size positions from the real account, not the config defaults.
        equity, exposure = broker.account_state()
        config.account.equity = equity
        config.account.open_exposure = exposure
        mode = "PAPER" if broker.paper else "LIVE"
        print(f"💼 {mode} account: equity ${equity:,.2f}, open exposure ${exposure:,.2f}")

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
        print(f"   {decision.line()}")

        if broker and decision.verdict == APPROVED:
            order_id = _approve_and_execute(broker, symbol, entry["plan"], entry["risk"])
            entry["order_id"] = order_id

        results.append(entry)
        decisions.append(decision)

    report_path = _write_report(results)
    print(f"\n📝 Report written to {report_path}")
    print("\n=== DECISIONS ===")
    for decision in decisions:
        print(decision.line())
    print("\n⚠️  Human review required. Research output only — not financial advice.")
    return decisions


def _approve_and_execute(broker: AlpacaBroker, symbol: str,
                         plan: dict, risk: dict) -> str | None:
    """Show the full trade and ask for explicit approval before submitting."""
    mode = "PAPER" if broker.paper else "⚠️ LIVE"
    print(f"\n   ── Trade proposal ({mode}) ─────────────────")
    print(f"   {symbol} {plan['direction'].upper()} — {plan.get('setup_type')}")
    print(f"   Entry {plan['entry']}, target {plan['target']}, stop {plan['stop']}")
    print(f"   Size: {risk['shares']} shares (~${risk['position_value']:,.0f}), "
          f"max loss at stop ${risk['dollar_risk']:,.0f}")
    print(f"   Invalidation: {plan.get('invalidation')}")
    print(f"   Why: {plan.get('rationale')}")
    try:
        answer = input("   Approve this trade? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        print("   ⏭️  Skipped — no order placed.")
        return None
    try:
        order_id = broker.place_bracket(
            symbol=symbol, qty=risk["shares"], direction=plan["direction"],
            entry=plan["entry"], target=plan["target"], stop=plan["stop"],
        )
        print(f"   📬 Bracket order submitted (id {order_id}) — "
              "entry + take-profit + stop-loss all attached.")
        return order_id
    except Exception as exc:
        print(f"   ⚠️  Order failed: {exc}")
        return None


def _write_report(results: list[dict]) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"scan-{stamp}.json"
    path.write_text(json.dumps(results, indent=2))
    return path

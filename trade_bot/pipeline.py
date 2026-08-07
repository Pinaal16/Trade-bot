"""Pipeline orchestration — SCAN → SIGNALS → PLAN → RISK → DECISION.

Runs the full workflow for each watchlist symbol and writes a JSON report.

Approval is pluggable: the CLI passes a console y/N prompt, the web dashboard
passes nothing and instead surfaces the proposal for a button click. Either
way no order is ever placed without an explicit human "yes".
"""

from __future__ import annotations

import datetime
import json
import traceback
from pathlib import Path
from typing import Callable

from .analyst import Analyst, RefusalError
from .broker import AlpacaBroker
from .config import Config
from .decision import APPROVED, Decision, decide
from .market_data import fetch_snapshot
from .risk import RiskEngine

REPORTS_DIR = Path("reports")

# (symbol, plan, risk) -> True to place the order
Approver = Callable[[str, dict, dict], bool]
# free-text status line for live UIs
Progress = Callable[[str], None]


def run_pipeline(config: Config, symbols: list[str] | None = None,
                 news_enabled: bool | None = None,
                 broker: AlpacaBroker | None = None,
                 approver: Approver | None = None,
                 progress: Progress | None = None) -> list[dict]:
    """Run the full pipeline and return one result dict per symbol."""
    symbols = symbols or config.watchlist
    use_news = config.news.enabled if news_enabled is None else news_enabled

    def report(message: str) -> None:
        print(message)
        if progress:
            progress(message)

    if broker:
        # Size positions from the real account, not the config defaults.
        equity, exposure = broker.account_state()
        config.account.equity = equity
        config.account.open_exposure = exposure
        mode = "PAPER" if broker.paper else "LIVE"
        report(f"💼 {mode} account: equity ${equity:,.2f}, open exposure ${exposure:,.2f}")

    analyst = Analyst(config.model)
    risk_engine = RiskEngine(config.risk, config.account)

    results: list[dict] = []

    for symbol in symbols:
        report(f"🔍 Scanning {symbol}...")
        entry: dict = {"symbol": symbol}
        try:
            snapshot = fetch_snapshot(symbol)
            entry["snapshot"] = snapshot.summary()

            news = None
            if use_news:
                report(f"📰 {symbol}: checking news...")
                news = analyst.scan_news(symbol, config.news.max_searches)
                entry["news"] = news

            report(f"📡 {symbol}: analyzing for setups...")
            plan = analyst.build_plan(snapshot, news)
            entry["plan"] = plan

            risk = None
            if plan.get("has_setup") and plan.get("direction") != "none":
                report(f"🛡️ {symbol}: running risk checks...")
                risk = risk_engine.evaluate(plan, snapshot)
                entry["risk"] = risk.to_dict()

            decision = decide(symbol, plan, risk)
        except RefusalError as exc:
            decision = Decision(symbol, "NO_SETUP", f"analysis declined: {exc}")
        except Exception as exc:  # keep the loop alive for the other symbols
            traceback.print_exc()
            decision = Decision(symbol, "NO_SETUP", f"error: {exc}")

        entry["decision"] = {"verdict": decision.verdict, "reason": decision.reason}
        report(decision.line())

        if broker and decision.verdict == APPROVED:
            if approver:
                entry["order_id"] = _approve_and_execute(
                    broker, symbol, entry["plan"], entry["risk"], approver
                )
            else:
                # No approver attached (web dashboard): leave it pending so a
                # human can approve it from the UI.
                entry["pending_approval"] = True

        results.append(entry)

    report(f"📝 Report written to {_write_report(results)}")
    report("⚠️ Human review required. Research output only — not financial advice.")
    return results


def console_approver(paper: bool) -> Approver:
    """Approval prompt for the terminal."""
    def ask(symbol: str, plan: dict, risk: dict) -> bool:
        mode = "PAPER" if paper else "⚠️ LIVE"
        print(f"\n   ── Trade proposal ({mode}) ─────────────────")
        print(f"   {symbol} {plan['direction'].upper()} — {plan.get('setup_type')}")
        print(f"   Entry {plan['entry']}, target {plan['target']}, stop {plan['stop']}")
        print(f"   Size: {risk['shares']} shares (~${risk['position_value']:,.0f}), "
              f"max loss at stop ${risk['dollar_risk']:,.0f}")
        print(f"   Invalidation: {plan.get('invalidation')}")
        print(f"   Why: {plan.get('rationale')}")
        try:
            return input("   Approve this trade? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            return False
    return ask


def place_order(broker: AlpacaBroker, symbol: str, plan: dict, risk: dict) -> str:
    """Submit the bracket order for an approved plan. Raises on failure."""
    return broker.place_bracket(
        symbol=symbol, qty=risk["shares"], direction=plan["direction"],
        entry=plan["entry"], target=plan["target"], stop=plan["stop"],
    )


def _approve_and_execute(broker: AlpacaBroker, symbol: str, plan: dict,
                         risk: dict, approver: Approver) -> str | None:
    if not approver(symbol, plan, risk):
        print("   ⏭️  Skipped — no order placed.")
        return None
    try:
        order_id = place_order(broker, symbol, plan, risk)
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

"""DECISION stage — combine the trade plan and the risk verdict.

Simple, auditable rules:
  - no setup                      -> NO_SETUP
  - any risk check failed         -> REJECTED
  - risk passed, high confidence  -> APPROVED
  - risk passed, lower confidence -> WATCHLIST
"""

from __future__ import annotations

import dataclasses

from .risk import RiskVerdict

APPROVED = "APPROVED"
WATCHLIST = "WATCHLIST"
REJECTED = "REJECTED"
NO_SETUP = "NO_SETUP"

_EMOJI = {APPROVED: "✅", WATCHLIST: "👁️", REJECTED: "❌", NO_SETUP: "➖"}


@dataclasses.dataclass
class Decision:
    symbol: str
    verdict: str
    reason: str

    def line(self) -> str:
        return f"{_EMOJI[self.verdict]} {self.symbol}: {self.verdict} — {self.reason}"


def decide(symbol: str, plan: dict, risk: RiskVerdict | None) -> Decision:
    if not plan.get("has_setup") or plan.get("direction") == "none":
        return Decision(symbol, NO_SETUP, plan.get("rationale", "no actionable setup"))

    if risk is None or not risk.passed:
        failures = "; ".join(risk.failures()) if risk else "risk evaluation unavailable"
        return Decision(symbol, REJECTED, f"risk checks failed: {failures}")

    if plan.get("confidence") == "high" and plan.get("risk_level") in ("low", "medium"):
        return Decision(
            symbol, APPROVED,
            f"{plan.get('setup_type')} ({plan.get('direction')}), "
            f"{risk.shares} shares, risking ${risk.dollar_risk:,.0f} — pending human review",
        )

    return Decision(
        symbol, WATCHLIST,
        f"{plan.get('setup_type')} ({plan.get('direction')}) — "
        f"confidence {plan.get('confidence')}, risk level {plan.get('risk_level')}",
    )

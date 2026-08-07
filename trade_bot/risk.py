"""RISK stage — deterministic risk engine.

Pure Python, no LLM. Given a trade plan and a market snapshot, it sizes the
position and runs the five checks from the workflow: position size, total
exposure, drawdown, volatility, and maximum loss. Any hard failure blocks
approval.
"""

from __future__ import annotations

import dataclasses

from .config import AccountConfig, RiskConfig
from .market_data import MarketSnapshot


@dataclasses.dataclass
class RiskCheck:
    name: str
    passed: bool
    detail: str


@dataclasses.dataclass
class RiskVerdict:
    passed: bool
    checks: list[RiskCheck]
    shares: int = 0
    position_value: float = 0.0
    dollar_risk: float = 0.0     # loss if the stop is hit

    def failures(self) -> list[str]:
        return [c.detail for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "shares": self.shares,
            "position_value": round(self.position_value, 2),
            "dollar_risk": round(self.dollar_risk, 2),
            "checks": [dataclasses.asdict(c) for c in self.checks],
        }


class RiskEngine:
    def __init__(self, risk: RiskConfig, account: AccountConfig, peak_equity: float | None = None):
        self.risk = risk
        self.account = account
        # Peak equity drives the drawdown check; defaults to current equity
        # when no history is tracked yet.
        self.peak_equity = peak_equity or account.equity

    def evaluate(self, plan: dict, snapshot: MarketSnapshot) -> RiskVerdict:
        checks: list[RiskCheck] = []
        entry = plan.get("entry")
        stop = plan.get("stop")

        if not entry or not stop or entry == stop:
            return RiskVerdict(
                passed=False,
                checks=[RiskCheck("plan_prices", False, "plan is missing usable entry/stop prices")],
            )

        equity = self.account.equity
        per_share_risk = abs(entry - stop)

        # Position sizing: risk a fixed % of equity between entry and stop,
        # capped by the absolute per-trade loss limit.
        risk_budget = min(
            equity * self.risk.max_risk_per_trade_pct / 100,
            self.risk.max_loss_per_trade_usd,
        )
        shares = int(risk_budget // per_share_risk)
        position_value = shares * entry
        dollar_risk = shares * per_share_risk

        if shares < 1:
            checks.append(RiskCheck(
                "position_size", False,
                f"stop distance {per_share_risk:.2f} too wide for risk budget ${risk_budget:.0f} (0 shares)",
            ))
        else:
            max_position_value = equity * self.risk.max_position_pct / 100
            if position_value > max_position_value:
                # Shrink to the position cap rather than failing outright.
                shares = int(max_position_value // entry)
                position_value = shares * entry
                dollar_risk = shares * per_share_risk
            checks.append(RiskCheck(
                "position_size", shares >= 1,
                f"{shares} shares (~${position_value:,.0f}, {position_value / equity * 100:.1f}% of equity)",
            ))

        exposure_after = self.account.open_exposure + position_value
        max_exposure = equity * self.risk.max_total_exposure_pct / 100
        checks.append(RiskCheck(
            "total_exposure", exposure_after <= max_exposure,
            f"exposure after entry ${exposure_after:,.0f} vs cap ${max_exposure:,.0f}",
        ))

        drawdown_pct = (self.peak_equity - equity) / self.peak_equity * 100 if self.peak_equity else 0.0
        checks.append(RiskCheck(
            "drawdown", drawdown_pct <= self.risk.max_drawdown_pct,
            f"current drawdown {drawdown_pct:.1f}% vs limit {self.risk.max_drawdown_pct:.1f}%",
        ))

        checks.append(RiskCheck(
            "volatility", snapshot.atr_pct <= self.risk.max_atr_pct,
            f"ATR {snapshot.atr_pct:.2f}% of price vs limit {self.risk.max_atr_pct:.1f}%",
        ))

        checks.append(RiskCheck(
            "max_loss", dollar_risk <= self.risk.max_loss_per_trade_usd,
            f"loss at stop ${dollar_risk:,.0f} vs limit ${self.risk.max_loss_per_trade_usd:,.0f}",
        ))

        return RiskVerdict(
            passed=all(c.passed for c in checks),
            checks=checks,
            shares=shares,
            position_value=position_value,
            dollar_risk=dollar_risk,
        )

"""Broker integration — Alpaca, paper trading by default.

Used only when trading mode is enabled. Every order is a bracket order that
carries the plan's target (take-profit) and stop (stop-loss), so the maximum
loss is fixed at submission time. Nothing is submitted without explicit
interactive approval in the pipeline.
"""

from __future__ import annotations

import os


class BrokerError(RuntimeError):
    pass


class AlpacaBroker:
    def __init__(self, paper: bool = True):
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise BrokerError(
                "alpaca-py is not installed — run: pip install alpaca-py"
            ) from exc

        key = os.environ.get("ALPACA_API_KEY")
        secret = os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise BrokerError(
                "set ALPACA_API_KEY and ALPACA_SECRET_KEY (free keys at alpaca.markets; "
                "use the paper-trading keys to start)"
            )
        self.paper = paper
        self.client = TradingClient(key, secret, paper=paper)

    def account_state(self) -> tuple[float, float]:
        """Return (equity, open_exposure) from the live account, so position
        sizing always uses real numbers instead of the config defaults."""
        acct = self.client.get_account()
        equity = float(acct.equity)
        exposure = abs(float(acct.long_market_value)) + abs(float(acct.short_market_value))
        return equity, exposure

    def account_summary(self) -> dict:
        """Richer account view for the dashboard."""
        acct = self.client.get_account()
        return {
            "mode": "PAPER" if self.paper else "LIVE",
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "last_equity": float(acct.last_equity),
            "day_pl": float(acct.equity) - float(acct.last_equity),
        }

    def positions(self) -> list[dict]:
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price or 0),
                "market_value": float(p.market_value or 0),
                "unrealized_pl": float(p.unrealized_pl or 0),
                "unrealized_pl_pct": float(p.unrealized_plpc or 0) * 100,
            }
            for p in self.client.get_all_positions()
        ]

    def open_orders(self) -> list[dict]:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        orders = self.client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=50)
        )
        return [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "side": str(getattr(o.side, "value", o.side)),
                "qty": float(o.qty or 0),
                "type": str(getattr(o.order_type, "value", o.order_type)),
                "limit_price": float(o.limit_price) if o.limit_price else None,
                "status": str(getattr(o.status, "value", o.status)),
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
            }
            for o in orders
        ]

    def place_bracket(self, symbol: str, qty: int, direction: str,
                      entry: float, target: float, stop: float) -> str:
        """Submit a limit bracket order and return the order id."""
        from alpaca.trading.client import TradingClient  # noqa: F401  (import guard above)
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            LimitOrderRequest, StopLossRequest, TakeProfitRequest,
        )

        order = self.client.submit_order(LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if direction == "long" else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            limit_price=round(entry, 2),
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2)),
        ))
        return str(order.id)

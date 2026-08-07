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

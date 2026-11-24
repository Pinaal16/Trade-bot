"""SIGNALS + PLAN stages — Claude Fable 5 analysis.

Two calls per symbol:
  1. scan_news()  — web-search-backed news/catalyst scan (optional).
  2. build_plan() — structured-output trade plan (entry/target/stop/
                    invalidation/risk level) from the market snapshot + news.

Fable 5 notes baked in here:
  - Thinking is always on; depth is controlled with output_config.effort.
  - Server-side refusal fallbacks are enabled so a safety-classifier decline
    is retried on the fallback model inside the same call.
  - stop_reason is checked before content is read.
"""

from __future__ import annotations

import json

import anthropic

from .config import ModelConfig
from .market_data import MarketSnapshot

SYSTEM_PROMPT = (
    "You are the analysis engine of a trading research and decision-support "
    "tool. You produce candidate trade plans for a human to review; nothing "
    "you output is executed automatically, and none of it is financial "
    "advice. Base every claim on the data provided or on sources you "
    "searched. If the data does not support an actionable setup, say so — "
    "a 'no setup' answer is a good answer."
)

FALLBACK_BETA = "server-side-fallback-2026-06-01"

# Structured-output schema for the trade plan. Numeric fields are nullable so
# the model can return has_setup=false without inventing price levels.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "has_setup": {"type": "boolean"},
        "setup_type": {
            "type": ["string", "null"],
            "description": "Short name of the setup, e.g. 'breakout above 52w high', 'pullback to SMA20 in uptrend'",
        },
        "direction": {"type": "string", "enum": ["long", "short", "none"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "entry": {"type": ["number", "null"], "description": "Suggested entry price"},
        "target": {"type": ["number", "null"], "description": "Profit target price"},
        "stop": {"type": ["number", "null"], "description": "Stop-loss price"},
        "invalidation": {
            "type": ["string", "null"],
            "description": "Condition that invalidates the thesis before the stop is hit",
        },
        "risk_level": {"type": "string", "enum": ["low", "medium", "high", "extreme"]},
        "rationale": {"type": "string", "description": "2-4 sentence explanation of the plan or of why there is no setup"},
    },
    "required": [
        "symbol", "has_setup", "setup_type", "direction", "confidence",
        "entry", "target", "stop", "invalidation", "risk_level", "rationale",
    ],
    "additionalProperties": False,
}


class RefusalError(RuntimeError):
    """Raised when the whole model chain (primary + fallback) declined."""


class Analyst:
    def __init__(self, model: ModelConfig, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()

    def _create(self, **kwargs) -> anthropic.types.Message:
        response = self.client.beta.messages.create(
            model=self.model.id,
            system=SYSTEM_PROMPT,
            betas=[FALLBACK_BETA],
            fallbacks=[{"model": self.model.fallback}],
            **kwargs,
        )
        if response.stop_reason == "refusal":
            detail = ""
            if response.stop_details:
                detail = f" (category: {response.stop_details.category})"
            raise RefusalError(f"model declined the request{detail}")
        return response

    def scan_news(self, symbol: str, max_searches: int = 3) -> str:
        """Search recent news for a symbol and return a compact summary."""
        messages = [{
            "role": "user",
            "content": (
                f"Search for the most recent news and catalysts for the stock {symbol} "
                "(earnings, guidance, analyst moves, product/regulatory events, "
                "sector-wide drivers). Summarize the 3-5 most market-relevant items "
                "in a short bulleted list with dates. If nothing notable is recent, "
                "say 'No significant recent news.'"
            ),
        }]
        while True:
            response = self._create(
                max_tokens=4000,
                output_config={"effort": self.model.effort_news},
                tools=[{
                    "type": "web_search_20260209",
                    "name": "web_search",
                    "max_uses": max_searches,
                }],
                messages=messages,
            )
            # Server-side tool loops can pause; re-send to let the server resume.
            if response.stop_reason == "pause_turn":
                messages = messages[:1] + [{"role": "assistant", "content": response.content}]
                continue
            return "\n".join(
                block.text for block in response.content if block.type == "text"
            ).strip()

    def build_plan(self, snapshot: MarketSnapshot, news_summary: str | None) -> dict:
        """Analyze a snapshot and return a trade-plan dict matching PLAN_SCHEMA."""
        news_section = news_summary or "News scan disabled for this run."
        prompt = (
            "Analyze the following market data and news for a potential swing-trade "
            "setup. Flag a setup only when price action, volume, trend, and the news "
            "backdrop genuinely line up; otherwise return has_setup=false.\n\n"
            f"MARKET DATA\n{snapshot.summary()}\n\n"
            f"RECENT NEWS\n{news_section}\n\n"
            "If there is a setup, provide a full plan: entry, target, stop, the "
            "invalidation condition, and an honest risk level. Entry/target/stop "
            "must be consistent with the current price and with the direction "
            "(for long: stop < entry < target; for short: target < entry < stop)."
        )
        response = self._create(
            max_tokens=8000,
            output_config={
                "effort": self.model.effort_signals,
                "format": {"type": "json_schema", "schema": PLAN_SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)

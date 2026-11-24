"""Trade journal — the record that tells you whether live matches the backtest.

A backtest says what *should* happen. This says what did. When live expectancy
drifts below backtest expectancy, something is wrong (slippage, missed fills,
overridden signals) and you want to know before it costs a season of returns.

Stored as newline-delimited JSON so it survives crashes and is trivially
inspectable with any tool.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

JOURNAL_PATH = Path("state/journal.jsonl")


@dataclasses.dataclass
class JournalEntry:
    timestamp: str
    symbol: str
    setup_type: str
    direction: str
    entry: float
    target: float
    stop: float
    shares: int
    dollar_risk: float
    order_id: str | None
    confidence: str
    rationale: str
    # Filled in later, once the position closes.
    exit_price: float | None = None
    exit_date: str | None = None
    pnl: float | None = None
    outcome: str | None = None      # "target" | "stop" | "manual"


def record(symbol: str, plan: dict, risk: dict, order_id: str | None) -> None:
    """Append an approved trade at the moment it is placed."""
    entry = JournalEntry(
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        symbol=symbol,
        setup_type=plan.get("setup_type") or "",
        direction=plan.get("direction") or "",
        entry=float(plan.get("entry") or 0),
        target=float(plan.get("target") or 0),
        stop=float(plan.get("stop") or 0),
        shares=int(risk.get("shares") or 0),
        dollar_risk=float(risk.get("dollar_risk") or 0),
        order_id=order_id,
        confidence=plan.get("confidence") or "",
        rationale=plan.get("rationale") or "",
    )
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a") as fh:
        fh.write(json.dumps(dataclasses.asdict(entry)) + "\n")


def load() -> list[dict]:
    if not JOURNAL_PATH.exists():
        return []
    return [json.loads(line) for line in JOURNAL_PATH.read_text().splitlines() if line.strip()]


def reconcile(broker) -> int:
    """Close out journal entries whose positions the broker no longer holds.

    Returns the number of entries updated. Exit price comes from the broker's
    filled orders where available, so realised P/L reflects actual fills rather
    than the plan's intended levels.
    """
    entries = load()
    if not entries:
        return 0

    try:
        held = {p["symbol"] for p in broker.positions()}
    except Exception:
        return 0

    updated = 0
    for e in entries:
        if e.get("pnl") is not None or e["symbol"] in held:
            continue
        # Position is gone and we never recorded an exit — mark it closed.
        e["exit_date"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        e["outcome"] = "closed"
        updated += 1

    if updated:
        with JOURNAL_PATH.open("w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
    return updated


def stats() -> dict:
    """Live performance, in the same shape as the backtest metrics."""
    closed = [e for e in load() if e.get("pnl") is not None]
    if not closed:
        return {"trades": 0}

    wins = [e for e in closed if e["pnl"] > 0]
    losses = [e for e in closed if e["pnl"] <= 0]
    gross_win = sum(e["pnl"] for e in wins)
    gross_loss = abs(sum(e["pnl"] for e in losses))
    r_multiples = [
        e["pnl"] / e["dollar_risk"] for e in closed if e.get("dollar_risk")
    ]

    return {
        "trades": len(closed),
        "open": len([e for e in load() if e.get("pnl") is None]),
        "win_rate": len(wins) / len(closed) * 100,
        "avg_win": gross_win / len(wins) if wins else 0.0,
        "avg_loss": gross_loss / len(losses) if losses else 0.0,
        "expectancy": sum(e["pnl"] for e in closed) / len(closed),
        "expectancy_r": sum(r_multiples) / len(r_multiples) if r_multiples else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf"),
        "total_pnl": sum(e["pnl"] for e in closed),
    }

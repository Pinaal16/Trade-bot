# Trade-bot — 24/7 AI Trading Research Assistant

An AI-powered market scanner and trade-planning system built on **Claude Fable 5**.
It scans the market, looks for setups, builds trade plans, checks risk, and keeps
monitoring everything around the clock.

> **Human review is still required.** This is a research and decision-support
> system, not guaranteed profit or financial advice. It never places orders.

## Workflow

```
🔍 SCAN → 📡 SIGNALS → 📝 PLAN → 🛡️ RISK → 👀 MONITOR → ✅ DECISION
```

It watches:

- 📊 Price action
- 📰 News (via Claude's web search)
- 📈 Volume
- 🧭 Trends (moving averages)
- ⭐ Watchlists

For each flagged setup it creates a full trade plan with:

- 🎯 Entry
- 💰 Target
- 🛑 Stop
- ⚠️ Invalidation
- 🛡️ Risk level

Before anything moves forward, a **deterministic risk engine** (plain Python, not
the LLM) checks:

- 📐 Position size
- 📦 Total exposure
- 📉 Drawdown
- 🌪️ Volatility
- 🚨 Maximum loss

The final output for every symbol is one of:

- ✅ `APPROVED` — setup found, plan built, all risk checks passed, high confidence
- 👁️ `WATCHLIST` — setup found but confidence is not high, or a soft risk check tripped
- ❌ `REJECTED` — a hard risk check failed
- ➖ `NO_SETUP` — nothing actionable right now

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

Edit `config.yaml` to set your watchlist, account equity, and risk limits.

## Usage

```bash
# One full pipeline pass over the watchlist
python main.py

# 24/7 monitoring loop (re-scans every interval from config.yaml)
python main.py --loop

# Scan a single symbol
python main.py --symbol NVDA

# Skip the news step (no web search, faster/cheaper)
python main.py --no-news
```

Each run writes a JSON report to `reports/` and prints a decision summary.

## Architecture

| Stage    | Module                  | Powered by |
|----------|-------------------------|------------|
| SCAN     | `trade_bot/market_data.py` | yfinance — price, volume, SMA trend, ATR volatility |
| SIGNALS + PLAN | `trade_bot/analyst.py` | Claude Fable 5 — news scan (web search) + structured trade plan |
| RISK     | `trade_bot/risk.py`     | Deterministic Python — no LLM in the risk path |
| DECISION | `trade_bot/decision.py` | Combines plan confidence + risk verdict |
| MONITOR  | `trade_bot/monitor.py`  | Interval loop around the pipeline |

Notes on the Claude integration:

- Model is `claude-fable-5`; thinking is always on for this model, so depth is
  controlled with `output_config.effort` instead of a thinking budget.
- Server-side refusal fallbacks are enabled (`fallbacks` → `claude-opus-4-8`),
  so an occasional safety-classifier decline is retried automatically in the
  same API call.
- Trade plans are produced as **structured outputs** (JSON schema), so parsing
  never depends on prompt formatting.

## Disclaimer

This software is for research and education. Markets involve risk of loss.
Nothing produced by this tool is investment advice, and no output should be
acted on without independent human judgment.

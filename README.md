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

## Usage — web dashboard (easiest)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export ALPACA_API_KEY=...  ALPACA_SECRET_KEY=...   # paper keys to start
python webapp.py
```

Your browser opens on **http://localhost:5000** with:

- your account equity, today's P/L, cash and buying power
- a **Run scan** button (edit the symbol list right in the page)
- a live progress log while the scan runs
- one colour-coded card per symbol — ✅ approved, 👁️ watchlist, ❌ rejected,
  ➖ no setup — each showing entry / target / stop / share count / max loss
- an **Approve & place order** button on approved setups only; nothing is
  ordered until you click it
- your open positions and open orders, refreshed automatically

## Usage — command line

```bash
# One full pipeline pass over the watchlist
python main.py

# 24/7 monitoring loop (re-scans every interval from config.yaml)
python main.py --loop

# Scan a single symbol
python main.py --symbol NVDA

# Skip the news step (no web search, faster/cheaper)
python main.py --no-news

# Trading mode: you approve each trade, the bot places the order (paper by default)
python main.py --trade
```

Each run writes a JSON report to `reports/` and prints a decision summary.

## Trading mode (approve-to-execute)

The web dashboard always runs in this mode. On the command line, use `--trade`
(or `broker.enabled: true` in config): every ✅ APPROVED setup is
shown to you in full — entry, target, stop, share count, max dollar loss, and
the rationale — and you answer **y/N**. Only on "y" does the bot submit the
order to [Alpaca](https://alpaca.markets) as a **bracket order**: the entry, the
take-profit at the target, and the stop-loss are all attached at submission, so
your maximum loss is fixed before the trade is live.

Setup:

1. Create a free Alpaca account and generate **paper-trading** API keys.
2. `export ALPACA_API_KEY=... ALPACA_SECRET_KEY=...`
3. `python main.py --trade`

In trading mode, position sizing uses your **real account equity and open
exposure** from Alpaca instead of the numbers in `config.yaml` — so as you
deposit more (e.g. adding to the account daily), sizes scale automatically.

Paper trading is the default and the config warns against switching it off.
Going live requires setting `broker.paper: false` **and** typing `LIVE` at
startup. Trade paper for several weeks first and review the reports before
risking real money — nothing here guarantees profit; the risk engine's job is
to keep the losing trades small, not to prevent them.

## Architecture

| Stage    | Module                  | Powered by |
|----------|-------------------------|------------|
| SCAN     | `trade_bot/market_data.py` | yfinance — price, volume, SMA trend, ATR volatility |
| SIGNALS + PLAN | `trade_bot/analyst.py` | Claude Fable 5 — news scan (web search) + structured trade plan |
| RISK     | `trade_bot/risk.py`     | Deterministic Python — no LLM in the risk path |
| DECISION | `trade_bot/decision.py` | Combines plan confidence + risk verdict |
| MONITOR  | `trade_bot/monitor.py`  | Interval loop around the pipeline |
| UI       | `webapp.py` + `templates/` | Flask dashboard — scan, review, approve |
| BROKER   | `trade_bot/broker.py`   | Alpaca bracket orders (paper by default) |

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

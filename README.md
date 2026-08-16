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

## Start here: does this actually work?

Before risking money, measure whether the strategy has an edge:

```bash
python backtest.py --universe sp100 --years 5 --equity 1500
```

This runs the strategy over 5 years and 40 symbols in a few minutes, for free
(no API calls), and prints a verdict:

| Verdict | What to do |
|---|---|
| `NO EDGE` | **Don't trade it.** You lose money per trade on average. |
| `INSUFFICIENT DATA` | Widen `--universe` / `--years` until you have 30+ trades. |
| `MARGINAL` | Profit factor too thin to survive real-world costs. |
| `UNDERPERFORMS BUY & HOLD` | Holding the same symbols beat the work. Not a business. |
| `PROMISING` | Permission to **paper trade** — not permission to go all in. |

The backtest is deliberately pessimistic: signals fill at the *next* bar's open
(never the close you just saw), a bar that spans both stop and target counts as
a **stop**, gaps through your stop fill at the open, and slippage is charged on
both sides. Position sizing calls the same `size_position()` the live bot uses,
so what you test is what you trade.

Backtests still flatter you — no emotions, perfect discipline, and whatever
survivorship bias is in your symbol list. Treat a good number as a hypothesis.

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
| VALIDATE | `trade_bot/backtest.py` + `strategy.py` | Edge measurement over years of history, free |
| TRACK    | `trade_bot/journal.py`  | Live trade log + expectancy vs the backtest |

Notes on the Claude integration:

- Model is `claude-fable-5`; thinking is always on for this model, so depth is
  controlled with `output_config.effort` instead of a thinking budget.
- Server-side refusal fallbacks are enabled (`fallbacks` → `claude-opus-4-8`),
  so an occasional safety-classifier decline is retried automatically in the
  same API call.
- Trade plans are produced as **structured outputs** (JSON schema), so parsing
  never depends on prompt formatting.

## Track record

Every order placed — from the dashboard or the CLI — is written to
`state/journal.jsonl` automatically, and the dashboard shows your live win
rate, expectancy per trade and total P/L.

**Compare live expectancy against your backtest expectancy.** That single
comparison is the health check for the whole system:

- Live ≈ backtest → the system is behaving as modelled.
- Live materially worse → slippage, missed fills, or you're overriding signals.
- Live negative over 30+ trades → stop. Don't add money to prove it right.

## A realistic operating plan

| Phase | Days | What you do |
|---|---|---|
| **1. Measure** | 1–7 | Run the backtest. If the verdict isn't `PROMISING`, fix the strategy or stop — this costs $0 and saves the tuition. |
| **2. Debug** | 8–14 | Paper trade to catch execution problems (rejected orders, bad fills, wrong sizes). This validates plumbing, not strategy — the backtest did that. |
| **3. Go live small** | 15–30 | Real money, `max_risk_per_trade_pct: 0.5` for the first month. Small enough that a losing streak is affordable, real enough that the psychology is real. |
| **4. Review** | 30+ | Compare journal expectancy to backtest. Only raise risk after 30+ live trades confirm the edge. |

Two rules worth more than any code here:

1. **Deposit on a schedule, trade on signals.** Never take a trade because you
   added money that day. Some days there is nothing worth doing.
2. **Costs are fixed, your account is not.** Run the cheapest model that works
   (`claude-haiku-4-5`) until the account is large enough that a better model's
   monthly bill is under ~1% of equity.

## Disclaimer

This software is for research and education. Markets involve risk of loss.
Nothing produced by this tool is investment advice, and no output should be
acted on without independent human judgment.

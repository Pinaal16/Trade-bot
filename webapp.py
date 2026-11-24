"""Trade-bot web dashboard.

A small local web UI: see your account, run a scan with one click, and approve
proposed trades with a button. Nothing is ever ordered without you clicking
Approve.

Run:  python webapp.py       then open http://localhost:5000
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from trade_bot import journal
from trade_bot.broker import AlpacaBroker, BrokerError
from trade_bot.config import load_config
from trade_bot.pipeline import place_order, run_pipeline

app = Flask(__name__)


def _config_path() -> Path:
    """Find config.yaml whether the app is launched from the project directory
    or from anywhere else."""
    explicit = os.environ.get("TRADEBOT_CONFIG")
    if explicit:
        return Path(explicit)
    local = Path.cwd() / "config.yaml"
    return local if local.exists() else Path(__file__).resolve().parent / "config.yaml"


CONFIG_PATH = _config_path()

# In-memory state for the current scan. Single-user local app, so a lock
# around a dict is enough.
_lock = threading.Lock()
_state: dict = {
    "running": False,
    "log": [],
    "results": [],
    "started_at": None,
    "error": None,
}

_broker: AlpacaBroker | None = None
_broker_error: str | None = None


def get_broker() -> AlpacaBroker | None:
    return _broker


@app.route("/")
def index():
    config = load_config(CONFIG_PATH)
    return render_template(
        "index.html",
        watchlist=config.watchlist,
        paper=config.broker.paper,
        broker_ready=_broker is not None,
        broker_error=_broker_error,
    )


@app.route("/api/account")
def api_account():
    broker = get_broker()
    if not broker:
        return jsonify({"connected": False, "error": _broker_error})
    try:
        journal.reconcile(broker)
        return jsonify({
            "connected": True,
            "account": broker.account_summary(),
            "positions": broker.positions(),
            "orders": broker.open_orders(),
            "journal": journal.stats(),
        })
    except Exception as exc:
        return jsonify({"connected": False, "error": str(exc)})


@app.route("/api/scan", methods=["POST"])
def api_scan():
    payload = request.get_json(silent=True) or {}
    symbols = [s.strip().upper() for s in payload.get("symbols", []) if s.strip()]
    use_news = payload.get("news", True)

    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "error": "a scan is already running"}), 409
        _state.update(running=True, log=[], results=[], error=None)

    threading.Thread(
        target=_run_scan, args=(symbols or None, use_news), daemon=True
    ).start()
    return jsonify({"ok": True})


def _run_scan(symbols: list[str] | None, use_news: bool) -> None:
    def progress(message: str) -> None:
        with _lock:
            _state["log"].append(message)

    try:
        config = load_config(CONFIG_PATH)
        results = run_pipeline(
            config,
            symbols=symbols,
            news_enabled=use_news,
            broker=get_broker(),
            approver=None,          # web UI approves via button, not stdin
            progress=progress,
        )
        with _lock:
            _state["results"] = results
    except Exception as exc:
        with _lock:
            _state["error"] = str(exc)
            _state["log"].append(f"⚠️ Scan failed: {exc}")
    finally:
        with _lock:
            _state["running"] = False


@app.route("/api/scan/status")
def api_scan_status():
    with _lock:
        return jsonify({
            "running": _state["running"],
            "log": _state["log"][-40:],
            "results": _state["results"],
            "error": _state["error"],
        })


@app.route("/api/approve", methods=["POST"])
def api_approve():
    """Place the bracket order for one proposed trade."""
    broker = get_broker()
    if not broker:
        return jsonify({"ok": False, "error": "broker not connected"}), 400

    symbol = (request.get_json(silent=True) or {}).get("symbol", "").upper()
    with _lock:
        entry = next(
            (r for r in _state["results"] if r.get("symbol") == symbol), None
        )
    if not entry or not entry.get("pending_approval"):
        return jsonify({"ok": False, "error": f"no pending trade for {symbol}"}), 404

    try:
        order_id = place_order(broker, symbol, entry["plan"], entry["risk"])
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    with _lock:
        entry["pending_approval"] = False
        entry["order_id"] = order_id
    return jsonify({"ok": True, "order_id": order_id})


@app.route("/api/skip", methods=["POST"])
def api_skip():
    symbol = (request.get_json(silent=True) or {}).get("symbol", "").upper()
    with _lock:
        for entry in _state["results"]:
            if entry.get("symbol") == symbol:
                entry["pending_approval"] = False
                entry["skipped"] = True
    return jsonify({"ok": True})


DEFAULT_PORT = 8099   # deliberately off the beaten path (3000/5000/8000/8080)


def _pick_port(host: str, preferred: int) -> int:
    """Return `preferred` if it's free, otherwise the next free port after it."""
    for port in range(preferred, preferred + 25):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
        if port != preferred:
            print(f"⚠️  Port {preferred} is in use — using {port} instead.")
        return port
    raise SystemExit(f"No free port between {preferred} and {preferred + 24}.")


def main() -> int:
    global _broker, _broker_error

    parser = argparse.ArgumentParser(description="Trade-bot dashboard")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"port to serve on (default {DEFAULT_PORT}); "
                             "if busy, the next free port is used")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default 127.0.0.1, local only)")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't open a browser window automatically")
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)
    if not config.broker.paper:
        print("⚠️  LIVE trading is configured (broker.paper: false). Real money is at risk.")
        if input("Type LIVE to confirm, anything else to abort: ").strip() != "LIVE":
            print("Aborted.")
            return 1

    try:
        _broker = AlpacaBroker(paper=config.broker.paper)
        mode = "paper" if config.broker.paper else "LIVE"
        print(f"✅ Connected to Alpaca ({mode} trading).")
    except BrokerError as exc:
        _broker_error = str(exc)
        print(f"⚠️  Broker not connected: {exc}")
        print("   The dashboard still runs — you'll get analysis, but no order buttons.")

    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print("⚠️  ANTHROPIC_API_KEY is not set — scans will fail until you set it.",
              file=sys.stderr)

    port = _pick_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    print(f"\n🌐 Dashboard: {url}")
    print("   (Ctrl-C to stop)\n")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

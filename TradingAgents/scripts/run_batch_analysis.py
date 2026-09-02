"""Run TradingAgentsGraph over a list of tickers and save each report to disk.

Reads the CSV produced by ``select_top_performers.py`` (Sector, Ticker, ...)
and, for every ticker, runs the full analyst -> research -> trader -> risk ->
portfolio pipeline via the programmatic API (same path as ``main.py``), then
writes the report tree under ``<output_dir>/<Sector>/<Ticker>/`` using the
same writer the CLI uses (``tradingagents.reporting.write_report_tree``).

Resumable: a ticker whose ``complete_report.md`` already exists is skipped,
so a killed/interrupted run can simply be restarted. Per-ticker failures are
caught, logged to ``<output_dir>/errors.log``, and do not abort the batch. A
running ``summary.csv`` (ticker, sector, index score, signal, elapsed) is
updated as each ticker finishes so partial progress is never lost.

Tickers can run concurrently via ``--workers N`` (default 1 = sequential,
same behavior as before). Each worker thread builds and reuses its own
TradingAgentsGraph instance (graphs are not shared across threads), so
concurrency only affects wall-clock time, not correctness. Every ticker's
config is identical, so the graph's shared global dataflow-config is
race-safe here even though it's process-wide.

Usage:
    python scripts/run_batch_analysis.py \\
        --tickers output/top_performers.csv \\
        --output-dir output/analysis \\
        --date 2026-09-01 \\
        [--limit 5] [--delay 3] [--workers 4]
"""

import argparse
import csv
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree

SUMMARY_FIELDS = ["Sector", "Ticker", "Index", "Signal", "ElapsedSeconds", "Status"]

_thread_local = threading.local()
_file_lock = threading.Lock()  # guards summary.csv / errors.log across worker threads


def load_tickers(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_summary_row(summary_path: Path, row: dict):
    with _file_lock:
        is_new = not summary_path.exists()
        with summary_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)


def append_error(errors_path: Path, ticker: str, sector: str, tb: str):
    with _file_lock:
        with errors_path.open("a", encoding="utf-8") as f:
            f.write(f"=== {ticker} ({sector}) ===\n{tb}\n\n")


def get_thread_graph(config: dict) -> TradingAgentsGraph:
    """One TradingAgentsGraph per worker thread, built lazily and reused for
    every ticker that thread processes (avoids rebuilding LLM clients / the
    compiled LangGraph workflow per ticker, while staying free of the
    cross-thread mutable-state issues a single shared instance would have)."""
    graph = getattr(_thread_local, "graph", None)
    if graph is None:
        graph = TradingAgentsGraph(debug=False, config=config)
        _thread_local.graph = graph
    return graph


def process_ticker(row: dict, config: dict, output_dir: Path, date: str, delay: float) -> dict:
    sector, ticker, index_score = row["Sector"], row["Ticker"], row["Index"]
    ticker_dir = output_dir / sector.replace("/", "-") / ticker
    report_path = ticker_dir / "complete_report.md"

    if report_path.exists():
        return {"ticker": ticker, "sector": sector, "index": index_score, "status": "skipped"}

    ta = get_thread_graph(config)
    t0 = time.time()
    try:
        final_state, signal = ta.propagate(ticker, date)
        write_report_tree(final_state, ticker, ticker_dir)
        elapsed = time.time() - t0
        if delay:
            time.sleep(delay)
        return {
            "ticker": ticker, "sector": sector, "index": index_score,
            "signal": signal, "elapsed": elapsed, "status": "ok",
        }
    except Exception as exc:
        elapsed = time.time() - t0
        return {
            "ticker": ticker, "sector": sector, "index": index_score,
            "status": "error", "error": str(exc), "elapsed": elapsed,
            "traceback": traceback.format_exc(),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="output/top_performers.csv")
    parser.add_argument("--output-dir", default="output/analysis")
    parser.add_argument("--date", required=True, help="Analysis date, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tickers (testing)")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds to sleep after each ticker completes")
    parser.add_argument("--workers", type=int, default=1, help="Number of tickers to run concurrently (default 1 = sequential)")
    args = parser.parse_args()

    rows = load_tickers(Path(args.tickers))
    if args.limit:
        rows = rows[: args.limit]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.csv"
    errors_path = output_dir / "errors.log"

    config = DEFAULT_CONFIG.copy()
    print(
        f"Provider={config['llm_provider']} deep={config['deep_think_llm']} "
        f"quick={config['quick_think_llm']} debate_rounds={config['max_debate_rounds']} "
        f"risk_rounds={config['max_risk_discuss_rounds']} workers={args.workers}",
        flush=True,
    )

    total = len(rows)
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_ticker, row, config, output_dir, args.date, args.delay): row
            for row in rows
        }
        for future in as_completed(futures):
            done += 1
            result = future.result()
            ticker, sector = result["ticker"], result["sector"]

            if result["status"] == "skipped":
                print(f"[{done}/{total}] {ticker} ({sector}) - already done, skipping", flush=True)
                continue

            if result["status"] == "ok":
                print(
                    f"[{done}/{total}] {ticker} ({sector}) - DONE in {result['elapsed']:.0f}s "
                    f"- signal={result['signal']}",
                    flush=True,
                )
                append_summary_row(summary_path, {
                    "Sector": sector, "Ticker": ticker, "Index": result["index"],
                    "Signal": result["signal"], "ElapsedSeconds": f"{result['elapsed']:.0f}",
                    "Status": "ok",
                })
            else:
                print(
                    f"[{done}/{total}] {ticker} ({sector}) - ERROR after {result['elapsed']:.0f}s: "
                    f"{result['error']}",
                    flush=True,
                )
                append_error(errors_path, ticker, sector, result["traceback"])
                append_summary_row(summary_path, {
                    "Sector": sector, "Ticker": ticker, "Index": result["index"],
                    "Signal": "ERROR", "ElapsedSeconds": f"{result['elapsed']:.0f}",
                    "Status": str(result["error"])[:200],
                })

    print(f"Batch complete. Summary -> {summary_path}", flush=True)


if __name__ == "__main__":
    main()

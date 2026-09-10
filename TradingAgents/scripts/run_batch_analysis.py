"""Run TradingAgentsGraph over a list of tickers and save each report to disk.

Reads the CSV produced by ``select_top_performers.py`` (Sector, Ticker, ...)
and, for every ticker, runs the full analyst -> research -> trader -> risk ->
portfolio pipeline via the programmatic API (same path as ``main.py``), then
writes the report tree under ``<output_dir>/<Sector>/<Ticker>/`` using the
same writer the CLI uses (``tradingagents.reporting.write_report_tree``).

Cached: each ticker's report folder also gets a ``.cache_meta.json`` recording
when it was generated. Before running a ticker, its cache is checked first --
if a report already exists and its cache metadata is younger than
``CACHE_DAYS`` (see the constant below, or ``--cache-days``), the saved
report is reused and TradingAgents is *not* re-run for that ticker. Once the
cache expires (or doesn't exist yet), the ticker is analyzed fresh and the
cache is refreshed. This is what makes re-running a 500-ticker batch cheap:
only tickers whose cache has actually expired do real work.

Per-ticker failures are caught, logged to ``<output_dir>/errors.log``, and do
not abort the batch. A running ``summary.csv`` (ticker, sector, index score,
signal, elapsed) is updated as each ticker finishes so partial progress is
never lost; a ticker already present in ``summary.csv`` from a prior run of
this same ``--output-dir`` is not re-added, whether it was served from cache
or freshly analyzed.

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
        [--limit 5] [--delay 3] [--workers 4] [--cache-days 1]
"""

import argparse
import csv
import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree

# How long a saved per-ticker report stays valid before TradingAgents is
# re-run for that ticker. Change this single number (or pass --cache-days)
# to make the cache last longer, e.g. CACHE_DAYS = 2.
CACHE_DAYS = 1

CACHE_META_FILENAME = ".cache_meta.json"

SUMMARY_FIELDS = ["Sector", "Ticker", "Index", "Signal", "ElapsedSeconds", "Status"]

_thread_local = threading.local()
_file_lock = threading.Lock()  # guards summary.csv / errors.log across worker threads


def load_cache_meta(ticker_dir: Path) -> dict | None:
    """Read a ticker's cache metadata, or None if it has never been cached."""
    meta_path = ticker_dir / CACHE_META_FILENAME
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # corrupt/unreadable cache file -> treat as no cache


def save_cache_meta(ticker_dir: Path, meta: dict):
    meta_path = ticker_dir / CACHE_META_FILENAME
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def cache_age_days(meta: dict) -> float:
    generated_at = datetime.fromisoformat(meta["generated_at"])
    return (datetime.now(timezone.utc) - generated_at).total_seconds() / 86400


def is_cache_fresh(meta: dict | None, cache_days: float) -> bool:
    if not meta:
        return False
    try:
        return cache_age_days(meta) < cache_days
    except (KeyError, ValueError):
        return False  # malformed metadata -> treat as expired


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


def replace_summary_row(summary_path: Path, ticker: str, row: dict):
    """Drop any existing row(s) for ``ticker`` and append ``row`` in their
    place (rewrites the whole file under the same lock ``append_summary_row``
    uses). Needed for a ticker whose prior run errored: it never got a cache
    entry, so a resume genuinely re-runs it -- and the fresh result must
    replace the stale ERROR row rather than being silently dropped (the old
    "already in existing_tickers, skip" guard did exactly that) or duplicated
    alongside it."""
    with _file_lock:
        rows = []
        if summary_path.exists():
            with summary_path.open(encoding="utf-8") as f:
                rows = [r for r in csv.DictReader(f) if r["Ticker"] != ticker]
        rows.append(row)
        with summary_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
            writer.writeheader()
            writer.writerows(rows)


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


def process_ticker(
    row: dict, config: dict, output_dir: Path, date: str, delay: float,
    cache_days: float, existing_summary: dict,
) -> dict:
    sector, ticker, index_score = row["Sector"], row["Ticker"], row["Index"]
    ticker_dir = output_dir / sector.replace("/", "-") / ticker
    report_path = ticker_dir / "complete_report.md"

    cache_meta = load_cache_meta(ticker_dir)
    if cache_meta is None and report_path.exists():
        # A report from before this caching feature existed: back-fill its
        # cache metadata from the file's own timestamp (when it was actually
        # written) plus summary.csv if we have a row for it, so it's treated
        # as cached rather than redone from scratch.
        prior = existing_summary.get(ticker, {})
        cache_meta = {
            "ticker": ticker, "sector": sector, "index": index_score,
            "signal": prior.get("Signal", "UNKNOWN"),
            "elapsed": float(prior.get("ElapsedSeconds") or 0),
            "generated_at": datetime.fromtimestamp(
                report_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        }
        save_cache_meta(ticker_dir, cache_meta)

    if report_path.exists() and is_cache_fresh(cache_meta, cache_days):
        return {
            "ticker": ticker, "sector": sector, "index": index_score,
            "signal": cache_meta.get("signal", "UNKNOWN"), "elapsed": 0.0,
            "status": "cached", "cache_age_days": cache_age_days(cache_meta),
        }

    ta = get_thread_graph(config)
    t0 = time.time()
    try:
        final_state, signal = ta.propagate(ticker, date)
        write_report_tree(final_state, ticker, ticker_dir)
        elapsed = time.time() - t0
        save_cache_meta(ticker_dir, {
            "ticker": ticker, "sector": sector, "index": index_score,
            "signal": signal, "elapsed": elapsed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
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
    parser.add_argument(
        "--cache-days", type=float, default=CACHE_DAYS,
        help=f"Reuse a ticker's saved report if it's younger than this many days (default {CACHE_DAYS})",
    )
    args = parser.parse_args()

    rows = load_tickers(Path(args.tickers))
    if args.limit:
        rows = rows[: args.limit]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.csv"
    errors_path = output_dir / "errors.log"

    # Rows already recorded in summary.csv from a prior run of this same
    # --output-dir: used both to avoid re-adding a ticker (keeps reruns
    # idempotent) and to back-fill cache metadata for reports generated
    # before this caching feature existed.
    existing_summary = {}
    if summary_path.exists():
        with summary_path.open(encoding="utf-8") as f:
            existing_summary = {r["Ticker"]: r for r in csv.DictReader(f)}
    existing_tickers = set(existing_summary)

    config = DEFAULT_CONFIG.copy()
    print(
        f"Provider={config['llm_provider']} deep={config['deep_think_llm']} "
        f"quick={config['quick_think_llm']} debate_rounds={config['max_debate_rounds']} "
        f"risk_rounds={config['max_risk_discuss_rounds']} workers={args.workers} "
        f"cache_days={args.cache_days}",
        flush=True,
    )

    total = len(rows)
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_ticker, row, config, output_dir, args.date,
                args.delay, args.cache_days, existing_summary,
            ): row
            for row in rows
        }
        for future in as_completed(futures):
            done += 1
            result = future.result()
            ticker, sector = result["ticker"], result["sector"]

            if result["status"] == "cached":
                print(
                    f"[{done}/{total}] {ticker} ({sector}) - cached "
                    f"({result['cache_age_days']:.1f}d old), skipping re-run "
                    f"- signal={result['signal']}",
                    flush=True,
                )
                if ticker not in existing_tickers:
                    append_summary_row(summary_path, {
                        "Sector": sector, "Ticker": ticker, "Index": result["index"],
                        "Signal": result["signal"], "ElapsedSeconds": "0",
                        "Status": "cached",
                    })
                continue

            # A ticker with a prior "ok"/"cached" row here would already have
            # been caught by the cache-freshness check inside process_ticker
            # (report_path.exists() and fresh -> "cached" status above), so
            # reaching this point with such a row would mean the CSV is stale
            # relative to the actual report on disk -- skip re-adding it.
            # But a prior *error* row leaves no cached report to catch, so
            # process_ticker genuinely re-ran it; that fresh result must
            # replace the stale error row, not be silently dropped.
            prior_status = existing_summary.get(ticker, {}).get("Status")
            had_stale_error_row = ticker in existing_tickers and prior_status not in ("ok", "cached")
            if ticker in existing_tickers and not had_stale_error_row:
                continue
            save_row = replace_summary_row if had_stale_error_row else append_summary_row
            save_row_args = (summary_path, ticker) if had_stale_error_row else (summary_path,)

            if result["status"] == "ok":
                print(
                    f"[{done}/{total}] {ticker} ({sector}) - DONE in {result['elapsed']:.0f}s "
                    f"- signal={result['signal']}",
                    flush=True,
                )
                save_row(*save_row_args, {
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
                save_row(*save_row_args, {
                    "Sector": sector, "Ticker": ticker, "Index": result["index"],
                    "Signal": "ERROR", "ElapsedSeconds": f"{result['elapsed']:.0f}",
                    "Status": str(result["error"])[:200],
                })

    print(f"Batch complete. Summary -> {summary_path}", flush=True)


if __name__ == "__main__":
    main()

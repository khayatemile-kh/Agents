# TradingAgents Practice Comparison — AAPL vs MSFT vs GOOGL vs NVDA (+ GOOGL model retry)

All runs: analysis date **2026-08-28**, analysts=`market, news`, `max_debate_rounds=1`, `max_risk_discuss_rounds=1`, `llm_provider=ollama`. Simulated research only — no real trades, no brokerage connection, no API keys configured. Five runs total: three on `llama3.1:8b` (AAPL, MSFT, GOOGL), plus two on `qwen2.5:7b-instruct` (a GOOGL retry, and NVDA — with a `max_tokens=2048` safeguard added after the GOOGL retry's killed hung attempt).

## ⚠️ GOOGL (llama3.1:8b) data caveat
The original GOOGL run hit a genuine upstream data gap (blank OHLC for the final day from the `yfinance` vendor) and the model **fabricated a price of $1500.45** instead of falling back to the real last close ($340.65 on 2026-08-27) or flagging the gap. That run's price/target figures are **void** — see `GOOGL_2026-08-28.md`.

## ⚠️ GOOGL (qwen2.5:7b-instruct retry) caveat — different failure mode
The retry avoided price fabrication entirely (real $340.65 close used throughout, correctly grounded via a `get_verified_market_snapshot` tool that excludes rows past the requested date). But it introduced a new issue: the Risk team's Neutral Analyst claimed *"RSI at 44.24 is closer to overbought"* — factually backwards (44.24 is near-neutral, if anything closer to oversold than overbought) — and that fabricated claim is what flipped the Trader's own "Hold" call into a final "Buy." See `GOOGL_2026-08-28_qwen2.5-7b.md` for full detail, including a killed first attempt that hung 45+ minutes with no `max_tokens` cap.

## ⚠️ NVDA (qwen2.5:7b-instruct) caveats — two new issues, no fabrication
No data gap this time (NVDA's 2026-08-28 row was complete), and no fabricated numbers were found. But two other reliability problems showed up:
1. **Research Manager vs. Trader disagreement, left unreconciled.** The Research Manager's independent bull/bear debate synthesis came out **Overweight** (bullish on AI/data-center/gaming exposure). The Trader then called **Sell** on technical grounds (MACD bearish divergence), and the Portfolio Manager sided with the Trader for the final **Sell** — overriding the Research Manager's bullish read entirely, with no visible reconciliation between the two conflicting views. This is the same "final stage overrides an earlier stage on a technical read" pattern seen on the GOOGL retry, just with a real disagreement (not a fabricated claim) driving it this time.
2. **Mid-response language switch.** The `final_trade_decision` text unexpectedly switched to **Chinese** partway through (the risk-analysts' viewpoints section) despite `output_language=English` being configured — a known Qwen code-switching behavior. The conclusion stayed consistent once it returned to English, so the substance wasn't corrupted, just the language.

See `NVDA_2026-08-28.md` for full detail, including the process notes on a log-ordering artifact that was investigated and ruled benign (not a real loop) before the run was allowed to continue.

| | AAPL (llama3.1:8b) | MSFT (llama3.1:8b) | GOOGL (llama3.1:8b) | GOOGL retry (qwen2.5:7b-instruct) | NVDA (qwen2.5:7b-instruct) |
|---|---|---|---|---|---|
| **Final rating** | Overweight | Overweight | Buy *(void — see caveat)* | Buy *(see caveat)* | Sell *(see caveat)* |
| **Entry/price basis** | ~$319.70 | $507.53 | ~~$1500.45~~ fabricated | $340.65 (real, correctly grounded) | $217.55 (real) |
| **Stop-loss** | ~$284.86 (est.) | $493.59 (VWMA) | ~~$1350.00~~ fabricated | Not explicitly stated | $195.67 (200 SMA) |
| **Position size** | 2–5% | 5–10% | 20% | "moderate" (unquantified) | 1–2x ATR |
| **Time horizon** | Not specified | 3–6 months | 3–6 months | 6–12 months | Not specified |
| **Price history pulled** | ~8 months, complete | 20 days, complete | ~8 months, final row blank | Correctly excluded blank final row | Complete, no gap |
| **News/macro** | None found / no FRED key | None found / no FRED key | None found / no FRED key | None found / no FRED key | None found; macro (Core PCE, Polymarket) available |
| **Technical basis** | Ad-hoc range heuristic | MACD/RSI/Bollinger/ATR/VWMA | Couldn't parse data, invented numbers | MACD/RSI/Bollinger/ATR, real values throughout | MACD/RSI/Bollinger/ATR, real values, correctly read RSI this time |
| **Structured-output retry** | Yes, once | Yes, once | No (hallucinated free text instead) | Not observed | Yes, once (Portfolio Manager) |
| **Internal pipeline consistency** | Consistent through all stages | Consistent through all stages | Consistent (uniformly fabricated) | **Inconsistent**: Market Analyst → Hold, Research Mgr → Buy, Trader → Hold, Portfolio Mgr → Buy (final) | **Inconsistent**: Research Mgr → Overweight, Trader → Sell, Portfolio Mgr → Sell (final) |
| **Notable reliability issue** | Crude support/resistance math | Fake tool-call narrated as text | **Fabricated a ~4.4x-inflated price** | **Fabricated an RSI interpretation** that reversed the Trader's call; Risky/Safe risk-analysts produced no output at all | **Research Mgr/Trader disagreement overridden silently**; mid-response **language switch to Chinese** |
| **Run stability** | Completed normally (~9 min) | Completed normally (~10 min) | Completed normally (~10 min) | First attempt hung 45+ min (killed); retry with `max_tokens=2048` completed normally | Completed normally with `max_tokens=2048` already in place; one log-ordering artifact investigated and ruled benign |

## Takeaways
- **Model swap fixed the specific failure it targeted, not fabrication in general.** The whole reason we tried qwen2.5:7b-instruct was llama3.1:8b's price hallucination on bad data — and on that narrow point, it worked across both qwen runs: neither GOOGL nor NVDA fabricated a raw number. But each qwen run found a *different* way to be unreliable (a wrong RSI interpretation on GOOGL, a silently-overridden internal disagreement plus a language switch on NVDA). **Swapping models moved the failure mode around; it didn't eliminate unreliability as a category.**
- **The framework's own grounding tool (`get_verified_market_snapshot`) is doing real work** — it's the reason neither qwen run repeated the raw price fabrication. That's a framework-level safeguard, not a model-level one, and it's worth relying on more than model choice alone for data-fidelity issues.
- **`max_tokens=2048` solved the hang and stayed clean.** The GOOGL retry's killed attempt burned 45+ minutes with no forward progress; both the GOOGL retry and NVDA completed normally with the cap in place. Worth keeping this setting for any future local-model run on this Mac.
- **Don't trust "final" pipeline output as consensus — confirmed on a second run.** Both qwen runs show the same pattern: an earlier stage (Trader on GOOGL, Research Manager on NVDA) took one view, and a later stage overrode it without visibly reconciling the disagreement, yet `propagate()` only returns the final stage's answer. On NVDA specifically, the Research Manager was independently bullish and the printed "Sell" gives no hint of that. Worth checking the full state log (or the debate history), not just the headline decision, on any run you plan to weigh seriously.
- **New on NVDA: language consistency isn't guaranteed.** Even with `output_language=English` configured, qwen2.5:7b-instruct code-switched into Chinese mid-response. Worth a spot-check on any run's raw text before treating it as clean, presentable output.
- **All five runs hit the same infrastructure gaps** (no news vendor coverage that week, no FRED key) — though NVDA's News Analyst did surface real Core PCE and Polymarket data despite the FRED gap, showing the macro fallback path can still produce something useful. Adding `FRED_API_KEY` and/or `ALPHA_VANTAGE_API_KEY` remains the biggest lever for improving *input* quality, independent of model choice.
- **None of this should be read as investment advice** — every run here is labeled "simulated," and every single run (five for five) surfaced at least one real reliability issue, just never the same one twice.

## Files
- Full AAPL detail: `AAPL_2026-08-28.md`
- Full MSFT detail: `MSFT_2026-08-28.md`
- Full GOOGL detail (llama3.1:8b, price fabrication): `GOOGL_2026-08-28.md`
- Full GOOGL retry detail (qwen2.5:7b-instruct, RSI-interpretation fabrication): `GOOGL_2026-08-28_qwen2.5-7b.md`
- Full NVDA detail (qwen2.5:7b-instruct, disagreement + language switch): `NVDA_2026-08-28.md`
- Raw state logs: `~/.tradingagents/logs/<TICKER>/TradingAgentsStrategy_logs/full_states_log_2026-08-28*.json` (llama3.1:8b runs use the bare filename; the GOOGL llama3.1:8b run is backed up as `..._llama3.1-8b.json`, the GOOGL qwen retry as `..._qwen2.5-7b.json`, NVDA uses the bare filename)

## Also produced this session (not part of the table above — different method)
Two additional analyses were run via Claude Code directly (no Ollama, no API key, no packaged pipeline — me reasoning manually over real data and real news) as a reliability comparison against the automated runs: `GOOGL_2026-08-28_claude-code.md` (Hold/Neutral) and `AMZN_2026-08-28_claude-code.md` (Overweight). Neither fabricated data, neither showed internal disagreement (single-pass reasoning, not a multi-stage pipeline), and both cited real, current news the automated runs had no access to.

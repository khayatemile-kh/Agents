# WMT (Walmart Inc.) — Technical Analysis Report
**Analysis date: 2024-09-30 | Exchange: NMS | Sector: Consumer Defensive / Discount Stores**

---

## 1. Market Context and Big Picture

WMT has been one of the strongest large-cap performers in 2024. Based on the retrieved price data, the stock closed at **$51.64 on 2024-01-02** and finished at **$79.30 on 2024-09-30** — a gain of approximately **+53.6% year-to-date**. Note the price series reflects Walmart's 3-for-1 stock split (split factor 3.0 visible in the data on **2024-02-26**), so all levels are split-adjusted.

The advance has occurred in well-defined staircase legs:
- **Feb 2024** earnings gap (Feb 20 close $57.01 on 71.8M shares vs. $55.23 the prior day)
- **May 2024** earnings gap (May 16 close $62.68 on 60.5M shares vs. $58.59 prior day)
- **Aug 2024** earnings gap (Aug 15: open $72.58 vs. Aug 14 close $67.24, on 49.6M shares — the single largest gap of the year)

Each gap has acted as a new base, with the stock consolidating sideways-to-higher above the gap afterward — a classic institutional accumulation pattern.

**Verified snapshot (2024-09-30):** O 78.46 / H 79.49 / L 78.43 / C 79.30, volume 18.997M.

---

## 2. Indicator Selection Rationale (8 indicators, complementary, non-redundant)

| Layer | Indicators Chosen | Why |
|---|---|---|
| Trend | close_10_ema, close_50_sma, close_200_sma | Three horizons (short/medium/long) to separate impulse from trend without overlap |
| Momentum | macd, macds | MACD line + signal for crossover timing; histogram derivative is redundant with the pair here, and RSI covers a different (speed-of-move) dimension |
| Momentum (2nd axis) | rsi | Overbought/oversold and divergence — complements MACD's EMA-based momentum |
| Volatility/Structure | boll_ub, atr | Upper band flags overextension/breakout zones; ATR quantifies volatility for stop placement |

Deliberately excluded: boll/boll_lb (implied by band framework, boll middle confirmed via snapshot), macdh (derived from macd/macds), vwma (volume trends are readable from raw CSV), 10/50/200 redundancy kept intentional as a maturity stack.

---

## 3. Trend Analysis (Moving Averages)

**Verified values (2024-09-30):** 10 EMA **78.48**, 50 SMA **73.09**, 200 SMA **62.45**; Close **79.30**.

- **10 EMA (78.48):** Price is ~**+1.0%** above the 10 EMA. The EMA has risen in an unbroken series from 74.27 (Sep 3) to 78.48 (Sep 30), briefly flattening Sep 16–20 during the pullback before resuming upward. This is short-term bullish but the *thin margin* (only ~$0.82) means a single weak session could
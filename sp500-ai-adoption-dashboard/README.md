# S&P 500 AI Adoption Index — Local Setup

A self-contained dashboard of all 500 S&P 500 companies scored for AI adoption, with the
103 "AI Trailblazers" (top 20% per sector) highlighted, plus full per-company analyst
reports in the detail drawer.

## What's in this folder

- `index.html` — the dashboard (table, filters, search, charts, drawer)
- `reports.json` — the full analyst report text for every ticker (~38MB), loaded by the
  page when you click into a row

## Requirements

- Python 3 (already installed on macOS by default — check with `python3 --version`)
- No internet connection needed once you have this folder; everything runs locally

## Run it

1. Open Terminal.
2. Go to this folder:
   ```bash
   cd sp500-ai-adoption-dashboard
   ```
3. Start the server:
   ```bash
   python3 -m http.server 8420
   ```
4. Open your browser to:
   ```
   http://127.0.0.1:8420/index.html
   ```
5. To stop the server, go back to Terminal and press `Ctrl+C`.

## Important: don't just double-click index.html

Opening the file directly (`file://...`) will load the table, but clicking into a
company's full report will fail — browsers block loading `reports.json` from a local
file for security reasons. It has to be served over `http://`, which is what the steps
above do.

## Sharing this with someone else

Zip this whole folder (both files) and send it. They run the same two commands
(`cd` into the folder, then `python3 -m http.server 8420`) on their own machine and get
an identical, fully working copy — report drawer included.

## Troubleshooting

- **"Address already in use"** — port 8420 is taken (maybe a previous server is still
  running). Either stop that one, or use a different port:
  `python3 -m http.server 8421` (and adjust the URL you open accordingly).
- **Report drawer says "Couldn't load reports.json"** — you're probably opening
  `index.html` directly instead of through `http://127.0.0.1:...`. See above.
- **Page loads but looks empty/broken** — make sure both `index.html` and
  `reports.json` are in the same folder; the page won't work with just one of them.

## What won't work locally

The "Ask AIDE" chat button (if you ever see it) needs a live connection to Claude and
won't appear in this local copy — that's expected, not a bug.

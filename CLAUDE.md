# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A static, build-free scoreboard (GitHub Pages, installable as a web app) that aggregates each period's member scores from a Google Sheet into rankings, stats and per-member trend charts. UI copy, code comments, README and bot commit messages are in Traditional Chinese.

Live site: https://der46.github.io/cm-master-board/ — GitHub Pages deploys from the `main` branch root, so any push to `main` publishes it.

## Commands

There is no bundler, package.json, linter or test suite. The page loads JSON with `fetch`, so it must be served over HTTP:

```bash
python -m http.server 8000          # then open http://localhost:8000
```

Data script (Python 3.9+, standard library only — nothing to `pip install`):

```bash
DEFAULT_SPREADSHEET_ID=... GOOGLE_SHEETS_API_KEY=... python scripts/fetch_sheets.py   # download + rebuild
python scripts/fetch_sheets.py --offline                                              # rebuild from data/sheets/ only
```

Syntax checks (no CI runs these; do them by hand after edits):

```bash
python -m py_compile scripts/fetch_sheets.py
# index.html has one inline <script>; extract it and run node --check on the result
```

On Windows, `core.autocrlf` makes `data/scores.csv` show as modified after an offline rebuild even when `git diff` shows no content change — restore it with `git checkout -- data/scores.csv` rather than committing it.

## Architecture

### Data pipeline (Google Sheet → `data/` → page)

`.github/workflows/sync-google-sheets.yml` runs daily at UTC 22:00 (06:00 Asia/Taipei) and on manual dispatch. It never runs on push and does **not** deploy — deployment is GitHub Pages' built-in "Deploy from a branch" (`main` / root, `.nojekyll` skips Jekyll). Keep it that way: the point is that unchanged data produces no commit and therefore no redeploy.

`scripts/fetch_sheets.py`:

1. Reads sheet metadata, keeps only tabs whose **name parses as a period** (`parse_period`: `2026/10/1-10/7`, `2026-10-01~10-07`, `20261001-1007`, cross-year `2026/12/28-1/3`), and fetches them all in **one** `values:batchGet` call.
2. If no tab matches, exits non-zero **without touching** `data/` (guards against API hiccups wiping the data).
3. `save_sheets` writes each tab's raw values to `data/sheets/<start>_<end>.csv` plus `data/sheets/index.json` (gid, sheet name, file) and deletes CSVs for tabs that no longer exist.
4. `build` always parses from `data/sheets/` (so online and `--offline` produce identical output) into `data/scores.json` (page input) and `data/scores.csv` (UTF-8 with BOM for Excel).
5. `generatedAt` is reused from the previous `scores.json` when `periods` and `records` are unchanged, so no-op syncs leave the working tree clean.

The workflow commits `data/` only if it changed (`Update score data YYYY-MM-DD HH:MM`, Taipei time) and pushes with `git pull --rebase -X theirs` and 3 retries.

### Sheet parsing rules (`parse_sheet`)

- Header row: first row in the top 30 containing both a name keyword and a score keyword; otherwise the first row with a cell that is exactly a name keyword (rows above are usually notes like 計分方式).
- Score: the score-keyword column; else the sum of score-like headers; else the column **after** the last labelled header (untitled total column). Rows with score ≤ 0 are dropped. `parse_score` accepts only plain integers / comma-grouped numbers.
- `clean_name` normalises names so the same person merges across periods: strips roster number prefixes (`35.明志`), converts full-width brackets to half-width, removes spaces around brackets.
- `returning_player_name`: rows named `回歸` / `回歸(…)` take the member name from the note column, and the `回歸(…)` marker moves into the note.
- Team: the team column via `normalize_team`, else 主隊 / 二隊 / 三隊 / 四隊 found in the sheet name or row, else 未標註.
- A period's `key` is the tab's gid (a string; gid `0` is valid).

These rules are also documented in README's 試算表格式 section — update both together. After changing parsing, run `--offline` and commit the regenerated `data/scores.json` / `scores.csv`.

### Front end (`index.html`, single file: CSS + HTML + one inline script)

- Chart.js 4.4.1 (jsDelivr) and Google Fonts are the only external resources. Icons are inline SVG `<symbol>`s referenced with `<use href="#i-…">`.
- **Loading:** `loadData` fetches `data/scores.json` with `cache: "no-cache"` (revalidates, 304 when unchanged) and maps records into `rawRows` (`period`, `periodLabel`, `name`, `team`, `score`, `note`); records whose period is unknown are dropped. `periodByKey` adds an `order` index used for sorting and "previous period" comparisons.
- **State** is plain module-level `let`s (`selectedMember`, `sortState`, `barEnd`, …) and DOM refs in `els`.
- **Rendering:** `refreshAll` recomputes `getFilteredRows()` → `aggregateMembers()` (rank = order by total score) and redraws everything: team nav counts, KPIs, table, trend chart, attendance gauge and the per-period bar chart. Charts are destroyed and recreated on every refresh.
- Two separate searches: `searchInput` filters the underlying rows (affects ranks and stats); `rankSearch` only filters table rows, and ranks stay those among all members.
- Trend chart compares the member to the per-period average of the same team/period filter, ignoring the keyword. Gauge = periods attended ÷ periods since the member's first appearance. Bar chart shows `BAR_PERIODS` (8) periods per page; `barEnd` pins paging, `null` follows the selected period.
- **Shareable URLs:** `q`, `team`, `period`, `member` (omitted when it's the default top member), `sort` (`key:dir`) are written with `history.replaceState` and restored once on load.
- `data/scores.json` format is consumed only here — change the script and page together.

## Conventions

- Keep the site build-free and the script dependency-free (standard library only).
- Write user-facing text, comments and README in Traditional Chinese, matching existing tone.
- API keys live only in GitHub Secrets (`DEFAULT_SPREADSHEET_ID`, `GOOGLE_SHEETS_API_KEY`); never put them in the front end or committed files.
- For behaviour-preserving front-end changes there are no tests: verify by comparing outputs before/after (e.g. extract functions from `index.html` and run them in Node against `data/scores.json`) and by loading the page over `http.server`.

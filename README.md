<p align="center">
  <img src="icon.svg" width="128" height="128" alt="CM大佬群專用記分板 icon" />
</p>

<h1 align="center">CM大佬群專用記分板</h1>

<p align="center">
  遊戲團隊成員數據儀表板 —— 自動從 Google Sheets 抓取每期分數，彙整成排行、統計與個人走勢圖。
</p>

<p align="center">
  🔗 <a href="https://der46.github.io/cm-master-board/">https://der46.github.io/cm-master-board/</a>
</p>

---

## 功能

- **總覽統計**：成員數、總累積分數、最高個人總分、資料時段數
- **篩選**：依成員名稱 / 備註搜尋，並可依時段（分頁）與隊伍篩選
- **個人走勢圖**：以 Chart.js 繪製單一成員各期分數變化，附總分、平均、最高單期、參與筆數
- **成員明細表**：依總分由高到低排序，點選任一列即可切換走勢圖
- **可安裝成 App**：附 SVG / PNG 圖示與 Web App Manifest，手機可「加入主畫面」

## 運作方式

```
Google Sheets ──(GitHub Actions, Sheets API)──▶ data/sheets-values.json ──▶ index.html（GitHub Pages）
```

1. [`.github/workflows/pages.yml`](.github/workflows/pages.yml) 在 **push 到 `main`**、**手動觸發**，以及 **每天 UTC 22:00（台灣時間 06:00）** 時執行。
2. [`scripts/build-data.js`](scripts/build-data.js) 透過 Google Sheets API 讀取試算表，只保留名稱符合時段格式的分頁，輸出成 `data/sheets-values.json`。
3. 整個專案連同資料檔一起部署到 GitHub Pages；前端 [`index.html`](index.html) 讀取該 JSON 後在瀏覽器端完成解析與統計。

API 金鑰只存在 GitHub Secrets，不會出現在前端。

## 試算表格式

**分頁名稱**需為時段格式，例如：

| 寫法 | 範例 |
| --- | --- |
| 完整日期區間 | `2026/10/1-10/7`、`2026-10-01~10-07` |
| 精簡寫法 | `20261001-1007` |

**表頭**（前 30 列內自動偵測）需同時包含：

- 成員欄：`成員`、`隊員`、`姓名`、`名稱`、`暱稱`、`玩家` 或 `Name`
- 分數欄：`總分`、`合計`、`總計`、`得分`、`分數`、`Score` 或 `Total`

隊伍可由 `隊伍` 欄或分頁 / 列內容中的 `主隊`、`二隊`、`三隊`、`四隊` 判斷。

## 部署設定

1. 在 repo 的 **Settings → Pages** 將 Source 設為 **GitHub Actions**。
2. 在 **Settings → Secrets and variables → Actions** 新增：

   | Secret | 說明 |
   | --- | --- |
   | `DEFAULT_SPREADSHEET_ID` | 試算表網址 `/d/` 與 `/edit` 之間的 ID |
   | `GOOGLE_SHEETS_API_KEY` | 已啟用 Google Sheets API 的金鑰（試算表需設為「知道連結的人可檢視」） |

3. push 到 `main` 或在 Actions 頁面手動執行 workflow 即可。

## 本機開發

需要 Node.js 18 以上（使用內建 `fetch`）。

```bash
DEFAULT_SPREADSHEET_ID=你的試算表ID GOOGLE_SHEETS_API_KEY=你的金鑰 node scripts/build-data.js
```

```bash
npx serve .
```

接著開啟終端機顯示的網址即可（直接用 `file://` 開啟會因瀏覽器限制而無法讀取 JSON）。

## 專案結構

```
.
├── index.html              # 儀表板（HTML / CSS / JS 單檔）
├── icon.svg                # App 圖示（向量原檔）
├── icon-180.png            # Apple touch icon
├── icon-192.png            # PWA 圖示
├── icon-512.png            # PWA 圖示 / maskable
├── manifest.webmanifest    # Web App Manifest
├── scripts/
│   └── build-data.js       # 從 Google Sheets 產生 data/sheets-values.json
└── .github/workflows/
    └── pages.yml           # 建置並部署到 GitHub Pages
```

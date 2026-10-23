"""
從 Google Sheets 下載各期分數，整理成網頁可直接使用的資料檔。

輸出：
    data/sheets/*.csv         每個時段分頁的原始內容（一個分頁一個檔）
    data/sheets/index.json    分頁清單（gid、分頁名稱、檔名）
    data/scores.json          網頁讀取用（periods + records）
    data/scores.csv           方便下載 / 用 Excel 開啟

用法：
    DEFAULT_SPREADSHEET_ID=... GOOGLE_SHEETS_API_KEY=... python scripts/fetch_sheets.py
    python scripts/fetch_sheets.py --offline   # 不連線，直接用 data/sheets/ 裡已下載的分頁重新產生

只使用 Python 標準函式庫，不需要 pip install。
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SHEETS_DIR = DATA_DIR / "sheets"

NAME_KEYWORDS = ["成員", "成員名稱", "隊員", "隊員名稱", "姓名", "名稱", "名字", "暱稱", "玩家", "玩家名稱", "Name", "name"]
TEAM_KEYWORDS = ["隊伍", "隊別", "團隊", "組別", "Team", "team"]
NOTE_KEYWORDS = ["備註", "說明", "狀態", "Note", "note", "Remark", "remark"]
SCORE_KEYWORDS = ["總分", "合計", "總計", "累計", "總合", "總和", "小計", "得分", "分數", "Score", "score", "Total", "total"]

# 偵測表頭列用（與欄位對應的關鍵字略有不同，沿用原本網頁的規則）
HEADER_NAME_KEYWORDS = ["成員", "成員名稱", "隊員", "姓名", "名稱", "暱稱", "玩家", "Name", "name"]
HEADER_SCORE_KEYWORDS = ["總分", "合計", "總計", "累計", "總合", "總和", "得分", "分數", "Score", "score", "Total", "total"]

SCORE_EXCLUDE_KEYWORDS = ["日期", "時間", "進隊", "入隊", "退隊", "備註", "說明", "名稱", "姓名", "成員", "隊伍", "隊別", "團隊", "組別", "gid", "sheet"]
BANNED_NAMES = {"主隊", "二隊", "三隊", "四隊", "總分", "合計", "小計", "隊伍", "備註", "成員", "姓名", "名稱", "團隊", "分數"}

TEAM_ORDER = ["主隊", "二隊", "三隊", "四隊"]
UNKNOWN_TEAM = "未標註"


# ==========================================================
# 基本工具
# ==========================================================
def text(value) -> str:
    return "" if value is None else str(value).strip()


# ==========================================================
# 分頁名稱 → 時段
# ==========================================================
def _valid_month_day(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def _parse_compact_month_day(token: str):
    digits = re.sub(r"\D", "", token or "")
    if len(digits) == 2:
        month, day = int(digits[0]), int(digits[1])
    elif len(digits) == 3:
        month, day = int(digits[0]), int(digits[1:])
    elif len(digits) == 4:
        month, day = int(digits[:2]), int(digits[2:])
    else:
        return None
    return (month, day) if _valid_month_day(month, day) else None


def parse_period(sheet_name: str):
    """
    支援：
        2026/10/1-10/7、2026-10-01~10-07、2026/12/28-2027/1/3
        20261001-1007、2026101-107
    不符合格式的分頁回傳 None（會被略過）。
    """
    s = text(sheet_name)

    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*[-~～]\s*(?:(\d{4})[/-])?(\d{1,2})[/-](\d{1,2})$", s)
    if m:
        year = int(m.group(1))
        start = (int(m.group(2)), int(m.group(3)))
        end = (int(m.group(5)), int(m.group(6)))
        end_year = int(m.group(4)) if m.group(4) else None
    else:
        m = re.match(r"^(\d{4})(\d{2,4})\s*[-~～]\s*(\d{1,4})$", s)
        if not m:
            return None
        year = int(m.group(1))
        start = _parse_compact_month_day(m.group(2))
        end = _parse_compact_month_day(m.group(3))
        end_year = None

    if not start or not end or not _valid_month_day(*start) or not _valid_month_day(*end):
        return None

    if end_year is None:
        # 跨年：12/28-1/3
        end_year = year + 1 if end < start else year

    try:
        start_date = date(year, *start)
        end_date = date(end_year, *end)
    except ValueError:
        return None

    return {
        "label": f"{year}/{start[0]}/{start[1]}-{end[0]}/{end[1]}",
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
    }


# ==========================================================
# 欄位偵測與資料解析
# ==========================================================
def normalize_team(value) -> str:
    t = text(value)
    if not t or t == "未標注":
        return UNKNOWN_TEAM
    if "主" in t:
        return "主隊"
    if "二" in t or "2" in t:
        return "二隊"
    if "三" in t or "3" in t:
        return "三隊"
    if "四" in t or "4" in t:
        return "四隊"
    return t


def detect_team(sheet_name: str, row_values) -> str:
    joined = f"{sheet_name} {' '.join(row_values)}"
    for team in TEAM_ORDER:
        if team in joined:
            return team
    return UNKNOWN_TEAM


def is_date_like(value: str) -> bool:
    return bool(re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", value) or re.fullmatch(r"\d{1,2}[/-]\d{1,2}", value))


def parse_score(value) -> float:
    t = text(value)
    if not t or is_date_like(t):
        return 0
    if re.search(r"[A-Za-z一-龥]", t):
        return 0
    if not re.fullmatch(r"-?\d{1,3}(,\d{3})*|-?\d+", t):
        return 0
    n = int(t.replace(",", ""))
    return n if n > 0 else 0


def is_invalid_name(name: str) -> bool:
    if not name or name in BANNED_NAMES or len(name) > 50:
        return True
    return name.replace(",", "").isdigit()


def is_likely_score_header(header: str) -> bool:
    if not header or any(k in header for k in SCORE_EXCLUDE_KEYWORDS):
        return False
    return any(k in header for k in SCORE_KEYWORDS)


def find_header(headers, keywords) -> str:
    for k in keywords:
        if k in headers:
            return k
    for k in keywords:
        for h in headers:
            if k in h:
                return h
    return ""


def find_header_row(values) -> int:
    for i, row in enumerate(values[:30]):
        joined = " ".join(text(v) for v in row)
        if any(k in joined for k in HEADER_NAME_KEYWORDS) and any(k in joined for k in HEADER_SCORE_KEYWORDS):
            return i

    # 表頭上方常有「計分方式」「主隊總分」等說明列；找第一個有「姓名」這類格子的列
    for i, row in enumerate(values[:30]):
        if any(text(v) in HEADER_NAME_KEYWORDS for v in row):
            return i

    return 0


def returning_player_name(name: str, note: str) -> str:
    """
    「回歸」或「回歸(健豪)」這類列，真正的玩家名稱寫在備註欄（例如「秀齡(健豪)」）。
    回傳備註裡的名字；備註看起來不是名字（空白、含日期的說明文字）就回傳空字串。
    """
    if not re.fullmatch(r"回歸(\(.+\)|（.+）)?", name):
        return ""
    if not note or len(note) > 20 or re.search(r"\d+/\d+", note):
        return ""
    return clean_name(note)


def clean_name(name: str) -> str:
    """去掉名單編號前綴：「35.明志」→「明志」、「21 .豪豪」→「豪豪」。"""
    stripped = re.sub(r"^\d+\s*\.\s*", "", name)
    return stripped or name


def unique_headers(row):
    used = {}
    result = []
    for i, h in enumerate(row):
        base = text(h) or f"欄位{i + 1}"
        used[base] = used.get(base, 0) + 1
        result.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return result


def parse_sheet(sheet_name: str, values):
    """把一個分頁的原始 values（二維陣列）轉成 [{name, team, score, note}, ...]。"""
    if not values:
        return []

    header_index = find_header_row(values)
    header_row = [text(v) for v in values[header_index]]

    # 資料列可能比表頭長（例如總分欄沒有標題），表頭補齊到最長的資料列
    width = max(len(r) for r in values[header_index:])
    headers = unique_headers(header_row + [""] * (width - len(header_row)))

    # 沒有總分標題時，最後一個有標題欄位的下一欄通常就是總分
    labelled = [i for i, h in enumerate(header_row) if h]
    trailing_h = headers[labelled[-1] + 1] if labelled and labelled[-1] + 1 < width else ""

    name_h = find_header(headers, NAME_KEYWORDS)
    team_h = find_header(headers, TEAM_KEYWORDS)
    note_h = find_header(headers, NOTE_KEYWORDS)
    score_h = find_header(headers, SCORE_KEYWORDS)

    records = []

    for raw in values[header_index + 1:]:
        row = {h: text(raw[i]) if i < len(raw) else "" for i, h in enumerate(headers)}
        cells = list(row.values())
        if not any(cells):
            continue

        name = clean_name(row.get(name_h, "")) if name_h else ""
        if not name:
            # 沒有成員欄時，取第一個看起來像名字的格子
            name = next((v for v in cells if v and not is_invalid_name(v) and not parse_score(v) and len(v) <= 30), "")
        if is_invalid_name(name):
            continue

        note = row.get(note_h, "") if note_h else ""
        player = returning_player_name(name, note)
        if player:
            # 名稱改用備註裡的玩家，原本的「回歸(…)」標記移到備註
            name, note = player, name

        score = parse_score(row.get(score_h)) if score_h else 0
        if not score:
            score = sum(parse_score(v) for h, v in row.items() if is_likely_score_header(h))
        if not score and not score_h and trailing_h:
            score = parse_score(row.get(trailing_h))
        if score <= 0:
            continue

        team_cell = row.get(team_h, "") if team_h else ""
        team = normalize_team(team_cell) if team_cell else detect_team(sheet_name, cells)

        records.append({
            "name": name,
            "team": team,
            "score": score,
            "note": note,
        })

    return records


# ==========================================================
# Google Sheets API
# ==========================================================
def api_get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=60) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"Google Sheets API 錯誤 HTTP {e.code}：{body}") from None


def fetch_raw(spreadsheet_id: str, api_key: str):
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id)}"
    key = urllib.parse.quote(api_key)

    meta = api_get(f"{base}?fields=sheets(properties(sheetId,title))&key={key}")
    titles = [(str(s["properties"]["sheetId"]), s["properties"]["title"]) for s in meta.get("sheets", [])]
    targets = [(gid, title) for gid, title in titles if parse_period(title)]

    print(f"共 {len(titles)} 個分頁，其中 {len(targets)} 個符合時段格式。")
    if not targets:
        return []

    # 一次 batchGet 抓完所有分頁
    ranges = "&".join("ranges=" + urllib.parse.quote(f"'{title}'") for _, title in targets)
    batch = api_get(f"{base}/values:batchGet?{ranges}&majorDimension=ROWS&valueRenderOption=FORMATTED_VALUE&key={key}")

    return [
        {"gid": gid, "sheetName": title, "values": vr.get("values", [])}
        for (gid, title), vr in zip(targets, batch.get("valueRanges", []))
    ]


# ==========================================================
# 已下載分頁（data/sheets/）
# ==========================================================
def save_sheets(raw_sheets):
    """每個分頁存成一個 CSV，並移除 Google Sheets 上已不存在的舊檔。"""
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)

    index = []
    used = set()

    for sheet in raw_sheets:
        info = parse_period(sheet["sheetName"])
        filename = f"{info['start']}_{info['end']}.csv"
        if filename in used:
            filename = f"{info['start']}_{info['end']}_{sheet['gid']}.csv"
        used.add(filename)

        with (SHEETS_DIR / filename).open("w", newline="", encoding="utf-8") as f:
            csv.writer(f, lineterminator="\n").writerows(sheet["values"])

        index.append({"gid": sheet["gid"], "sheetName": sheet["sheetName"], "file": filename})

    for old in SHEETS_DIR.glob("*.csv"):
        if old.name not in used:
            old.unlink()

    (SHEETS_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已儲存 {len(index)} 個分頁到 {SHEETS_DIR.relative_to(ROOT)}/")


def load_sheets():
    index_path = SHEETS_DIR / "index.json"
    if not index_path.exists():
        sys.exit(f"找不到 {index_path.relative_to(ROOT)}，請先連線下載一次。")

    sheets = []
    for item in json.loads(index_path.read_text(encoding="utf-8")):
        with (SHEETS_DIR / item["file"]).open(newline="", encoding="utf-8") as f:
            sheets.append({"gid": item["gid"], "sheetName": item["sheetName"], "values": list(csv.reader(f))})
    return sheets


# ==========================================================
# 輸出
# ==========================================================
def build(raw_sheets, generated_at):
    periods = []
    records = []

    for sheet in raw_sheets:
        info = parse_period(sheet["sheetName"])
        if not info:
            continue

        key = str(sheet.get("gid") or sheet["sheetName"])
        rows = parse_sheet(sheet["sheetName"], sheet.get("values", []))
        print(f"  {sheet['sheetName']}: {len(rows)} 筆")

        periods.append({"key": key, "sheetName": sheet["sheetName"], **info})
        records.extend({"period": key, **r} for r in rows)

    periods.sort(key=lambda p: (p["start"], p["sheetName"]))

    return {
        "generatedAt": generated_at,
        "periods": periods,
        "records": records,
    }


def write_outputs(data):
    DATA_DIR.mkdir(exist_ok=True)

    json_path = DATA_DIR / "scores.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    labels = {p["key"]: p["label"] for p in data["periods"]}
    order = {p["key"]: i for i, p in enumerate(data["periods"])}
    csv_path = DATA_DIR / "scores.csv"
    # utf-8-sig：讓 Excel 正確辨識中文
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["時段", "成員", "隊伍", "分數", "備註"])
        for r in sorted(data["records"], key=lambda r: (order[r["period"]], -r["score"])):
            w.writerow([labels[r["period"]], r["name"], r["team"], r["score"], r["note"]])

    print(f"已產生 {json_path.relative_to(ROOT)}、{csv_path.relative_to(ROOT)}：{len(data['periods'])} 個時段，{len(data['records'])} 筆資料。")


def main():
    # Windows 終端機預設不是 UTF-8，避免中文訊息變亂碼
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="不連線，直接用 data/sheets/ 重新產生 scores.json / scores.csv")
    args = parser.parse_args()

    scores_path = DATA_DIR / "scores.json"
    previous = json.loads(scores_path.read_text(encoding="utf-8")) if scores_path.exists() else None

    if not args.offline:
        spreadsheet_id = os.environ.get("DEFAULT_SPREADSHEET_ID")
        api_key = os.environ.get("GOOGLE_SHEETS_API_KEY")
        if not spreadsheet_id or not api_key:
            sys.exit("缺少環境變數 DEFAULT_SPREADSHEET_ID 或 GOOGLE_SHEETS_API_KEY。")

        raw = fetch_raw(spreadsheet_id, api_key)
        if not raw:
            # 避免 API 暫時異常時把已下載的資料清空
            sys.exit("沒有抓到任何符合時段格式的分頁，保留現有資料不更新。")
        save_sheets(raw)

    data = build(load_sheets(), datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # 內容沒變就沿用舊的時間戳，避免每天產生只改時間的 commit
    if previous and previous.get("periods") == data["periods"] and previous.get("records") == data["records"]:
        data["generatedAt"] = previous.get("generatedAt", data["generatedAt"])

    write_outputs(data)


if __name__ == "__main__":
    main()

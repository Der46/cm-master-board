const fs = require("fs");
const path = require("path");

const DEFAULT_SPREADSHEET_ID = process.env.DEFAULT_SPREADSHEET_ID;
const GOOGLE_SHEETS_API_KEY = process.env.GOOGLE_SHEETS_API_KEY;

if (!DEFAULT_SPREADSHEET_ID) {
    throw new Error("Missing DEFAULT_SPREADSHEET_ID secret.");
}

if (!GOOGLE_SHEETS_API_KEY) {
    throw new Error("Missing GOOGLE_SHEETS_API_KEY secret.");
}

function normalizeText(value) {
    return String(value ?? "").trim();
}

function isValidMonthDay(month, day) {
    return (
        Number.isInteger(month) &&
        Number.isInteger(day) &&
        month >= 1 &&
        month <= 12 &&
        day >= 1 &&
        day <= 31
    );
}

function parseCompactMonthDay(token) {
    const text = String(token ?? "").replace(/\D/g, "");
    if (!text) return null;

    const candidates = [];

    if (text.length === 2) {
        candidates.push({
            month: Number(text.slice(0, 1)),
            day: Number(text.slice(1, 2))
        });
    }

    if (text.length === 3) {
        candidates.push({
            month: Number(text.slice(0, 1)),
            day: Number(text.slice(1, 3))
        });
    }

    if (text.length === 4) {
        candidates.push({
            month: Number(text.slice(0, 2)),
            day: Number(text.slice(2, 4))
        });
    }

    return candidates.find(x => isValidMonthDay(x.month, x.day)) || null;
}

function parseTargetPeriodSheetName(sheetName) {
    const s = normalizeText(sheetName);

    let match = s.match(/^(\d{4})[\/-](\d{1,2})[\/-](\d{1,2})\s*[-~～]\s*(?:(\d{4})[\/-])?(\d{1,2})[\/-](\d{1,2})$/);

    if (match) {
        const year = Number(match[1]);
        const startMonth = Number(match[2]);
        const startDay = Number(match[3]);
        const endMonth = Number(match[5]);
        const endDay = Number(match[6]);

        if (
            isValidMonthDay(startMonth, startDay) &&
            isValidMonthDay(endMonth, endDay)
        ) {
            return {
                year,
                startMonth,
                startDay,
                endMonth,
                endDay,
                label: `${year}/${startMonth}/${startDay}-${endMonth}/${endDay}`
            };
        }
    }

    match = s.match(/^(\d{4})(\d{2,4})\s*[-~～]\s*(\d{1,4})$/);

    if (match) {
        const year = Number(match[1]);
        const start = parseCompactMonthDay(match[2]);
        const end = parseCompactMonthDay(match[3]);

        if (start && end) {
            return {
                year,
                startMonth: start.month,
                startDay: start.day,
                endMonth: end.month,
                endDay: end.day,
                label: `${year}/${start.month}/${start.day}-${end.month}/${end.day}`
            };
        }
    }

    return null;
}

function isTargetPeriodSheetName(sheetName) {
    return Boolean(parseTargetPeriodSheetName(sheetName));
}

function detectPeriodFromSheetName(sheetName) {
    const parsed = parseTargetPeriodSheetName(sheetName);
    return parsed ? parsed.label : normalizeText(sheetName);
}

async function fetchSpreadsheetSheets(spreadsheetId) {
    const url =
        `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(spreadsheetId)}` +
        `?fields=sheets(properties(sheetId,title))` +
        `&key=${encodeURIComponent(GOOGLE_SHEETS_API_KEY)}`;

    const response = await fetch(url);

    if (!response.ok) {
        const text = await response.text();
        throw new Error(`取得分頁清單失敗，HTTP ${response.status}。${text}`);
    }

    const data = await response.json();

    const allSheets = (data.sheets || []).map(sheet => ({
        gid: String(sheet.properties.sheetId),
        sheetName: sheet.properties.title,
        period: detectPeriodFromSheetName(sheet.properties.title)
    }));

    return allSheets.filter(sheet => isTargetPeriodSheetName(sheet.sheetName));
}

async function fetchSheetValues(spreadsheetId, sheetConfig) {
    const range = encodeURIComponent(`'${sheetConfig.sheetName}'`);

    const url =
        `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(spreadsheetId)}` +
        `/values/${range}` +
        `?majorDimension=ROWS` +
        `&valueRenderOption=FORMATTED_VALUE` +
        `&key=${encodeURIComponent(GOOGLE_SHEETS_API_KEY)}`;

    const response = await fetch(url);

    if (!response.ok) {
        const text = await response.text();
        throw new Error(`${sheetConfig.sheetName} 讀取失敗，HTTP ${response.status}。${text}`);
    }

    const data = await response.json();

    return data.values || [];
}

async function main() {
    console.log("Fetching Google Sheets metadata...");

    const availableSheets = await fetchSpreadsheetSheets(DEFAULT_SPREADSHEET_ID);

    console.log(`Found ${availableSheets.length} target sheets.`);

    const sheets = [];

    for (const sheetConfig of availableSheets) {
        console.log(`Fetching sheet: ${sheetConfig.sheetName}`);

        const values = await fetchSheetValues(DEFAULT_SPREADSHEET_ID, sheetConfig);

        sheets.push({
            ...sheetConfig,
            values
        });
    }

    const output = {
        fetchedAt: new Date().toISOString(),
        sheets
    };

    const dataDir = path.join(process.cwd(), "data");

    if (!fs.existsSync(dataDir)) {
        fs.mkdirSync(dataDir, { recursive: true });
    }

    const outputPath = path.join(dataDir, "sheets-values.json");

    fs.writeFileSync(outputPath, JSON.stringify(output, null, 2), "utf8");

    console.log(`Generated: ${outputPath}`);
}

main().catch(error => {
    console.error(error);
    process.exit(1);
});

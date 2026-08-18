/** Generate consolidated and attachment-style per-CCC Taiwan trade workbooks. */

import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const COLORS = {
  navy: "#17365D", blue: "#2F75B5", lightBlue: "#D9EAF7", header: "#D9E2F3",
  stripe: "#F4F7FB", border: "#B4C7E7", text: "#1F2937", warning: "#FFF2CC",
};

function parseArgs(argv) {
  const args = {};
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    if (!key?.startsWith("--")) throw new Error(`Unexpected argument: ${key}`);
    args[key.slice(2)] = argv[index + 1];
  }
  if (!args.metrics || !args["output-dir"] || !args.flow) {
    throw new Error("Usage: excel_writer.mjs --metrics file --output-dir dir --flow import|export");
  }
  args.scope ??= "all";
  args.concurrency = Number(args.concurrency ?? 6);
  args.limitCcc = args["limit-ccc"] ? Number(args["limit-ccc"]) : null;
  if (!new Set(["all", "consolidated", "per-ccc"]).has(args.scope)) throw new Error("Invalid scope");
  if (!new Set(["import", "export"]).has(args.flow)) throw new Error("Invalid flow");
  if (!Number.isInteger(args.concurrency) || args.concurrency < 1 || args.concurrency > 12) {
    throw new Error("--concurrency must be an integer from 1 to 12");
  }
  return args;
}

function excelDate(month) {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year, number - 1, 1));
}

function shiftMonth(month, delta) {
  const [year, number] = month.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, number - 1 + delta, 1));
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, "0")}`;
}

function groupRows(rows) {
  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.ccc_code)) groups.set(row.ccc_code, []);
    groups.get(row.ccc_code).push(row);
  }
  for (const values of groups.values()) values.sort((a, b) => a.month.localeCompare(b.month));
  return new Map([...groups.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function applyTitle(sheet, endColumn, title, subtitle) {
  sheet.mergeCells(`A1:${endColumn}1`);
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${endColumn}1`).format = {
    fill: COLORS.navy, font: { bold: true, color: "#FFFFFF", size: 15 },
    verticalAlignment: "center",
  };
  sheet.getRange("A1").format.rowHeight = 30;
  sheet.mergeCells(`A2:${endColumn}2`);
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endColumn}2`).format = {
    fill: COLORS.lightBlue, font: { color: COLORS.text, size: 10 },
    verticalAlignment: "center", wrapText: true,
  };
  sheet.getRange("A2").format.rowHeight = 28;
}

function styleHeader(range) {
  range.format = {
    fill: COLORS.header, font: { bold: true, color: COLORS.text },
    horizontalAlignment: "center", verticalAlignment: "center", wrapText: true,
    borders: { preset: "all", style: "thin", color: COLORS.border },
  };
  range.format.rowHeight = 36;
}

function styleData(sheet, startRow, endRow, lastColumn) {
  sheet.getRange(`A${startRow}:${lastColumn}${endRow}`).format = {
    font: { color: COLORS.text, size: 10 },
    borders: { insideHorizontal: { style: "thin", color: COLORS.border } },
    verticalAlignment: "center",
  };
  for (let row = startRow; row <= endRow; row += 2) {
    sheet.getRange(`A${row}:${lastColumn}${row}`).format.fill = COLORS.stripe;
  }
}

function sourceSubtitle(flow, sourceUrl) {
  return `${flow.toUpperCase()} | Value: USD (${flow === "import" ? "CIF" : "FOB"}) | ` +
    `Quantity: declared statistical unit | Weight: kg | Source: ${sourceUrl}`;
}

function perCccFormulas(rows, startRow) {
  const columns = Array.from({ length: 14 }, () => []);
  const monthRows = new Map(rows.map((row, offset) => [row.month, startRow + offset]));
  rows.forEach((row, offset) => {
    const r = startRow + offset;
    const mom = monthRows.get(shiftMonth(row.month, -1));
    const yoy = monthRows.get(shiftMonth(row.month, -12));
    columns[0].push([`=D${r}/1000000`]);
    columns[1].push([`=IF(OR(B${r}="",B${r}=0,D${r}=""),"",D${r}/B${r})`]);
    columns[2].push([`=IF(OR(C${r}="",C${r}=0,D${r}=""),"",D${r}/C${r})`]);
    columns[3].push([row.unit_value_3mma !== null ? `=IF(COUNT(F${r - 2}:F${r})=3,AVERAGE(F${r - 2}:F${r}),"")` : ""]);
    columns[4].push([row.quantity_mom !== null && mom ? `=IFERROR(B${r}/B${mom}-1,"")` : ""]);
    columns[5].push([row.weight_mom !== null && mom ? `=IFERROR(C${r}/C${mom}-1,"")` : ""]);
    columns[6].push([row.value_mom !== null && mom ? `=IFERROR(D${r}/D${mom}-1,"")` : ""]);
    columns[7].push([row.unit_value_mom !== null && mom ? `=IFERROR(F${r}/F${mom}-1,"")` : ""]);
    columns[8].push([row.kg_value_mom !== null && mom ? `=IFERROR(G${r}/G${mom}-1,"")` : ""]);
    columns[9].push([row.quantity_yoy !== null && yoy ? `=IFERROR(B${r}/B${yoy}-1,"")` : ""]);
    columns[10].push([row.weight_yoy !== null && yoy ? `=IFERROR(C${r}/C${yoy}-1,"")` : ""]);
    columns[11].push([row.value_yoy !== null && yoy ? `=IFERROR(D${r}/D${yoy}-1,"")` : ""]);
    columns[12].push([row.unit_value_yoy !== null && yoy ? `=IFERROR(F${r}/F${yoy}-1,"")` : ""]);
    columns[13].push([row.kg_value_yoy !== null && yoy ? `=IFERROR(G${r}/G${yoy}-1,"")` : ""]);
  });
  return columns;
}

async function createPerCccWorkbook(code, rows, flow, sourceUrl) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Monthly Data");
  sheet.showGridLines = false;
  const latest = rows.at(-1);
  const unit = latest.quantity_unit || "N/A";
  applyTitle(
    sheet, "R", `Taiwan ${flow[0].toUpperCase() + flow.slice(1)} Trade | CCC ${code}`,
    sourceSubtitle(flow, sourceUrl),
  );
  sheet.getRange("A4:R4").values = [[
    "Date", `Quantity (${unit})`, "Weight (kg)", "Value (USD)", "Value (mn USD)",
    `Unit Value (USD/${unit})`, "Value (USD/kg)", "Unit Value (3MMA)",
    "Quantity (MoM)", "Weight (MoM)", "Value (MoM)", "Unit Value (MoM)",
    "USD/kg (MoM)", "Quantity (YoY)", "Weight (YoY)", "Value (YoY)",
    "Unit Value (YoY)", "USD/kg (YoY)",
  ]];
  styleHeader(sheet.getRange("A4:R4"));
  const start = 5;
  const end = start + rows.length - 1;
  sheet.getRange(`A${start}:D${end}`).values = rows.map((row) => [
    excelDate(row.month), row.quantity, row.weight_kg, row.value_usd,
  ]);
  const formulas = perCccFormulas(rows, start);
  "EFGHIJKLMNOPQR".split("").forEach((column, index) => {
    sheet.getRange(`${column}${start}:${column}${end}`).formulas = formulas[index];
  });
  styleData(sheet, start, end, "R");
  sheet.getRange(`A${start}:A${end}`).format.numberFormat = "yyyy-mm";
  sheet.getRange(`B${start}:D${end}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`E${start}:H${end}`).format.numberFormat = "#,##0.0000";
  sheet.getRange(`I${start}:R${end}`).format.numberFormat = "0.00%";
  sheet.getRange(`A${start}:R${end}`).format.rowHeight = 22;
  sheet.getRange(`A1:A${end}`).format.columnWidth = 12;
  sheet.getRange(`B1:R${end}`).format.columnWidth = 16;
  sheet.freezePanes.freezeRows(4);

  const raw = workbook.worksheets.add("Raw Data");
  raw.showGridLines = false;
  applyTitle(raw, "L", `Raw Official Data | CCC ${code}`, `Source endpoint: ${sourceUrl}`);
  raw.getRange("A4:L4").values = [[
    "Date", "Flow", "CCC Code", "HS6", "HS8", "Quantity Unit", "Quantity",
    "Weight (kg)", "Value (USD)", "Record Status", "Fetched at UTC", "Source URL",
  ]];
  styleHeader(raw.getRange("A4:L4"));
  raw.getRange(`A${start}:L${end}`).values = rows.map((row) => [
    excelDate(row.month), row.flow, row.ccc_code, row.hs6, row.hs8, row.quantity_unit,
    row.quantity, row.weight_kg, row.value_usd, row.record_status, row.fetched_at_utc, sourceUrl,
  ]);
  styleData(raw, start, end, "L");
  raw.getRange(`A${start}:A${end}`).format.numberFormat = "yyyy-mm";
  raw.getRange(`C${start}:E${end}`).format.numberFormat = "@";
  raw.getRange(`G${start}:I${end}`).format.numberFormat = "#,##0.00";
  raw.getRange(`K${start}:K${end}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
  raw.getRange(`A1:A${end}`).format.columnWidth = 12;
  raw.getRange(`B1:K${end}`).format.columnWidth = 18;
  raw.getRange(`L1:L${end}`).format.columnWidth = 55;
  raw.freezePanes.freezeRows(4);

  const mapping = workbook.worksheets.add("CCC Mapping");
  mapping.showGridLines = false;
  applyTitle(mapping, "B", `CCC Mapping | ${code}`, "Official Taiwan customs classification metadata");
  mapping.getRange("A4:B12").values = [
    ["Field", "Value"], ["CCC Code (11-digit)", code], ["HS6", latest.hs6],
    ["Taiwan Tariff No. (HS8)", latest.hs8], ["Chinese Description", latest.commodity_name_zh],
    ["English Description", latest.commodity_name_en], ["Quantity Unit", unit],
    ["Weight Unit", "KGM"], ["Trade Flow", flow],
  ];
  styleHeader(mapping.getRange("A4:B4"));
  styleData(mapping, 5, 12, "B");
  mapping.getRange("A1:A12").format.columnWidth = 25;
  mapping.getRange("B1:B12").format.columnWidth = 100;
  mapping.getRange("B5:B12").format.wrapText = true;
  return workbook;
}

function consolidatedFormulaColumns(rows, startRow) {
  const output = Array.from({ length: 12 }, () => []);
  const keyedRows = new Map(rows.map((row, offset) => [
    `${row.ccc_code}|${row.month}`, startRow + offset,
  ]));
  rows.forEach((row, offset) => {
    const r = startRow + offset;
    const mom = keyedRows.get(`${row.ccc_code}|${shiftMonth(row.month, -1)}`);
    const yoy = keyedRows.get(`${row.ccc_code}|${shiftMonth(row.month, -12)}`);
    output[0].push([`=J${r}/1000000`]);
    output[1].push([`=IF(OR(H${r}="",H${r}=0,J${r}=""),"",J${r}/H${r})`]);
    output[2].push([`=IF(OR(I${r}="",I${r}=0,J${r}=""),"",J${r}/I${r})`]);
    output[3].push([row.quantity_mom !== null && mom ? `=IFERROR(H${r}/H${mom}-1,"")` : ""]);
    output[4].push([row.weight_mom !== null && mom ? `=IFERROR(I${r}/I${mom}-1,"")` : ""]);
    output[5].push([row.value_mom !== null && mom ? `=IFERROR(J${r}/J${mom}-1,"")` : ""]);
    output[6].push([row.unit_value_mom !== null && mom ? `=IFERROR(L${r}/L${mom}-1,"")` : ""]);
    output[7].push([row.kg_value_mom !== null && mom ? `=IFERROR(M${r}/M${mom}-1,"")` : ""]);
    output[8].push([row.quantity_yoy !== null && yoy ? `=IFERROR(H${r}/H${yoy}-1,"")` : ""]);
    output[9].push([row.weight_yoy !== null && yoy ? `=IFERROR(I${r}/I${yoy}-1,"")` : ""]);
    output[10].push([row.value_yoy !== null && yoy ? `=IFERROR(J${r}/J${yoy}-1,"")` : ""]);
    output[11].push([row.unit_value_yoy !== null && yoy ? `=IFERROR(L${r}/L${yoy}-1,"")` : ""]);
  });
  return output;
}

async function createConsolidatedWorkbook(groups, flow, sourceUrl) {
  const workbook = Workbook.create();
  const index = workbook.worksheets.add("Index");
  const all = workbook.worksheets.add("All CCC Monthly");
  const notes = workbook.worksheets.add("Data Notes");
  index.showGridLines = false;
  all.showGridLines = false;
  notes.showGridLines = false;
  const flat = [...groups.values()].flat();
  applyTitle(all, "V", `Taiwan ${flow[0].toUpperCase() + flow.slice(1)} Trade | All CCC Codes`, sourceSubtitle(flow, sourceUrl));
  all.getRange("A4:V4").values = [[
    "CCC Code", "Date", "HS6", "HS8", "Chinese Description", "English Description",
    "Quantity Unit", "Quantity", "Weight (kg)", "Value (USD)", "Value (mn USD)",
    "Unit Value", "USD/kg", "Quantity (MoM)", "Weight (MoM)", "Value (MoM)",
    "Unit Value (MoM)", "USD/kg (MoM)", "Quantity (YoY)", "Weight (YoY)",
    "Value (YoY)", "Unit Value (YoY)",
  ]];
  styleHeader(all.getRange("A4:V4"));
  const end = flat.length + 4;
  all.getRange(`A5:J${end}`).values = flat.map((row) => [
    row.ccc_code, excelDate(row.month), row.hs6, row.hs8, row.commodity_name_zh,
    row.commodity_name_en, row.quantity_unit, row.quantity, row.weight_kg, row.value_usd,
  ]);
  const formulaColumns = consolidatedFormulaColumns(flat, 5);
  "KLMNOPQRSTUV".split("").forEach((column, columnIndex) => {
    all.getRange(`${column}5:${column}${end}`).formulas = formulaColumns[columnIndex];
  });
  styleData(all, 5, end, "V");
  all.getRange(`A5:A${end}`).format.numberFormat = "@";
  all.getRange(`B5:B${end}`).format.numberFormat = "yyyy-mm";
  all.getRange(`C5:D${end}`).format.numberFormat = "@";
  all.getRange(`H5:J${end}`).format.numberFormat = "#,##0.00";
  all.getRange(`K5:M${end}`).format.numberFormat = "#,##0.0000";
  all.getRange(`N5:V${end}`).format.numberFormat = "0.00%";
  all.getRange(`A1:D${end}`).format.columnWidth = 13;
  all.getRange(`E1:F${end}`).format.columnWidth = 45;
  all.getRange(`G1:V${end}`).format.columnWidth = 16;
  all.getRange(`E5:F${end}`).format.wrapText = true;
  all.freezePanes.freezeRows(4);
  all.freezePanes.freezeColumns(2);

  const indexRows = [...groups.entries()];
  applyTitle(index, "M", `Taiwan ${flow[0].toUpperCase() + flow.slice(1)} | CCC Index`, `${groups.size.toLocaleString()} current Chapter 84/85 CCC codes`);
  index.getRange("A4:M4").values = [[
    "CCC Code", "HS6", "HS8", "Chinese Description", "English Description", "Unit",
    "Months", "Latest Month", "Latest Quantity", "Latest Weight (kg)", "Latest Value (USD)",
    "Latest Unit Value", "Per-CCC Workbook",
  ]];
  styleHeader(index.getRange("A4:M4"));
  const indexEnd = indexRows.length + 4;
  index.getRange(`A5:M${indexEnd}`).values = indexRows.map(([code, rows]) => {
    const latest = rows.at(-1);
    return [
      code, latest.hs6, latest.hs8, latest.commodity_name_zh, latest.commodity_name_en,
      latest.quantity_unit, rows.length, excelDate(latest.month), latest.quantity,
      latest.weight_kg, latest.value_usd, latest.unit_value_usd,
      `by_ccc_code/${code}.xlsx`,
    ];
  });
  styleData(index, 5, indexEnd, "M");
  index.getRange(`A5:C${indexEnd}`).format.numberFormat = "@";
  index.getRange(`H5:H${indexEnd}`).format.numberFormat = "yyyy-mm";
  index.getRange(`I5:L${indexEnd}`).format.numberFormat = "#,##0.0000";
  index.getRange(`A1:C${indexEnd}`).format.columnWidth = 13;
  index.getRange(`D1:E${indexEnd}`).format.columnWidth = 45;
  index.getRange(`F1:M${indexEnd}`).format.columnWidth = 17;
  index.getRange(`M1:M${indexEnd}`).format.columnWidth = 30;
  index.getRange(`D5:E${indexEnd}`).format.wrapText = true;
  index.freezePanes.freezeRows(4);

  applyTitle(notes, "B", "Data Definitions and Validation Notes", "Read before using unit values as market prices");
  const noteRows = [
    ["Topic", "Definition / caution"],
    ["CCC Code", "11 digits: HS6 + Taiwan tariff/statistical extension + check digit."],
    ["Scope", "Current Chapter 84 and 85 codes from the official tariff dataset."],
    ["Import value", "USD on a CIF basis; includes re-imports in the default All scope."],
    ["Export value", "USD on an FOB basis; includes re-exports in the default All scope."],
    ["Quantity", "Official declared statistical quantity. Blank means the tariff code has no quantity unit."],
    ["Weight", "Official net/statistical weight in kilograms."],
    ["Unit Value", "Value divided by declared quantity. It is an average customs unit value, not a quoted market price."],
    ["USD/kg", "Value divided by weight. Useful when the declared quantity unit is unavailable or not comparable."],
    ["Zero rows", "A current CCC code omitted from a complete <=20-code batch is recorded as zero only when no protected row is present."],
    ["Protected data", "If the source returns an unlabeled protected row, omitted codes in that batch remain unresolved rather than being forced to zero."],
    ["Revisions", "Recent months may be preliminary and can change. The workflow refreshes recent months on every scheduled run."],
    ["Source", sourceUrl],
  ];
  notes.getRange(`A4:B${noteRows.length + 3}`).values = noteRows;
  styleHeader(notes.getRange("A4:B4"));
  styleData(notes, 5, noteRows.length + 3, "B");
  notes.getRange(`A1:A${noteRows.length + 3}`).format.columnWidth = 24;
  notes.getRange(`B1:B${noteRows.length + 3}`).format.columnWidth = 110;
  notes.getRange(`B5:B${noteRows.length + 3}`).format.wrapText = true;
  return workbook;
}

async function saveWorkbook(workbook, destination) {
  await fs.mkdir(path.dirname(destination), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(destination);
  await fs.rm(`${destination}.inspect.ndjson`, { force: true });
}

async function runPool(items, concurrency, worker) {
  let cursor = 0;
  const runners = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      await worker(items[index], index);
    }
  });
  await Promise.all(runners);
}

async function main() {
  const args = parseArgs(process.argv);
  const payload = JSON.parse(await fs.readFile(args.metrics, "utf8"));
  const groups = groupRows(payload.rows);
  const outputDir = path.resolve(args["output-dir"]);
  if (args.scope === "all" || args.scope === "consolidated") {
    const consolidated = await createConsolidatedWorkbook(groups, args.flow, payload.source_url);
    await saveWorkbook(consolidated, path.join(outputDir, `all_ccc_${args.flow}.xlsx`));
  }
  if (args.scope === "all" || args.scope === "per-ccc") {
    let entries = [...groups.entries()];
    if (args.limitCcc !== null) entries = entries.slice(0, args.limitCcc);
    let completed = 0;
    await runPool(entries, args.concurrency, async ([code, rows]) => {
      const workbook = await createPerCccWorkbook(code, rows, args.flow, payload.source_url);
      await saveWorkbook(workbook, path.join(outputDir, "by_ccc_code", `${code}.xlsx`));
      completed += 1;
      if (completed % 100 === 0 || completed === entries.length) {
        console.log(`[${args.flow}] per-CCC workbooks: ${completed}/${entries.length}`);
      }
    });
  }
  console.log(JSON.stringify({ flow: args.flow, ccc_count: groups.size, output_dir: outputDir }));
}

await main();

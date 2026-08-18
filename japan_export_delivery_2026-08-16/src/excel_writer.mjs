/** Generate the consolidated and attachment-style per-HS workbooks. */

import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const SOURCE_URL = "https://www.customs.go.jp/JCWSV04/servlet/JCWSV04";
const COLORS = {
  navy: "#24577F",
  lightBlue: "#D9E8F5",
  header: "#D5DFF1",
  stripe: "#F3F7FA",
  border: "#B7C9D6",
  text: "#263238",
  input: "#EAF2F8",
};

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unexpected argument: ${key}`);
    args[key.slice(2)] = argv[i + 1];
  }
  if (!args.metrics || !args["output-dir"]) {
    throw new Error("Usage: excel_writer.mjs --metrics input.json --output-dir dir [--scope all]");
  }
  args.scope ??= "all";
  if (!new Set(["all", "consolidated", "per-hs"]).has(args.scope)) {
    throw new Error(`Invalid --scope: ${args.scope}`);
  }
  args.limitHs = args["limit-hs"] ? Number(args["limit-hs"]) : null;
  args.hsCode = args["hs-code"] ?? null;
  args.concurrency = args.concurrency ? Number(args.concurrency) : 4;
  if (!Number.isInteger(args.concurrency) || args.concurrency < 1 || args.concurrency > 16) {
    throw new Error("--concurrency must be an integer from 1 to 16");
  }
  args.previewDir = args["preview-dir"] ?? null;
  return args;
}

function excelDate(month) {
  const [year, monthNumber] = month.split("-").map(Number);
  return new Date(Date.UTC(year, monthNumber - 1, 1));
}

function groupRows(rows) {
  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.hs_code)) groups.set(row.hs_code, []);
    groups.get(row.hs_code).push(row);
  }
  for (const group of groups.values()) group.sort((a, b) => a.month.localeCompare(b.month));
  return new Map([...groups.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

function applyTitle(sheet, endColumn, title, subtitle) {
  sheet.mergeCells(`A1:${endColumn}1`);
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${endColumn}1`).format = {
    fill: COLORS.navy,
    font: { bold: true, color: "#FFFFFF", size: 15 },
    verticalAlignment: "center",
  };
  sheet.getRange("A1").format.rowHeight = 30;
  sheet.mergeCells(`A2:${endColumn}2`);
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endColumn}2`).format = {
    fill: COLORS.lightBlue,
    font: { color: COLORS.text, size: 10 },
    verticalAlignment: "center",
  };
  sheet.getRange("A2").format.rowHeight = 24;
}

function styleHeader(range) {
  range.format = {
    fill: COLORS.header,
    font: { bold: true, color: COLORS.text },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: COLORS.border },
  };
  range.format.rowHeight = 34;
}

function styleData(sheet, rangeAddress, rowCount, lastColumn) {
  const range = sheet.getRange(rangeAddress);
  range.format = {
    font: { color: COLORS.text, size: 10 },
    borders: { insideHorizontal: { style: "thin", color: COLORS.border } },
    verticalAlignment: "center",
  };
  for (let offset = 0; offset < rowCount; offset += 2) {
    sheet.getRange(`A${5 + offset}:${lastColumn}${5 + offset}`).format.fill = COLORS.stripe;
  }
}

function perHsFormulaColumns(rows, startRow = 5) {
  const result = Array.from({ length: 12 }, () => []);
  rows.forEach((row, index) => {
    const excelRow = startRow + index;
    result[0].push(["=RC[-1]/1000"]); // D Value mn
    result[1].push(["=IF(OR(RC[-3]=0,RC[-3]=\"\"),\"\",RC[-2]/RC[-3])"]); // E ASP
    result[2].push([index >= 2 ? "=IF(COUNT(R[-2]C[-1]:RC[-1])=3,AVERAGE(R[-2]C[-1]:RC[-1]),\"\")" : ""]);
    result[3].push([index >= 1 ? "=IFERROR(RC[-2]/R[-1]C[-2]-1,\"\")" : ""]);
    result[4].push([index >= 1 ? "=IFERROR(RC[-6]/R[-1]C[-6]-1,\"\")" : ""]);
    result[5].push([index >= 1 ? "=IFERROR(RC[-6]/R[-1]C[-6]-1,\"\")" : ""]);
    result[6].push([index >= 12 ? "=IFERROR(RC[-5]/R[-12]C[-5]-1,\"\")" : ""]);
    result[7].push([index >= 12 ? "=IFERROR(RC[-9]/R[-12]C[-9]-1,\"\")" : ""]);
    result[8].push([index >= 12 ? "=IFERROR(RC[-9]/R[-12]C[-9]-1,\"\")" : ""]);
    result[9].push([row.value_quarter_thousand_yen !== null ? "=SUM(R[-2]C[-10]:RC[-10])" : ""]);
    result[10].push([row.quarter_value_qoq !== null ? "=IFERROR(RC[-1]/R[-3]C[-1]-1,\"\")" : ""]);
    result[11].push([row.quarter_value_yoy !== null ? "=IFERROR(RC[-2]/R[-12]C[-2]-1,\"\")" : ""]);
  });
  return result;
}

async function createPerHsWorkbook(code, rows, sourceUrl, metadata = {}) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Monthly Data");
  sheet.showGridLines = false;
  const unit2s = [...new Set(rows.map((row) => row.unit2).filter(Boolean))];
  const unit2 = unit2s.length === 1 ? unit2s[0] : "MULTIPLE";
  applyTitle(
    sheet,
    "O",
    `Japan Export Trade Data | HS ${code}`,
    `FOB value: thousand JPY | Primary volume: Unit2 (${unit2}) | ASP: thousand JPY/${unit2}`,
  );
  const headers = [[
    "Date", `Volume (${unit2})`, "Value (thsd)", "Value (mn)", "ASP", "ASP (3MMA)",
    "ASP (MoM)", "Volume (MoM)", "Value (MoM)", "ASP (YoY)", "Volume (YoY)",
    "Value (YoY)", "Value (Q)", "Q Value (QoQ)", "Q Value (YoY)",
  ]];
  sheet.getRange("A4:O4").values = headers;
  styleHeader(sheet.getRange("A4:O4"));
  const startRow = 5;
  const endRow = startRow + rows.length - 1;
  sheet.getRange(`A${startRow}:C${endRow}`).values = rows.map((row) => [
    excelDate(row.month), row.volume, row.value_thousand_yen,
  ]);
  const formulas = perHsFormulaColumns(rows, startRow);
  "DEFGHIJKLMNO".split("").forEach((column, index) => {
    sheet.getRange(`${column}${startRow}:${column}${endRow}`).formulasR1C1 = formulas[index];
  });
  styleData(sheet, `A${startRow}:O${endRow}`, rows.length, "O");
  sheet.getRange(`A${startRow}:A${endRow}`).format.numberFormat = "yyyy-mm";
  sheet.getRange(`B${startRow}:C${endRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`D${startRow}:D${endRow}`).format.numberFormat = "#,##0.000";
  sheet.getRange(`E${startRow}:F${endRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`G${startRow}:L${endRow}`).format.numberFormat = "0%";
  sheet.getRange(`M${startRow}:M${endRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`N${startRow}:O${endRow}`).format.numberFormat = "0%";
  sheet.getRange(`A${startRow}:O${endRow}`).format.rowHeight = 22;
  sheet.getRange(`A1:A${endRow}`).format.columnWidth = 12;
  sheet.getRange(`B1:O${endRow}`).format.columnWidth = 15;
  sheet.freezePanes.freezeRows(4);

  const raw = workbook.worksheets.add("Raw Data");
  raw.showGridLines = false;
  applyTitle(raw, "I", `Raw Source Data | HS ${code}`, `Source: ${sourceUrl}`);
  raw.getRange("A4:I4").values = [[
    "Date", "Unit1", "Quantity1", "Unit2", "Quantity2", "Value (thsd JPY)",
    "Status", "Fetched at UTC", "Source URL",
  ]];
  styleHeader(raw.getRange("A4:I4"));
  raw.getRange(`A5:I${endRow}`).values = rows.map((row) => [
    excelDate(row.month), row.unit1, row.quantity1, row.unit2, row.volume,
    row.value_thousand_yen, row.record_status, row.fetched_at_utc, sourceUrl,
  ]);
  styleData(raw, `A5:I${endRow}`, rows.length, "I");
  raw.getRange(`A5:A${endRow}`).format.numberFormat = "yyyy-mm";
  raw.getRange(`C5:F${endRow}`).format.numberFormat = "#,##0";
  raw.getRange(`H5:H${endRow}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
  raw.getRange(`A1:A${endRow}`).format.columnWidth = 12;
  raw.getRange(`B1:F${endRow}`).format.columnWidth = 16;
  raw.getRange(`G1:G${endRow}`).format.columnWidth = 20;
  raw.getRange(`H1:H${endRow}`).format.columnWidth = 28;
  raw.getRange(`I1:I${endRow}`).format.columnWidth = 54;
  raw.freezePanes.freezeRows(4);

  const mapping = workbook.worksheets.add("HS Mapping");
  mapping.showGridLines = false;
  applyTitle(mapping, "B", `HS Mapping | ${code}`, "Business definition and official export-code audit trail");
  mapping.getRange("A4:B10").values = [
    ["Field", "Value"],
    ["Official Export HS Code", code],
    ["Source Code(s)", metadata.source_codes || code],
    ["Product Types", metadata.product_types || ""],
    ["Companies", metadata.companies || ""],
    ["Mapping Action", metadata.mapping_action || "direct"],
    ["Mapping Note", metadata.mapping_note || ""],
  ];
  styleHeader(mapping.getRange("A4:B4"));
  styleData(mapping, "A5:B10", 6, "B");
  mapping.getRange("A1:A10").format.columnWidth = 23;
  mapping.getRange("B1:B10").format.columnWidth = 95;
  mapping.getRange("B5:B10").format.wrapText = true;
  mapping.getRange("A5:B10").format.rowHeight = 42;
  return workbook;
}

async function createConsolidatedWorkbook(groups, sourceUrl, metadataByHs = {}) {
  const workbook = Workbook.create();
  const index = workbook.worksheets.add("Index");
  const all = workbook.worksheets.add("All HS Monthly");
  index.showGridLines = false;
  all.showGridLines = false;

  const flat = [];
  const rowAddress = new Map();
  for (const [code, rows] of groups) {
    for (const row of rows) {
      flat.push(row);
      rowAddress.set(`${code}|${row.month}`, flat.length + 4);
    }
  }
  applyTitle(
    all, "T", "Japan Export Trade Data | All HS Codes",
    `Source: ${sourceUrl} | FOB value | Primary volume: Unit2 | ASP: thousand JPY per Unit2`,
  );
  all.getRange("A4:T4").values = [[
    "HS Code", "Date", "Unit1", "Quantity1", "Unit2", "Volume", "Value (thsd)",
    "Value (mn)", "ASP", "ASP (3MMA)", "ASP (MoM)", "Volume (MoM)", "Value (MoM)",
    "ASP (YoY)", "Volume (YoY)", "Value (YoY)", "Value (Q)", "Q Value (QoQ)",
    "Q Value (YoY)", "Status",
  ]];
  styleHeader(all.getRange("A4:T4"));
  const endRow = flat.length + 4;
  all.getRange(`A5:G${endRow}`).values = flat.map((row) => [
    row.hs_code, excelDate(row.month), row.unit1, row.quantity1, row.unit2,
    row.volume, row.value_thousand_yen,
  ]);
  all.getRange(`T5:T${endRow}`).values = flat.map((row) => [row.record_status]);
  const formulaColumns = Array.from({ length: 12 }, () => []);
  flat.forEach((row, index) => {
    formulaColumns[0].push(["=RC[-1]/1000"]);
    formulaColumns[1].push(["=IF(OR(RC[-3]=0,RC[-3]=\"\"),\"\",RC[-2]/RC[-3])"]);
    formulaColumns[2].push([index >= 2 ? "=IF(AND(RC[-9]=R[-2]C[-9],COUNT(R[-2]C[-1]:RC[-1])=3),AVERAGE(R[-2]C[-1]:RC[-1]),\"\")" : ""]);
    formulaColumns[3].push([index >= 1 ? "=IF(RC[-10]=R[-1]C[-10],IFERROR(RC[-2]/R[-1]C[-2]-1,\"\"),\"\")" : ""]);
    formulaColumns[4].push([index >= 1 ? "=IF(RC[-11]=R[-1]C[-11],IFERROR(RC[-6]/R[-1]C[-6]-1,\"\"),\"\")" : ""]);
    formulaColumns[5].push([index >= 1 ? "=IF(RC[-12]=R[-1]C[-12],IFERROR(RC[-6]/R[-1]C[-6]-1,\"\"),\"\")" : ""]);
    formulaColumns[6].push([index >= 12 ? "=IF(RC[-13]=R[-12]C[-13],IFERROR(RC[-5]/R[-12]C[-5]-1,\"\"),\"\")" : ""]);
    formulaColumns[7].push([index >= 12 ? "=IF(RC[-14]=R[-12]C[-14],IFERROR(RC[-9]/R[-12]C[-9]-1,\"\"),\"\")" : ""]);
    formulaColumns[8].push([index >= 12 ? "=IF(RC[-15]=R[-12]C[-15],IFERROR(RC[-9]/R[-12]C[-9]-1,\"\"),\"\")" : ""]);
    formulaColumns[9].push([row.value_quarter_thousand_yen !== null ? "=SUM(R[-2]C[-10]:RC[-10])" : ""]);
    formulaColumns[10].push([row.quarter_value_qoq !== null ? "=IFERROR(RC[-1]/R[-3]C[-1]-1,\"\")" : ""]);
    formulaColumns[11].push([row.quarter_value_yoy !== null ? "=IFERROR(RC[-2]/R[-12]C[-2]-1,\"\")" : ""]);
  });
  "HIJKLMNOPQRS".split("").forEach((column, indexColumn) => {
    all.getRange(`${column}5:${column}${endRow}`).formulasR1C1 = formulaColumns[indexColumn];
  });
  styleData(all, `A5:T${endRow}`, flat.length, "T");
  all.getRange(`A5:A${endRow}`).format.numberFormat = "@";
  all.getRange(`B5:B${endRow}`).format.numberFormat = "yyyy-mm";
  all.getRange(`D5:D${endRow}`).format.numberFormat = "#,##0";
  all.getRange(`F5:G${endRow}`).format.numberFormat = "#,##0";
  all.getRange(`H5:J${endRow}`).format.numberFormat = "#,##0.00";
  all.getRange(`K5:P${endRow}`).format.numberFormat = "0%";
  all.getRange(`Q5:Q${endRow}`).format.numberFormat = "#,##0";
  all.getRange(`R5:S${endRow}`).format.numberFormat = "0%";
  all.getRange(`A1:A${endRow}`).format.columnWidth = 13;
  all.getRange(`B1:B${endRow}`).format.columnWidth = 12;
  all.getRange(`C1:T${endRow}`).format.columnWidth = 15;
  all.freezePanes.freezeRows(4);
  all.freezePanes.freezeColumns(2);

  applyTitle(
    index, "K", "Japan Export Trade Data | HS Code Index",
    `${groups.size.toLocaleString()} HS codes | Click/filter by HS code using the consolidated data sheet`,
  );
  index.getRange("A4:K4").values = [[
    "HS Code", "Months", "Latest Month", "Unit1", "Unit2", "Latest Volume",
    "Latest Value (thsd)", "Latest ASP", "Product Types", "Source Code(s)",
    "Per-HS Workbook",
  ]];
  styleHeader(index.getRange("A4:K4"));
  const indexRows = [...groups.entries()];
  const indexEnd = indexRows.length + 4;
  index.getRange(`A5:E${indexEnd}`).values = indexRows.map(([code, rows]) => {
    const latest = rows.at(-1);
    return [code, rows.length, excelDate(latest.month), latest.unit1, latest.unit2];
  });
  index.getRange(`I5:K${indexEnd}`).values = indexRows.map(([code]) => [
    metadataByHs[code]?.product_types || "",
    metadataByHs[code]?.source_codes || code,
    `by_hs_code/${code}.xlsx`,
  ]);
  indexRows.forEach(([code, rows], offset) => {
    const latest = rows.at(-1);
    const sourceRow = rowAddress.get(`${code}|${latest.month}`);
    const targetRow = offset + 5;
    index.getRange(`F${targetRow}:G${targetRow}`).formulas = [[
      `='All HS Monthly'!F${sourceRow}`,
      `='All HS Monthly'!G${sourceRow}`,
    ]];
    if (latest.asp_thousand_yen_per_unit2 !== null) {
      index.getRange(`H${targetRow}`).formulas = [[`='All HS Monthly'!I${sourceRow}`]];
    }
  });
  styleData(index, `A5:K${indexEnd}`, indexRows.length, "K");
  index.getRange(`A5:A${indexEnd}`).format.numberFormat = "@";
  index.getRange(`C5:C${indexEnd}`).format.numberFormat = "yyyy-mm";
  index.getRange(`F5:G${indexEnd}`).format.numberFormat = "#,##0";
  index.getRange(`H5:H${indexEnd}`).format.numberFormat = "#,##0.00";
  index.getRange(`A1:A${indexEnd}`).format.columnWidth = 13;
  index.getRange(`B1:H${indexEnd}`).format.columnWidth = 16;
  index.getRange(`I1:I${indexEnd}`).format.columnWidth = 48;
  index.getRange(`J1:J${indexEnd}`).format.columnWidth = 24;
  index.getRange(`K1:K${indexEnd}`).format.columnWidth = 28;
  index.getRange(`I5:J${indexEnd}`).format.wrapText = true;
  index.freezePanes.freezeRows(4);
  return workbook;
}

async function saveWorkbook(workbook, destination) {
  await fs.mkdir(path.dirname(destination), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(destination);
  // The spreadsheet runtime may emit a diagnostic sidecar beside the XLSX.
  // It is useful during authoring but is not part of the monthly deliverable.
  await fs.rm(`${destination}.inspect.ndjson`, { force: true });
}

async function verifyAndPreview(workbook, sheetName, range, previewPath) {
  const inspection = await workbook.inspect({
    kind: "table", range: `${sheetName}!${range}`, include: "values,formulas",
    tableMaxRows: 18, tableMaxCols: 20, maxChars: 8000,
  });
  const errors = await workbook.inspect({
    kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 50 }, summary: "formula error scan",
  });
  if (errors.ndjson.includes('"kind":"match"')) {
    throw new Error(`Formula error detected: ${errors.ndjson}`);
  }
  if (previewPath) {
    const image = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
    await fs.mkdir(path.dirname(previewPath), { recursive: true });
    await fs.writeFile(previewPath, new Uint8Array(await image.arrayBuffer()));
  }
  return inspection.ndjson;
}

async function main() {
  const args = parseArgs(process.argv);
  const payload = JSON.parse(await fs.readFile(args.metrics, "utf8"));
  const sourceUrl = payload.source_url || SOURCE_URL;
  const metadataByHs = payload.hs_metadata || {};
  let groups = groupRows(payload.rows ?? []);
  if (args.hsCode !== null) {
    if (!groups.has(args.hsCode)) throw new Error(`HS code not found in metrics: ${args.hsCode}`);
    groups = new Map([[args.hsCode, groups.get(args.hsCode)]]);
  }
  if (args.limitHs !== null) groups = new Map([...groups.entries()].slice(0, args.limitHs));
  if (groups.size === 0) throw new Error("Metrics JSON contains no HS rows.");
  const outputDir = path.resolve(args["output-dir"]);
  await fs.mkdir(outputDir, { recursive: true });

  if (args.scope === "all" || args.scope === "consolidated") {
    console.log(`Building consolidated workbook for ${groups.size} HS codes ...`);
    const workbook = await createConsolidatedWorkbook(groups, sourceUrl, metadataByHs);
    const preview = args.previewDir ? path.join(args.previewDir, "all_hs_index.png") : null;
    console.log(await verifyAndPreview(workbook, "Index", `A1:K${Math.min(groups.size + 4, 24)}`, preview));
    if (args.previewDir) {
      const image = await workbook.render({
        sheetName: "All HS Monthly", range: "A1:T20", scale: 1.1, format: "png",
      });
      await fs.mkdir(args.previewDir, { recursive: true });
      await fs.writeFile(
        path.join(args.previewDir, "all_hs_monthly.png"),
        new Uint8Array(await image.arrayBuffer()),
      );
    }
    await saveWorkbook(workbook, path.join(outputDir, "all_hs_export.xlsx"));
  }

  if (args.scope === "all" || args.scope === "per-hs") {
    const perHsDir = path.join(outputDir, "by_hs_code");
    await fs.mkdir(perHsDir, { recursive: true });
    const entries = [...groups.entries()];
    let completed = 0;
    const [firstCode, firstRows] = entries.shift();
    const firstWorkbook = await createPerHsWorkbook(firstCode, firstRows, sourceUrl, metadataByHs[firstCode]);
    const preview = args.previewDir ? path.join(args.previewDir, `${firstCode}.png`) : null;
    await verifyAndPreview(firstWorkbook, "Monthly Data", `A1:O${firstRows.length + 4}`, preview);
    if (args.previewDir) {
      const rawPreview = await firstWorkbook.render({
        sheetName: "Raw Data", range: `A1:I${firstRows.length + 4}`, scale: 1.1, format: "png",
      });
      await fs.writeFile(
        path.join(args.previewDir, `${firstCode}_raw.png`),
        new Uint8Array(await rawPreview.arrayBuffer()),
      );
      const mappingPreview = await firstWorkbook.render({
        sheetName: "HS Mapping", range: "A1:B10", scale: 1.1, format: "png",
      });
      await fs.writeFile(
        path.join(args.previewDir, `${firstCode}_mapping.png`),
        new Uint8Array(await mappingPreview.arrayBuffer()),
      );
    }
    await saveWorkbook(firstWorkbook, path.join(perHsDir, `${firstCode}.xlsx`));
    completed = 1;
    let cursor = 0;
    async function worker() {
      while (cursor < entries.length) {
        const current = cursor;
        cursor += 1;
        const [code, rows] = entries[current];
        const workbook = await createPerHsWorkbook(code, rows, sourceUrl, metadataByHs[code]);
        await saveWorkbook(workbook, path.join(perHsDir, `${code}.xlsx`));
        completed += 1;
        if (completed % 50 === 0 || completed === groups.size) {
          console.log(`Built ${completed}/${groups.size} per-HS workbooks.`);
        }
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(args.concurrency, entries.length) }, () => worker()),
    );
  }
}

await main();

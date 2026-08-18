import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = process.argv[2];
const output = process.argv[3];
if (!input || !output) throw new Error("Usage: inspect_workbook.mjs input.xlsx preview.png");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 4000 });
console.log(sheets.ndjson);
const first = workbook.worksheets.getItemAt(0);
const summary = await workbook.inspect({
  kind: "table", sheetId: first.name, range: "A1:O24", include: "values,formulas",
  tableMaxRows: 24, tableMaxCols: 15, maxChars: 8000,
});
console.log(summary.ndjson);
const preview = await workbook.render({ sheetName: first.name, range: "A1:O24", scale: 1.2, format: "png" });
await fs.mkdir(new URL(".", `file:///${output.replaceAll("\\", "/")}`).pathname, { recursive: true }).catch(() => {});
await fs.writeFile(output, new Uint8Array(await preview.arrayBuffer()));

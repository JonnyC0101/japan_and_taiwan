/** Inspect and render a generated consolidated workbook for visual and formula QA. */

import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = process.argv[2];
const previewDir = process.argv[3];
if (!workbookPath || !previewDir) {
  throw new Error("Usage: inspect_total_workbook.mjs all_ccc_<flow>.xlsx preview_dir");
}
const input = await fs.readFile(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const inspection = await workbook.inspect({
  kind: "table", range: "Index!A1:M18", include: "values,formulas",
  tableMaxRows: 18, tableMaxCols: 13, maxChars: 12000,
});
const errors = await workbook.inspect({
  kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan",
});
const detail = await workbook.inspect({
  kind: "table", range: "All CCC Monthly!A20:V36", include: "values,formulas",
  tableMaxRows: 17, tableMaxCols: 22, maxChars: 16000,
});
await fs.mkdir(previewDir, { recursive: true });
const image = await workbook.render({ sheetName: "Index", range: "A1:M18", scale: 1.4, format: "png" });
await fs.writeFile(
  path.join(previewDir, "index_preview.png"),
  new Uint8Array(await image.arrayBuffer()),
);
console.log(JSON.stringify({
  inspection: inspection.ndjson, detail: detail.ndjson, errors: errors.ndjson,
}, null, 2));

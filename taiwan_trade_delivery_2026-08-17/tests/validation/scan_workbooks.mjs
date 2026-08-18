/** Re-import generated workbooks and fail on common spreadsheet formula errors. */

import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile } from "@oai/artifact-tool";

const workbooks = process.argv.slice(2);
if (workbooks.length === 0) {
  throw new Error("Usage: scan_workbooks.mjs workbook1.xlsx [workbook2.xlsx ...]");
}

for (const workbookPath of workbooks) {
  const workbook = await SpreadsheetFile.importXlsx(await fs.readFile(workbookPath));
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "delivery formula error scan",
  });
  if (!errors.ndjson.includes("matched 0 entries")) {
    throw new Error(`${path.basename(workbookPath)} formula scan failed: ${errors.ndjson}`);
  }
  const sheetNames = workbook.worksheets.items.map((sheet) => sheet.name);
  console.log(JSON.stringify({ workbook: workbookPath, sheetNames, formulaErrors: 0 }));
}


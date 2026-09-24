const XLSX = require("xlsx");
const fs = require("fs");

const filePath = "C:/Users/Prasanna/Desktop/IB/backend/app/Book1.xlsx";

const workbook = XLSX.readFile(filePath);
const sheet = workbook.Sheets["Sheet1"];

// Read the first row as an array of cells
const range = XLSX.utils.decode_range(sheet["!ref"]);

const headers = [];

for (let col = range.s.c; col <= range.e.c; col++) {
    const cellAddress = XLSX.utils.encode_cell({
        r: 0,
        c: col,
    });

    const cell = sheet[cellAddress];

    headers.push(cell ? String(cell.v).trim() : "");
}

console.log("Total columns:", headers.length);

// Generate TypeScript
const output = `export const templateHeaders = [
${headers.map((header) => `  ${JSON.stringify(header)},`).join("\n")}
] as const;
`;

fs.writeFileSync("templateHeaders.ts", output, "utf8");

console.log("Created templateHeaders.ts");
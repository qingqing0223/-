// Reusable V3 workbook writer. Public text is always stored as literal values.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

let moduleName = process.env.WECHAT_MP_ARTIFACT_MODULE || '@oai/artifact-tool';
if (process.env.WECHAT_MP_ARTIFACT_PACKAGE) {
  const require = createRequire(path.join(process.env.WECHAT_MP_ARTIFACT_PACKAGE, 'package.json'));
  moduleName = pathToFileURL(require.resolve('@oai/artifact-tool')).href;
}
const { Workbook, SpreadsheetFile } = await import(moduleName);
const [input, output] = process.argv.slice(2);
const data = JSON.parse(await fs.readFile(input, 'utf8'));
const book = Workbook.create();
const intro = book.worksheets.add('说明与统计');
intro.showGridLines = false;
const coverage = Object.values(data.collector.keyword_coverage || {});
const notes = [
  ['微信公众号 TechDesign V3', null],
  ['正式监测开始', data.monitoring_start_time],
  ['有效文章数', data.valid_articles], ['已采集帐号数', data.table_counts[4]],
  ['表1、表2输出时间', data.content_export_at], ['表3—表5输出时间', data.metrics_export_at],
  ['采集状态', data.collector.status],
  ['本批次结束时间', data.monitoring_end_time ? `${data.monitoring_end_time}（含边界）` : '未限定'],
  ['总候选数', data.total_candidates], ['明确无效文章数', data.invalid_articles], ['待人工核验文章数', data.pending_review_articles],
  ['搜索完成度', `${coverage.filter(x=>['SUCCESS','NO_RESULTS'].includes(x)).length}/${coverage.length} 个关键词到达自然终点。逐词状态、页数、命中量和去重新增量见 summary.json。`],
  ['公开数据边界', data.limitations],
  ['正文与过滤', data.content_note], ['文章标识', data.identity_note],
  ['公开文章链接限制', data.canonical_url_limitation],
  ['POMS文件格式', data.poms_json_note],
  ['帐号统计口径', data.account_metrics_note], ['CSV导入', data.csv_note],
  ['时间与空值', '所有时间为北京时间(+08:00)。未知单元格为空；数值0仅代表可靠取得的真实零值。'],
  ['评论表说明', '表2、表4仅保留结构，当前公开来源未取得评论。'],
];
intro.getRangeByIndexes(0, 0, notes.length, 2).values = notes;
intro.getRange(`A1:B${notes.length}`).format.font = {name: 'Arial', size: 11};
intro.getRange(`A1:B${notes.length}`).format.wrapText = true;
intro.getRange(`A1:B${notes.length}`).format.rowHeight = 44;
intro.getRange(`A1:A${notes.length}`).format.columnWidth = 28;
intro.getRange(`B1:B${notes.length}`).format.columnWidth = 110;
intro.getRange('A1:B1').format.font = {name: 'Arial', size: 15, bold: true};
intro.getRange(`A1:B${notes.length}`).format.autofitRows();
for (const [cell, value] of [['B2', data.monitoring_start_time], ['B5', data.content_export_at], ['B6', data.metrics_export_at]]) {
  intro.getRange(cell).values = [[value ? Date.parse(value) / 86400000 + 25569 + 8 / 24 : null]];
  intro.getRange(cell).setNumberFormat('yyyy-mm-dd hh:mm:ss');
}

const literal = value => typeof value === 'string' && value.startsWith('=') ? "'" + value : value;
for (let i = 0; i < data.sheets.length; i++) {
  const sheet = book.worksheets.add(data.sheets[i]);
  const headers = data.fields[i];
  const values = [headers, ...data.tables[i].map(row => row.map(literal))];
  sheet.showGridLines = false;
  const range = sheet.getRangeByIndexes(0, 0, values.length, headers.length);
  range.values = values;
  range.format.font = { name: 'Arial', size: 11 };
  range.format.columnWidth = 24;
  range.format.rowHeight = 38;
  range.format.wrapText = true;
  range.format.verticalAlignment = 'center';
  const header = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  header.format.fill = '#25465B';
  header.format.font = { name: 'Arial', size: 11, bold: true, color: '#FFFFFF' };
  header.format.rowHeight = 44;
  for (let c = 0; c < headers.length; c++) {
    const column = sheet.getRangeByIndexes(0, c, values.length, 1);
    if (/编号|ID/.test(headers[c])) {
      column.setNumberFormat('@');
      column.format.columnWidth = 38;
    }
    if (/时间/.test(headers[c]) && values.length > 1) {
      // Excel timestamps have no timezone; encode Beijing wall time as a serial.
      const cells = sheet.getRangeByIndexes(1, c, values.length - 1, 1);
      cells.values = data.tables[i].map(row => [row[c] ? Date.parse(row[c]) / 86400000 + 25569 + 8 / 24 : null]);
      cells.setNumberFormat('yyyy-mm-dd hh:mm:ss');
      column.format.columnWidth = 25;
    }
    if (/标题|正文|关键词|链接/.test(headers[c])) column.format.columnWidth = 65;
  }
  if (values.length > 1) range.format.autofitRows();
  if (i !== 0) range.format.rowHeight = 30;
  header.format.rowHeight = 44;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(1);
}
book.recalculate();
console.log((await book.inspect({kind:'sheet', include:'id,name', maxChars:2000})).ndjson);
if (process.env.WECHAT_MP_RENDER_DIR) {
  await fs.mkdir(process.env.WECHAT_MP_RENDER_DIR, {recursive:true});
  for (const name of ['说明与统计', ...data.sheets]) {
    const lastCol = name === '说明与统计' ? 'B' : String.fromCharCode(64 + data.fields[data.sheets.indexOf(name)].length);
    const preview = await book.render({sheetName:name, range:`A1:${lastCol}${name === '说明与统计' ? notes.length : 3}`, scale:1, format:'png'});
    await fs.writeFile(path.join(process.env.WECHAT_MP_RENDER_DIR, name+'.png'), new Uint8Array(await preview.arrayBuffer()));
  }
}
const file = await SpreadsheetFile.exportXlsx(book);
await file.save(output + '.tmp');
await fs.rename(output + '.tmp', output);
// The runtime's diagnostic sidecar is not part of the submission contract.
await fs.unlink(output + '.tmp.inspect.ndjson').catch(error => {
  if (error.code !== 'ENOENT') throw error;
});

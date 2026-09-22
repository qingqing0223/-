#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const artifactEntry = require.resolve("@oai/artifact-tool");
const { SpreadsheetFile, Workbook } = await import(pathToFileURL(artifactEntry).href);
const JSZip = require("jszip");

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 2) out[argv[i].replace(/^--/, "")] = argv[i + 1];
  if (!out["data-root"] || !out.output) {
    throw new Error("Usage: node scripts/export_kuaishou_techdesign_v3.mjs --data-root <ks-data-root> --output <xlsx> [--cutoff <ISO8601>]");
  }
  return out;
}

async function readJsonl(file) {
  try {
    return (await fs.readFile(file, "utf8")).split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
}

const asText = (value) => {
  if (value == null) return null;
  const text = String(value);
  // Leading apostrophe is Excel's text marker. It prevents long numeric IDs
  // from being coerced to numbers while remaining invisible in the cell.
  return /^\d{12,}$/.test(text) ? `'${text}` : text;
};
const beforeCutoff = (value, cutoff) => !cutoff || (value && Date.parse(value) <= cutoff);
const boolZh = (value) => value == null ? null : (value ? "是" : "否");
const first = (...values) => values.find((value) => value !== undefined && value !== null && value !== "") ?? null;
const kw = (row) => {
  const raw = row.source_keywords?.length
    ? row.source_keywords
    : String(row.source_keyword || "").split(/[；;,]/);
  const seen = new Set();
  const unique = [];
  for (const item of raw) {
    for (const part of String(item || "").split(/[；;,]/)) {
      const text = part.trim();
      if (!text || seen.has(text)) continue;
      seen.add(text);
      unique.push(text);
    }
  }
  return unique.join("；") || null;
};

const beijingFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
  hourCycle: "h23",
});

function beijingExcelDate(value) {
  if (value == null || value === "") return null;
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return null;
  const parts = Object.fromEntries(
    beijingFormatter.formatToParts(instant)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)])
  );
  // Excel stores a timezone-free serial. Build a synthetic UTC Date from the
  // Asia/Shanghai wall-clock components so export cannot shift it back by 8h.
  return new Date(Date.UTC(
    parts.year, parts.month - 1, parts.day,
    parts.hour, parts.minute, parts.second
  ));
}

const xmlEscape = (value) => String(value)
  .replaceAll("&", "&amp;").replaceAll('"', "&quot;")
  .replaceAll("<", "&lt;").replaceAll(">", "&gt;");

async function addNativeHyperlinks(xlsxPath, specs) {
  if (!specs.length) return;
  const zip = await JSZip.loadAsync(await fs.readFile(xlsxPath));
  const bySheet = new Map();
  for (const spec of specs) {
    if (!bySheet.has(spec.sheetIndex)) bySheet.set(spec.sheetIndex, []);
    bySheet.get(spec.sheetIndex).push(spec);
  }
  for (const [sheetIndex, links] of bySheet) {
    const sheetPath = `xl/worksheets/sheet${sheetIndex}.xml`;
    const relsPath = `xl/worksheets/_rels/sheet${sheetIndex}.xml.rels`;
    let sheetXml = await zip.file(sheetPath).async("string");
    let relsXml = zip.file(relsPath)
      ? await zip.file(relsPath).async("string")
      : '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>';
    const usedIds = [...relsXml.matchAll(/Id="rId(\d+)"/g)].map((match) => Number(match[1]));
    let nextId = Math.max(0, ...usedIds) + 1;
    const hyperlinkXml = [];
    const relationshipXml = [];
    for (const link of links) {
      const relId = `rId${nextId++}`;
      hyperlinkXml.push(`<hyperlink ref="${link.cell}" r:id="${relId}"/>`);
      relationshipXml.push(`<Relationship Id="${relId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="${xmlEscape(link.url)}" TargetMode="External"/>`);
    }
    const worksheetOpenTag = sheetXml.match(/<(?:\w+:)?worksheet\b[^>]*>/)?.[0] || "";
    if (!worksheetOpenTag.includes('xmlns:r=')) {
      sheetXml = sheetXml.replace(
        /<((?:\w+:)?worksheet)\b/,
        '<$1 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
      );
    }
    const mainPrefix = sheetXml.match(/<(\w+:)worksheet\b/)?.[1] || "";
    const namespacedLinks = hyperlinkXml.map((item) => item.replace("<hyperlink ", `<${mainPrefix}hyperlink `));
    const block = `<${mainPrefix}hyperlinks>${namespacedLinks.join("")}</${mainPrefix}hyperlinks>`;
    const insertionPoint = sheetXml.search(/<(?:\w+:)?(?:printOptions|pageMargins|pageSetup|headerFooter|drawing|legacyDrawing|tableParts|extLst)\b|<\/(?:\w+:)?worksheet>/);
    sheetXml = insertionPoint >= 0
      ? `${sheetXml.slice(0, insertionPoint)}${block}${sheetXml.slice(insertionPoint)}`
      : sheetXml;
    relsXml = relsXml.replace("</Relationships>", `${relationshipXml.join("")}</Relationships>`);
    zip.file(sheetPath, sheetXml);
    zip.file(relsPath, relsXml);
  }
  await fs.writeFile(xlsxPath, await zip.generateAsync({ type: "nodebuffer" }));
}

async function stripExcelTextMarkers(xlsxPath) {
  const zip = await JSZip.loadAsync(await fs.readFile(xlsxPath));
  const sheetFiles = Object.keys(zip.files).filter((name) => /^xl\/worksheets\/sheet\d+\.xml$/.test(name));
  for (const sheetPath of sheetFiles) {
    const xml = await zip.file(sheetPath).async("string");
    // Artifact Tool preserves the leading apostrophe as literal shared/inline
    // text. Remove only markers immediately followed by a long numeric ID;
    // the cell remains a text cell in the XLSX package.
    zip.file(sheetPath, xml
      .replace(/(<t(?:\s[^>]*)?>)'(\d{12,})(<\/t>)/g, "$1$2$3")
      .replace(/(<(?:\w+:)?v>)'(\d{12,})(<\/(?:\w+:)?v>)/g, "$1$2$3"));
  }
  const sharedPath = "xl/sharedStrings.xml";
  if (zip.file(sharedPath)) {
    const xml = await zip.file(sharedPath).async("string");
    zip.file(sharedPath, xml.replace(/(<t(?:\s[^>]*)?>)'(\d{12,})(<\/t>)/g, "$1$2$3"));
  }
  await fs.writeFile(xlsxPath, await zip.generateAsync({ type: "nodebuffer" }));
}

function latestBy(rows, keyFn, timeFn, cutoff) {
  const latest = new Map();
  for (const row of rows) {
    const time = timeFn(row);
    if (!beforeCutoff(time, cutoff)) continue;
    const key = keyFn(row);
    if (!key) continue;
    const old = latest.get(key);
    if (!old || Date.parse(time || 0) >= Date.parse(timeFn(old) || 0)) latest.set(key, row);
  }
  return [...latest.values()];
}

function addSheet(workbook, name, title, note, headers, rows, options = {}) {
  const {
    textColumns = [], dateColumns = [], linkColumns = [], wrapColumns = [],
    widths = {}, tableName = null,
  } = options;
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const lastCol = String.fromCharCode(64 + headers.length);
  sheet.mergeCells(`A1:${lastCol}1`);
  sheet.mergeCells(`A2:${lastCol}2`);
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A2").values = [[note]];
  sheet.getRange(`A3:${lastCol}3`).values = [headers];
  // Apply text formats before writing identifiers. Artifact Tool may otherwise
  // infer long numeric-looking IDs as numbers and export scientific notation.
  for (const index of textColumns) sheet.getRangeByIndexes(3, index, Math.max(rows.length, 1), 1).format.numberFormat = "@";
  if (rows.length) sheet.getRangeByIndexes(3, 0, rows.length, headers.length).values = rows;
  sheet.getRange(`A1:${lastCol}${Math.max(3, rows.length + 3)}`).format.font = { name: "Arial", size: 10, color: "#1F2937" };
  sheet.getRange("A1").format.font = { name: "Arial", size: 14, bold: true, color: "#1F2937" };
  sheet.getRange("A2").format.font = { name: "Arial", size: 10, italic: true, color: "#596579" };
  sheet.getRange("1:1").format.rowHeight = 24;
  sheet.getRange("2:2").format.rowHeight = 30;
  sheet.getRange("3:3").format.rowHeight = 32;
  sheet.getRange(`A3:${lastCol}3`).format = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
  sheet.getRange(`A3:${lastCol}${Math.max(3, rows.length + 3)}`).format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
  sheet.getRange(`A1:${lastCol}${Math.max(3, rows.length + 3)}`).format.verticalAlignment = "center";
  sheet.getRange(`A2:${lastCol}${Math.max(3, rows.length + 3)}`).format.wrapText = true;
  for (const index of textColumns) sheet.getRangeByIndexes(3, index, Math.max(rows.length, 1), 1).format.numberFormat = "@";
  for (const index of dateColumns) sheet.getRangeByIndexes(3, index, Math.max(rows.length, 1), 1).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
  for (const index of wrapColumns) sheet.getRangeByIndexes(3, index, Math.max(rows.length, 1), 1).format.wrapText = true;
  const nativeLinks = [];
  for (const index of linkColumns) {
    for (let row = 0; row < rows.length; row++) {
      const url = rows[row][index];
      if (!url) continue;
      sheet.getCell(row + 3, index).format.font = { name: "Arial", size: 10, color: "#0563C1", underline: true };
      nativeLinks.push({ cell: `${String.fromCharCode(65 + index)}${row + 4}`, url: String(url) });
    }
  }
  sheet.getRange(`A1:${lastCol}${Math.max(3, rows.length + 3)}`).format.autofitColumns();
  sheet.getRange(`A1:${lastCol}${Math.max(3, rows.length + 3)}`).format.autofitRows();
  for (let col = 0; col < headers.length; col++) {
    const width = widths[col] ?? ([0, 1, 2, 3].includes(col) ? 18 : 14);
    sheet.getRangeByIndexes(0, col, Math.max(rows.length + 3, 3), 1).format.columnWidth = width;
  }
  if (name === "说明与统计") sheet.getRange("C:C").format.columnWidth = 42;
  if (tableName) {
    const table = sheet.tables.add(`A3:${lastCol}${Math.max(3, rows.length + 3)}`, true, tableName);
    table.style = "TableStyleMedium2";
    table.showFilterButton = true;
  }
  sheet.freezePanes.freezeRows(3);
  return { sheet, nativeLinks };
}

const args = parseArgs(process.argv);
const dataRoot = path.resolve(args["data-root"]);
const output = path.resolve(args.output);
const cutoff = args.cutoff ? Date.parse(args.cutoff) : null;
const monitoringStart = Date.parse("2026-09-16T00:00:00+08:00");
if (args.cutoff && Number.isNaN(cutoff)) throw new Error(`Invalid cutoff: ${args.cutoff}`);

const normalized = await readJsonl(path.join(dataRoot, "classified", "classified_results.jsonl"));
const engagement = await readJsonl(path.join(dataRoot, "classified", "kuaishou_engagement_snapshots.jsonl"));
const accountSnapshots = await readJsonl(path.join(dataRoot, "classified", "kuaishou_account_snapshots.jsonl"));
const scoped = normalized.filter((row) => {
  const published = Date.parse(row.publish_time || "");
  return row.platform === "ks" && Number.isFinite(published) && published >= monitoringStart && beforeCutoff(row.publish_time, cutoff);
});
const contents = latestBy(scoped.filter((row) => row.record_type !== "comment"), (row) => first(row.content_id, row.url), (row) => row.first_seen_time, cutoff);
const comments = latestBy(scoped.filter((row) => row.record_type === "comment"), (row) => row.comment_id, (row) => row.first_seen_time, cutoff);
const accounts = latestBy(accountSnapshots, (row) => row.account_attributes?.account_id, (row) => row.data_collection_time, cutoff);

const t1Headers = ["发布内容编号","平台名称","发布帐号ID","帐号名称","帐号IP属地","帐号类型","内容类型","标题","正文/文案/视频说明","发布时间","数据采集时间","原始内容链接","命中的全部关键词","是否原创/转载","是否属于有效监测数据","无效原因"];
const t1 = contents.map((r) => [asText(first(r.content_id, r.url)),"快手",asText(r.author_id),r.author||null,r.ip_location||null,r.account_type||null,r.record_type||null,r.context||null,r.content||null,beijingExcelDate(r.publish_time),beijingExcelDate(first(r.first_seen_time,r.collected_time,r.data_collection_time)),r.url||null,kw(r),null,"是",null]);
const t2Headers = ["对应发布内容编号","评论编号","平台名称","评论用户ID","评论用户IP属地","评论正文","评论发布时间","是否属于有效评论","评论层级","父评论编号","根评论编号","数据采集时间"];
const t2 = comments.map((r) => [asText(r.content_id),asText(r.comment_id),"快手",asText(r.author_id),r.ip_location||null,r.content||null,beijingExcelDate(r.publish_time),"是",r.comment_level??null,asText(r.parent_comment_id),asText(r.root_comment_id),beijingExcelDate(first(r.first_seen_time,r.collected_time,r.data_collection_time))]);
const t3Headers = ["对应发布内容编号","平台名称","统计时间","阅读/播放量","点赞量","评论量","转发量","分享量","收藏量"];
const validContentIds = new Set(contents.map((r) => String(first(r.content_id, r.url))));
const validCommentIds = new Set(comments.map((r) => String(r.comment_id)));
const t3 = engagement.filter((r) => r.entity_type === "content" && validContentIds.has(String(first(r.content_id, r.url))) && beforeCutoff(r.statistics_time, cutoff)).map((r) => [asText(r.content_id),"快手",beijingExcelDate(r.statistics_time),r.metrics?.view_or_play_count??null,r.metrics?.like_count??null,r.metrics?.comment_count??null,r.metrics?.repost_count??null,r.metrics?.share_count??null,r.metrics?.favorite_count??null]);
const t4Headers = ["对应发布内容编号","评论编号","平台名称","统计时间","评论回复数","评论点赞数"];
const t4 = engagement.filter((r) => r.entity_type === "comment" && validCommentIds.has(String(r.comment_id)) && beforeCutoff(r.statistics_time, cutoff)).map((r) => [asText(r.content_id),asText(r.comment_id),"快手",beijingExcelDate(r.statistics_time),r.metrics?.reply_count??null,r.metrics?.like_count??null]);
const t5Headers = ["帐号ID","平台","帐号名称","主页地址","帐号类型","粉丝量","关注量","所属地区","所属机构","是否属于重点监测帐号","相关发文量","阅读/播放量","点赞量","评论量","转发量","收藏量","总互动量","数据采集时间"];
const t5 = accounts.map((r) => { const a=r.account_attributes||{}, g=r.monitoring_period_aggregates||{}; return [asText(a.account_id),"快手",a.account_name||null,a.profile_url||null,a.account_type||null,a.follower_count??null,a.following_count??null,a.account_region||null,a.institution||null,boolZh(a.is_key_monitor_account),g.related_post_count??null,g.view_or_play_count??null,g.like_count??null,g.comment_count??null,g.repost_count??null,g.favorite_count??null,g.total_interaction_count??null,beijingExcelDate(r.data_collection_time)]; });

const workbook = Workbook.create();
const hyperlinkSpecs = [];
addSheet(workbook,"说明与统计","快手监测数据（Tech Design V3）","仅含表1～表5；原始 JSON/CSV 单独保留。缺失或平台不公开字段保持空值，不以0估算。平台展示互动指标与实际可采集评论记录数可能存在差异，实际评论记录数不反写覆盖平台评论量。",["数据项","数量","口径"],[
  ["发布内容",t1.length,"去重后的有效主题相关内容"],["评论/回复",t2.length,"含一级评论与楼中楼"],["发布互动快照",t3.length,"重点内容小时追加快照"],["评论互动快照",t4.length,"重点评论小时追加快照"],["发布帐号",t5.length,"截至截止时间每个帐号最新一条快照"],
],{tableName:"KuaishouSummary"});
hyperlinkSpecs.push(...addSheet(workbook,"表1-发布内容","表1 发布内容基础信息表","正式范围从2026-09-16 00:00:00+08:00开始。发布时间和数据采集时间均为北京时间；数据采集时间优先采用记录首次采集时间。",t1Headers,t1,{textColumns:[0,2],dateColumns:[9,10],linkColumns:[11],wrapColumns:[7,8,12],widths:{7:24,8:48,9:20,10:20,11:36,12:30},tableName:"KuaishouTable1"}).nativeLinks.map((link)=>({...link,sheetIndex:2})));
addSheet(workbook,"表2-评论","表2 评论基础信息表","正式字段后保留评论层级、父评论编号、根评论编号和数据采集时间；时间均为北京时间，数据采集时间优先采用记录首次采集时间。",t2Headers,t2,{textColumns:[0,1,3,9,10],dateColumns:[6,11],wrapColumns:[5],widths:{5:48,6:20,11:20},tableName:"KuaishouTable2"});
addSheet(workbook,"表3-发布互动","表3 发布内容互动数据表","统计时间为北京时间，仅对重点内容按小时追加快照；缺失公开指标保持空值。",t3Headers,t3,{textColumns:[0],dateColumns:[2],widths:{2:20},tableName:"KuaishouTable3"});
addSheet(workbook,"表4-评论互动","表4 评论互动数据表","统计时间为北京时间，仅对重点评论按小时追加快照；评论回复数、点赞数为平台公开采集值。",t4Headers,t4,{textColumns:[0,1],dateColumns:[3],widths:{3:20},tableName:"KuaishouTable4"});
hyperlinkSpecs.push(...addSheet(workbook,"表5-帐号信息","表5 帐号信息表","每个有效发布帐号一行，取截止时间前最新帐号快照。数据采集时间为该帐号快照的北京时间；总互动量=点赞量+评论量+转发量+收藏量，不含阅读/播放量。",t5Headers,t5,{textColumns:[0],dateColumns:[17],linkColumns:[3],widths:{2:20,3:36,17:20},tableName:"KuaishouTable5"}).nativeLinks.map((link)=>({...link,sheetIndex:6})));
workbook.recalculate();
await fs.mkdir(path.dirname(output), { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(output);
await addNativeHyperlinks(output, hyperlinkSpecs);
await stripExcelTextMarkers(output);
console.log(JSON.stringify({ output, sheets: 6, rows: { table1: t1.length, table2: t2.length, table3: t3.length, table4: t4.length, table5: t5.length } }, null, 2));

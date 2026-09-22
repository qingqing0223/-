import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const artifactEntry = require.resolve("@oai/artifact-tool");
const { FileBlob, SpreadsheetFile } = await import(pathToFileURL(artifactEntry).href);
const JSZip = require("jszip");
const root = await fs.mkdtemp(path.join(os.tmpdir(), "ks-export-test-"));
const classified = path.join(root, "classified");
await fs.mkdir(classified, { recursive: true });

const writeJsonl = async (name, rows) => fs.writeFile(
  path.join(classified, name),
  rows.map((row) => JSON.stringify(row)).join("\n") + "\n",
  "utf8",
);

await writeJsonl("classified_results.jsonl", [
  {
    platform: "ks", record_type: "video", content_id: "12345678901234567890",
    author_id: "99887766554433221100", author: "测试帐号",
    context: "测试标题", content: "测试正文",
    publish_time: "2026-09-17T11:31:37+08:00",
    first_seen_time: "2026-09-20T20:36:53+08:00",
    url: "https://www.kuaishou.com/short-video/12345678901234567890",
    source_keywords: ["首个民族团结进步宣传周；民族团结进步倡议；首个民族团结进步宣传周", "民族团结进步倡议"],
  },
]);
await writeJsonl("kuaishou_engagement_snapshots.jsonl", [
  {
    entity_type: "content", content_id: "12345678901234567890",
    statistics_time: "2026-09-20T20:36:53+08:00",
    metrics: { view_or_play_count: null, like_count: 5, comment_count: null, repost_count: null, share_count: null, favorite_count: null },
  },
]);
await writeJsonl("kuaishou_account_snapshots.jsonl", [
  {
    account_attributes: { account_id: "99887766554433221100", account_name: "测试帐号", profile_url: null, is_key_monitor_account: false },
    monitoring_period_aggregates: { related_post_count: 1, view_or_play_count: null, like_count: 5, comment_count: null, repost_count: null, favorite_count: null, total_interaction_count: null },
    data_collection_time: "2026-09-20T20:36:53+08:00",
  },
]);

const output = path.join(root, "result.xlsx");
const exporter = path.resolve("scripts", "export_kuaishou_techdesign_v3.mjs");
const run = spawnSync(process.execPath, [exporter, "--data-root", root, "--output", output], {
  cwd: path.resolve("."), encoding: "utf8", env: process.env,
});
assert.equal(run.status, 0, run.stderr || run.stdout);

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(output));
const table1 = workbook.worksheets.getItem("表1-发布内容");
const table2 = workbook.worksheets.getItem("表2-评论");
const table3 = workbook.worksheets.getItem("表3-发布互动");
const table5 = workbook.worksheets.getItem("表5-帐号信息");

const excelSerial = (year, month, day, hour, minute, second) =>
  Date.UTC(year, month - 1, day, hour, minute, second) / 86400000 + 25569;
const publishedSerial = Number(table1.getRange("J4").values[0][0]);
const collectedSerial = Number(table1.getRange("K4").values[0][0]);
assert.ok(Math.abs(publishedSerial - excelSerial(2026, 9, 17, 11, 31, 37)) < 1e-8);
assert.ok(Math.abs(collectedSerial - excelSerial(2026, 9, 20, 20, 36, 53)) < 1e-8);
assert.ok(Math.abs(collectedSerial - excelSerial(2026, 9, 20, 12, 36, 53)) > 0.3);
assert.equal(table1.getRange("J4").format.numberFormat, "yyyy-mm-dd hh:mm:ss");
assert.equal(table1.getRange("K4").format.numberFormat, "yyyy-mm-dd hh:mm:ss");

assert.equal(table1.getRange("M4").values[0][0], "首个民族团结进步宣传周；民族团结进步倡议");
assert.equal(String(table1.getRange("A4").values[0][0]), "12345678901234567890");
assert.equal(table1.getRange("A4").format.numberFormat, "@");
assert.equal(table1.getRange("L4").values[0][0], "https://www.kuaishou.com/short-video/12345678901234567890");
const zip = await JSZip.loadAsync(await fs.readFile(output));
const sheet2Xml = await zip.file("xl/worksheets/sheet2.xml").async("string");
const sheet2Rels = await zip.file("xl/worksheets/_rels/sheet2.xml.rels").async("string");
assert.match(sheet2Xml, /<(?:\w+:)?hyperlink ref="L4" r:id="rId\d+"\/>/);
assert.match(sheet2Rels, /relationships\/hyperlink/);
assert.match(sheet2Rels, /TargetMode="External"/);
assert.equal(table2.getRange("F3").values[0][0], "评论正文");
assert.equal(table2.getRange("H3").values[0][0], "是否属于有效评论");
assert.equal(table3.getRange("D4").values[0][0], null);
assert.equal(table3.getRange("F4").values[0][0], null);
assert.equal(table5.getRange("L4").values[0][0], null);
assert.equal(table5.getRange("Q4").values[0][0], null);

await fs.rm(root, { recursive: true, force: true });
console.log("kuaishou Tech Design V3 export tests passed");

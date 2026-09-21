"""TechDesign V3 exports for the public WeChat MP source only."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess

from .mp_records import START, assess_record, key_account, normalize_name
from .mp_poms import POMS_NOTE, poms_rows

FIELDS = [
    ["发布内容编号", "平台名称", "发布帐号ID", "帐号名称", "帐号IP属地", "帐号类型", "内容类型", "标题", "正文、文案或视频描述", "发布时间", "数据采集时间", "原始内容链接", "命中的全部关键词", "是否原创/转载", "是否属于有效监测数据", "无效原因"],
    ["对应发布内容编号", "评论编号", "平台名称", "评论用户ID", "评论用户IP属地", "评论正文", "评论发布时间", "是否属于有效评论"],
    ["对应发布内容编号", "平台名称", "统计时间", "阅读/播放量", "点赞量", "评论量", "转发量", "分享量", "收藏量"],
    ["对应发布内容编号", "评论编号", "平台名称", "统计时间", "评论回复数", "评论点赞数"],
    ["帐号ID", "平台", "帐号名称", "主页地址", "帐号类型", "粉丝量", "关注量", "所属地区", "所属机构", "是否属于重点监测帐号", "相关发文量", "阅读/播放量", "点赞量", "评论量", "转发量", "收藏量", "总互动量", "数据采集时间"],
]
SHEETS = ["表1-发布内容", "表2-评论", "表3-发布互动", "表4-评论互动", "表5-帐号信息"]
FILES = ["01_表1_发布内容.csv", "02_表2_评论.csv", "03_表3_发布互动.csv", "04_表4_评论互动.csv", "05_表5_帐号信息.csv"]
WORKBOOK = "微信公众号监测数据_按TechDesignV3整理.xlsx"
LIMITATIONS = "平台公开数据源暂不提供/当前未获取：完整评论、楼中楼、IP属地、可靠完整互动量、帐号ID、粉丝量及关注量。未知值留空。"
URL_LIMITATION = "canonical URL仅通过正常公开页面及结果点击尽力解析；无法取得时保留搜狗公开跳转链接，不视为采集失败。链接可能过期，不使用非公开接口，不绕过验证码。"


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".jsonl.tmp")
    temp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    temp.replace(path)


def _sum_known(rows: list[dict], field: str):
    values = [r.get(field) for r in rows]
    return sum(values) if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values) else None


def build_tables(rows: list[dict], catalog: dict, stamp: str) -> list[list[list]]:
    tables: list[list[list]] = [[], [], [], [], []]
    accounts: dict[str, list[dict]] = {}
    for r in rows:
        r = assess_record(r) if "review_status" not in r else r
        if not r.get("candidate_eligible"):
            continue
        is_key, account_type = key_account(r.get("author", ""), catalog)
        tables[0].append([
            str(r["content_id"]), "微信公众号", str(r["author_id"]) if r.get("author_id") is not None else None,
            r.get("author") or None, r.get("account_region"), account_type or None, "文章",
            r.get("title"), r.get("content"), r.get("publish_time"), r.get("collected_at"),
            r.get("canonical_url") or r.get("url") or None,
            json.dumps(r.get("matched_keywords", []), ensure_ascii=False), r.get("original"), r["review_status"], r.get("invalid_reason") or None,
        ])
        # Keep the established tables 3/5 valid-content aggregation scope.
        if r["review_status"] != "是":
            continue
        tables[2].append([str(r["content_id"]), "微信公众号", r.get("last_seen_at") or r.get("collected_at"),
                          *[r.get(k) for k in ("views", "likes", "comments", "reposts", "shares", "favorites")]])
        if r.get("author"):
            accounts.setdefault(normalize_name(r["author"]), []).append(r)
    for group in accounts.values():
        r = group[0]
        is_key, account_type = key_account(r["author"], catalog)
        metrics = [_sum_known(group, k) for k in ("views", "likes", "comments", "reposts", "favorites")]
        interactions = [_sum_known(group, k) for k in ("likes", "comments", "reposts", "shares", "favorites")]
        tables[4].append([
            str(r["author_id"]) if r.get("author_id") is not None else None, "微信公众号", r["author"],
            r.get("profile_url"), account_type or None, None, None, r.get("account_region"), None,
            "是" if is_key else "否", len(group), *metrics,
            sum(interactions) if all(v is not None for v in interactions) else None,
            max(x.get("last_seen_at") or x.get("collected_at", "") for x in group),
        ])
    return tables


def csv_value(value):
    # CSV has no cell types. Block spreadsheet formula interpretation of public text.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def workbook_runtime(cfg: dict) -> tuple[str, dict]:
    env = os.environ.copy()
    bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    node = cfg.get("wechat_mp_node_executable") or str(bundle / "bin/node.exe")
    if not Path(node).is_file():
        node = shutil.which("node") or "node"
    if cfg.get("wechat_mp_artifact_module"):
        env["WECHAT_MP_ARTIFACT_MODULE"] = cfg["wechat_mp_artifact_module"]
    elif (bundle / "node_modules/@oai/artifact-tool/package.json").exists():
        env["WECHAT_MP_ARTIFACT_PACKAGE"] = str(bundle / "node_modules/@oai/artifact-tool")
    return node, env


def export_submission(rows: list[dict], cfg: dict, catalog: dict, stamp: str, collector: dict,
                      force: bool = False) -> dict:
    rows = [assess_record(r, cfg.get("monitoring_start_time", START), cfg.get("keywords"), cfg.get("monitoring_end_time")) for r in rows]
    rows = [r for r in rows if r["candidate_eligible"]]
    node_id = str(cfg.get("wechat_mp_node_id", "wechatmp01"))
    if not node_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("invalid wechat_mp_node_id")
    from datetime import date
    batch_date = cfg.get("wechat_mp_submission_date") or stamp[:10]
    date.fromisoformat(batch_date)
    out = Path(cfg.get("wechat_mp_submission_root", "data_submissions/wechat_mp")) / (batch_date + "_" + node_id)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = out / "export_snapshot.json"
    previous = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else {}
    from datetime import datetime
    clock = datetime.fromisoformat(stamp).timestamp()
    content_due = force or clock - previous.get("content_export_epoch", 0) >= int(cfg.get("wechat_mp_content_export_seconds", 900))
    metrics_due = force or clock - previous.get("metrics_export_epoch", 0) >= int(cfg.get("wechat_mp_interaction_export_seconds", 3600))
    if not (content_due or metrics_due):
        return {"directory": str(out), "updated": False}
    tables = build_tables(rows, catalog, stamp)
    old_tables = previous.get("tables", tables)
    for index in range(5):
        if not (content_due if index < 2 else metrics_due):
            tables[index] = old_tables[index]
        path = out / FILES[index]
        temp = path.with_suffix(".csv.tmp")
        with temp.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FIELDS[index])
            writer.writerows([[csv_value(v) for v in row] for row in tables[index]])
        # Transport files contain JSON arrays, literal strings for IDs, JSON null
        # for unknown values. POMS uses ordered English keys and native booleans.
        atomic_json(out / f"table{index+1}_batch.json.pending", poms_rows(index, tables[index]))
    coverage = collector.get("keyword_coverage", {})
    summary = {
        "schema_version": 4,
        "platform": "wechat_mp", "monitoring_start_time": cfg["monitoring_start_time"],
        "monitoring_end_time": cfg.get("monitoring_end_time"),
        "batch_id": batch_date + "_" + node_id,
        "exported_at": stamp, "total_candidates": len(tables[0]),
        "valid_articles": sum(r[14] == "是" for r in tables[0]),
        "invalid_articles": sum(r[14] == "否" for r in tables[0]),
        "pending_review_articles": sum(r[14] == "待核验" for r in tables[0]),
        "accounts": len(tables[4]), "keyword_coverage": coverage,
        "search_acceptance_complete": collector.get("search_acceptance_complete", False),
        "table_counts": [len(t) for t in tables], "collector": collector,
        "limitations": LIMITATIONS,
        "content_note": "正文列为公开搜索摘要。表1保留正式关键词实际命中且时间合格的全部候选，标记是/否/待核验及原因。时间不合格或无搜索命中证据的记录另存审计文件；原始记录不丢弃。表3/5仍按明确有效文章统计。",
        "canonical_url_limitation": URL_LIMITATION,
        "poms_json_note": POMS_NOTE,
        "identity_note": "优先真实公众号canonical URL；否则规范化标题+帐号（可靠绝对日期用于区分重发）。回退标识可能无法区分同账号同名文章。",
        "account_metrics_note": "相关发文量为本节点已采集有效文章数。互动汇总仅在该帐号全部已采集文章均有对应可靠指标时计算，不代表帐号全量。",
        "csv_note": "CSV不含单元格类型；Excel请用配套XLSX，或导入CSV时将ID列指定为文本。危险公式前缀已转义。",
        "content_export_at": stamp if content_due else previous.get("content_export_at"),
        "metrics_export_at": stamp if metrics_due else previous.get("metrics_export_at"),
    }
    payload = {**summary, "fields": FIELDS, "sheets": SHEETS, "tables": tables,
               "content_export_epoch": clock if content_due else previous.get("content_export_epoch", 0),
               "metrics_export_epoch": clock if metrics_due else previous.get("metrics_export_epoch", 0)}
    pending = out / "export_pending.json"
    atomic_json(pending, payload)
    node, env = workbook_runtime(cfg)
    staged_workbook = out / (WORKBOOK + ".pending")
    subprocess.run([node, str(Path(__file__).resolve().parents[1] / "scripts/export_wechat_mp_xlsx.mjs"),
                    str(pending.resolve()), str(staged_workbook.resolve())], env=env, check=True, timeout=240)
    # Do not replace published CSVs if workbook generation fails. summary.json
    # is written last and serves as the completion marker for this generation.
    staged_workbook.replace(out / WORKBOOK)
    for filename in FILES:
        path = out / filename
        path.with_suffix(".csv.tmp").replace(path)
    for index in range(1, 6):
        (out / f"table{index}_batch.json.pending").replace(out / f"table{index}_batch.json")
    pending.replace(snapshot)
    atomic_json(out / "summary.json", summary)
    if content_due:
        write_jsonl(out / "search_contents.jsonl", rows)
    (out / "README.txt").write_text(
        "微信公众号 TechDesign V3\n"
        f"总候选：{summary['total_candidates']}；有效：{summary['valid_articles']}；无效：{summary['invalid_articles']}；待核验：{summary['pending_review_articles']}\n"
        f"本批次全部关键词真实搜索验收完成：{summary['search_acceptance_complete']}\n"
        + summary["content_note"] + "\n" + LIMITATIONS + "\n" + URL_LIMITATION + "\n" + POMS_NOTE + "\n"
        + "逐关键词状态、页数、原始命中量、去重新增量见summary.json。\n", encoding="utf-8")
    return {"directory": str(out), "updated": True, "table_counts": summary["table_counts"]}

#!/usr/bin/env python3
"""Generate one evidence-grounded daily public-opinion DOCX report.

Numbers and charts are calculated locally from the repository's privacy-safe
node snapshots. Qwen only drafts the narrative fields and is not allowed to
change counts or invent source texts.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


PLATFORM_ORDER = ["wechat_mp", "dy", "ks", "xhs", "bili", "wb", "zhihu", "toutiao"]
PLATFORM_NAMES = {
    "wechat_mp": "微信公众号",
    "wechat_channels": "微信视频号",
    "dy": "抖音",
    "ks": "快手",
    "xhs": "小红书",
    "bili": "哔哩哔哩",
    "wb": "微博",
    "zhihu": "知乎",
    "toutiao": "今日头条",
}
DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen3.8-max"
REQUIRED_NARRATIVE_FIELDS = (
    "main_attitude",
    "attitude_summary",
    "overall_judgment",
    "issue1_title",
    "issue1_evidence",
    "issue1_recommendation",
    "issue2_title",
    "issue2_evidence",
    "issue2_recommendation",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def discover_dates(results_root: Path) -> list[date]:
    out: list[date] = []
    for child in results_root.iterdir() if results_root.exists() else []:
        if not child.is_dir():
            continue
        try:
            out.append(date.fromisoformat(child.name))
        except ValueError:
            continue
    return sorted(out)


def latest_snapshots(results_root: Path, cutoff: date) -> dict[tuple[str, str], dict[str, Any]]:
    """Keep the latest snapshot for each (platform, node) on/before cutoff."""
    selected: dict[tuple[str, str], tuple[tuple[str, str], dict[str, Any]]] = {}
    for day in discover_dates(results_root):
        if day > cutoff:
            continue
        for path in sorted((results_root / day.isoformat() / "nodes").glob("*/*.json")):
            try:
                obj = read_json(path)
            except Exception as exc:
                logging.warning("skip unreadable node file %s: %s", path, exc)
                continue
            platform = str(obj.get("platform") or path.parent.name)
            node_id = str(obj.get("node_id") or path.stem)
            rank = (day.isoformat(), str(obj.get("generated_at") or ""))
            key = (platform, node_id)
            if key not in selected or rank > selected[key][0]:
                obj["_source_file"] = str(path)
                obj["_snapshot_date"] = day.isoformat()
                selected[key] = (rank, obj)
    return {key: value[1] for key, value in selected.items()}


def empty_metrics() -> dict[str, Any]:
    return {
        "total": 0,
        "posts": 0,
        "videos": 0,
        "publications": 0,
        "comments": 0,
        "root_comments": 0,
        "reply_comments": 0,
        "status": Counter(),
        "types": Counter(),
        "attitude": Counter(),
        "comment_attitude": Counter(),
        "sources": Counter(),
        "keywords": Counter(),
        "latest_generated_at": "",
        "files": [],
    }


def aggregate_snapshots(snapshots: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    platforms: dict[str, dict[str, Any]] = defaultdict(empty_metrics)
    monitoring_start = ""
    event_name = ""
    node_files: list[str] = []

    for (platform, _node_id), node in snapshots.items():
        summary = node.get("summary") or {}
        totals = summary.get("totals") or {}
        record_types = summary.get("record_types") or {}
        dst = platforms[platform]
        total = int(totals.get("unique_records") or 0)
        comments = int(totals.get("comment_records") or record_types.get("comment") or 0)
        posts = int(record_types.get("post") or 0)
        videos = int(record_types.get("video") or 0)
        publications = posts + videos
        if publications + comments < total:
            publications = total - comments

        dst["total"] += total
        dst["posts"] += posts
        dst["videos"] += videos
        dst["publications"] += publications
        dst["comments"] += comments
        dst["root_comments"] += int(totals.get("root_comment_records") or 0)
        dst["reply_comments"] += int(totals.get("reply_comment_records") or 0)
        for field, target in (
            ("v2_status", "status"),
            ("v2_type", "types"),
            ("attitude", "attitude"),
            ("comment_attitude", "comment_attitude"),
            ("source_types", "sources"),
            ("keywords", "keywords"),
        ):
            dst[target].update({str(k): int(v) for k, v in (summary.get(field) or {}).items()})
        generated = str(node.get("generated_at") or summary.get("generated_at") or "")
        dst["latest_generated_at"] = max(dst["latest_generated_at"], generated)
        dst["files"].append(node.get("_source_file", ""))
        node_files.append(node.get("_source_file", ""))
        monitoring_start = monitoring_start or str(node.get("monitoring_start_time") or summary.get("monitoring_start_time") or "")
        event_name = event_name or str(node.get("event_name") or "")

    overall = empty_metrics()
    for metrics in platforms.values():
        for key in ("total", "posts", "videos", "publications", "comments", "root_comments", "reply_comments"):
            overall[key] += metrics[key]
        for key in ("status", "types", "attitude", "comment_attitude", "sources", "keywords"):
            overall[key].update(metrics[key])
        overall["latest_generated_at"] = max(overall["latest_generated_at"], metrics["latest_generated_at"])

    return {
        "event_name": event_name,
        "monitoring_start_time": monitoring_start,
        "platforms": dict(platforms),
        "overall": overall,
        "source_files": sorted(filter(None, node_files)),
    }


def subtract_metrics(current: dict[str, Any], previous: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    out = {"platforms": {}, "overall": empty_metrics()}
    all_platforms = set(current["platforms"]) | set(previous["platforms"])
    for platform in all_platforms:
        cur = current["platforms"].get(platform, empty_metrics())
        prev = previous["platforms"].get(platform, empty_metrics())
        row = empty_metrics()
        for key in ("total", "posts", "videos", "publications", "comments", "root_comments", "reply_comments"):
            raw = int(cur[key]) - int(prev[key])
            if raw < 0:
                warnings.append(f"{platform}.{key} cumulative counter decreased ({cur[key]} < {prev[key]}); daily increment clamped to 0")
            row[key] = max(raw, 0)
            out["overall"][key] += row[key]
        out["platforms"][platform] = row
    return out, warnings


def pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.0%"
    return f"{numerator / denominator * 100:.1f}%"


def attitude_three_way(counter: Counter) -> dict[str, int]:
    # v2.2 L1 attention is "中性信息". The summary layer uses the
    # neutral bucket for attention/neutral and the attention bucket for its
    # information_gap/consultation subtypes; all three become report "真中性".
    return {
        "认可支持": int(counter.get("support", 0)),
        "真中性": int(counter.get("neutral", 0) + counter.get("attention", 0)),
        "非支持": int(counter.get("non_support", 0)),
        "待分类": int(counter.get("unknown", 0)),
    }


def build_facts(current: dict[str, Any], previous: dict[str, Any], target: date) -> dict[str, Any]:
    daily, warnings = subtract_metrics(current, previous)
    overall = current["overall"]
    platforms = current["platforms"]
    comment_attitude = attitude_three_way(overall["comment_attitude"])
    classified_comments = sum(comment_attitude[k] for k in ("认可支持", "真中性", "非支持"))
    main_platform = max(platforms, key=lambda p: platforms[p]["total"]) if platforms else ""

    start_dt = parse_iso(current.get("monitoring_start_time", ""))
    day_index = (target - start_dt.date()).days + 1 if start_dt else 1
    latest_dt = parse_iso(overall["latest_generated_at"])
    cutoff_text = f"{target.month}月{target.day}日"
    if latest_dt and latest_dt.date() == target:
        cutoff_text += f"{latest_dt.hour}时"

    platform_rows: dict[str, Any] = {}
    for code in PLATFORM_ORDER:
        cur = platforms.get(code, empty_metrics())
        inc = daily["platforms"].get(code, empty_metrics())
        platform_rows[code] = {
            "name": PLATFORM_NAMES[code],
            "cumulative_total": cur["total"],
            "cumulative_publications": cur["publications"],
            "cumulative_posts": cur["posts"],
            "cumulative_videos": cur["videos"],
            "cumulative_comments": cur["comments"],
            "daily_total": inc["total"],
            "daily_publications": inc["publications"],
            "daily_posts": inc["posts"],
            "daily_videos": inc["videos"],
            "daily_comments": inc["comments"],
            "comment_attitude": attitude_three_way(cur["comment_attitude"]),
            "status": dict(cur["status"]),
        }

    return {
        "report_date": target.isoformat(),
        "date_text": f"{target.month}月{target.day}日",
        "cutoff_text": cutoff_text,
        "preheat_day_index": max(day_index, 1),
        "event_name": current.get("event_name") or "2026年民族团结进步宣传周预热阶段舆情监测",
        "monitoring_start_time": current.get("monitoring_start_time", ""),
        "platform_count": len([p for p in PLATFORM_ORDER if p in platforms]),
        "platform_names": [PLATFORM_NAMES[p] for p in PLATFORM_ORDER if p in platforms],
        "cumulative": {
            "total": overall["total"],
            "publications": overall["publications"],
            "posts": overall["posts"],
            "videos": overall["videos"],
            "comments": overall["comments"],
            "root_comments": overall["root_comments"],
            "reply_comments": overall["reply_comments"],
        },
        "daily_increment": {
            key: daily["overall"][key]
            for key in ("total", "publications", "posts", "videos", "comments", "root_comments", "reply_comments")
        },
        "main_platform": PLATFORM_NAMES.get(main_platform, main_platform),
        "main_platform_share": pct(platforms.get(main_platform, empty_metrics())["total"], overall["total"]),
        "short_video_share": pct(overall["videos"], overall["publications"]),
        "comment_attitude": comment_attitude,
        "classified_comment_count": classified_comments,
        "platform_rows": platform_rows,
        "status": dict(overall["status"]),
        "types": dict(overall["types"]),
        "source_types": dict(overall["sources"]),
        "keywords": dict(overall["keywords"]),
        "data_quality": {
            "unclassified_records": int(overall["status"].get("unclassified", 0)),
            "unknown_comment_attitude": comment_attitude["待分类"],
            "source_snapshot_count": len(current["source_files"]),
            "limitations": [
                "GitHub结果只含脱敏汇总，不含帖子/评论原文、URL和截图",
                "无法仅凭汇总快照核验代表性原话及其母帖上下文",
                "同一平台多节点汇总若存在交叉采集，缺少记录ID时无法再次去重",
            ],
            "warnings": warnings,
        },
        "source_files": current["source_files"],
    }


def compact_prompt_facts(facts: dict[str, Any]) -> dict[str, Any]:
    keep = copy.deepcopy(facts)
    keep.pop("source_files", None)
    keep["platform_rows"] = {
        row["name"]: {
            "累计总量": row["cumulative_total"],
            "累计评论": row["cumulative_comments"],
            "评论态度": row["comment_attitude"],
            "status": row["status"],
        }
        for row in facts["platform_rows"].values()
    }
    return keep


def load_prompt_config(path: Path) -> dict[str, Any]:
    return read_json(path)


def strip_json_fence(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def call_qwen(facts: dict[str, Any], prompt_cfg: dict[str, Any], model: str, endpoint: str, api_key: str) -> tuple[dict[str, str], dict[str, Any]]:
    user_prompt = prompt_cfg["user_prompt"].replace(
        "{facts_json}", json.dumps(compact_prompt_facts(facts), ensure_ascii=False, indent=2)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_cfg["system_prompt"]},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                response = json.loads(resp.read().decode("utf-8", errors="replace"))
            raw = response["choices"][0]["message"]["content"]
            narrative = json.loads(strip_json_fence(raw))
            if not isinstance(narrative, dict):
                raise ValueError("model response is not a JSON object")
            missing = [k for k in REQUIRED_NARRATIVE_FIELDS if not str(narrative.get(k) or "").strip()]
            if missing:
                raise ValueError("model response missing fields: " + ", ".join(missing))
            clean = {k: str(narrative[k]).strip() for k in REQUIRED_NARRATIVE_FIELDS}
            trace = {
                "model": model,
                "endpoint": endpoint,
                "attempt": attempt,
                "usage": response.get("usage") or {},
                "finish_reason": response.get("choices", [{}])[0].get("finish_reason"),
                "raw_content": raw,
            }
            return clean, trace
        except Exception as exc:
            last_error = exc
            logging.warning("Qwen request attempt %d/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"Qwen request failed after 3 attempts: {last_error}")


def fallback_narrative(facts: dict[str, Any]) -> dict[str, str]:
    a = facts["comment_attitude"]
    classified = max(facts["classified_comment_count"], 1)
    dominant = max(("认可支持", "真中性", "非支持"), key=lambda x: a[x])
    problem_platform = max(
        facts["platform_rows"].values(),
        key=lambda row: row["comment_attitude"]["非支持"],
    )
    return {
        "main_attitude": dominant + "态度",
        "attitude_summary": (
            f"已分类评论中认可支持{a['认可支持']}条（{pct(a['认可支持'], classified)}）、"
            f"真中性{a['真中性']}条（{pct(a['真中性'], classified)}）、"
            f"非支持{a['非支持']}条（{pct(a['非支持'], classified)}）。"
        ),
        "overall_judgment": "当前汇总数据显示存在需进一步核查的非支持类表达，正式研判前仍需回看原文、母帖和截图",
        "issue1_title": "部分记录尚未完成分类",
        "issue1_evidence": f"汇总快照中有{facts['data_quality']['unclassified_records']}条记录处于待分类状态，可能影响总体比例。",
        "issue1_recommendation": "补跑分类失败记录并检查API调用日志，在完成前单列待分类数量",
        "issue2_title": "非支持类评论需要原文复核",
        "issue2_evidence": f"{problem_platform['name']}的汇总数据中非支持类评论数量相对较高，但GitHub快照不含可核验原文。",
        "issue2_recommendation": "从本地classified_results.jsonl回溯对应评论、母帖、链接和截图，经人工核查后形成处置口径",
    }


def enforce_narrative_consistency(facts: dict[str, Any], narrative: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Keep model prose, but make the headline attitude arithmetically true."""
    corrected = dict(narrative)
    corrections: list[str] = []
    a = facts["comment_attitude"]
    classified = facts["classified_comment_count"]
    ordered = sorted(
        ((name, int(a[name])) for name in ("认可支持", "真中性", "非支持")),
        key=lambda item: (-item[1], item[0]),
    )
    dominant, dominant_count = ordered[0]
    runner_up, runner_count = ordered[1]
    expected_main = dominant + "态度"
    if corrected.get("main_attitude") != expected_main:
        corrections.append(
            f"main_attitude corrected from {corrected.get('main_attitude')!r} to {expected_main!r}; "
            f"counts show {dominant}={dominant_count} > {runner_up}={runner_count}"
        )
        corrected["main_attitude"] = expected_main

    if dominant_count == runner_count:
        tendency = f"{dominant}与{runner_up}数量并列"
    elif classified and (dominant_count - runner_count) / classified < 0.05:
        tendency = f"{dominant}数量略高于{runner_up}"
    else:
        tendency = f"{dominant}数量居首"
    deterministic_summary = (
        f"已分类评论中，认可支持{a['认可支持']}条（{pct(a['认可支持'], classified)}）、"
        f"真中性{a['真中性']}条（{pct(a['真中性'], classified)}）、"
        f"非支持{a['非支持']}条（{pct(a['非支持'], classified)}），{tendency}。"
    )
    if corrected.get("attitude_summary") != deterministic_summary:
        corrections.append("attitude_summary replaced with locally calculated wording")
        corrected["attitude_summary"] = deterministic_summary

    platform = max(
        facts["platform_rows"].values(),
        key=lambda row: row["comment_attitude"][dominant],
    )
    deterministic_judgment = (
        f"当前已分类评论中{tendency}，相关表达在{platform['name']}较为集中；"
        "鉴于GitHub快照仅含脱敏汇总、缺少可核验原文及母帖上下文，正式研判前仍需回到本地明细复核"
    )
    if corrected.get("overall_judgment") != deterministic_judgment:
        corrections.append("overall_judgment replaced to remove claims inconsistent with aggregate counts")
        corrected["overall_judgment"] = deterministic_judgment
    return corrected, corrections


def set_paragraph_text(paragraph, text: str, *, bold: bool = False, size: float = 12, center: bool | None = None) -> None:
    paragraph.clear()
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = "宋体"
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(size)
    if center is not None:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.JUSTIFY


def set_cell_text(cell, text: str, *, bold: bool = False) -> None:
    paragraph = cell.paragraphs[0]
    set_paragraph_text(paragraph, text, bold=bold, size=9.5, center=True)


def issue_paragraph(prefix: str, title: str, evidence: str, recommendation: str) -> str:
    title = str(title).strip().rstrip("。；;，,")
    evidence = str(evidence).strip().rstrip("。；;")
    recommendation = str(recommendation).strip().rstrip("。；;")
    if not recommendation.startswith("建议"):
        recommendation = "建议" + recommendation
    return f"{prefix}{title}。{evidence}。{recommendation}。"


def publication_text(row: dict[str, Any], prefix: str) -> str:
    posts = int(row[f"{prefix}_posts"])
    videos = int(row[f"{prefix}_videos"])
    if posts and videos:
        return f"{posts}篇图文/{videos}条视频"
    if videos:
        return f"{videos}条视频"
    if posts:
        return f"{posts}篇内容"
    return "0"


def setup_chinese_font() -> FontProperties:
    candidates = (
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    )
    font_path = next((p for p in candidates if p.exists()), None)
    plt.rcParams["axes.unicode_minus"] = False
    return FontProperties(fname=str(font_path)) if font_path else FontProperties()


def pie_chart(values: dict[str, int], output: Path, title: str, colors: list[str], *, include_zero: bool = False) -> None:
    chinese_font = setup_chinese_font()
    pairs = [(k, int(v)) for k, v in values.items() if include_zero or int(v) > 0]
    if not pairs:
        pairs = [("暂无数据", 1)]
        colors = ["#D1D5DB"]
    labels = [x[0] for x in pairs]
    counts = [x[1] for x in pairs]
    total = sum(counts)
    fig, ax = plt.subplots(figsize=(8.4, 4.1), dpi=180)
    wedges, _ = ax.pie(
        counts,
        startangle=90,
        colors=colors[: len(counts)],
        wedgeprops={"width": 0.48, "edgecolor": "white", "linewidth": 1.5},
    )
    legend = [f"{label}  {count}条（{count / total * 100:.1f}%）" for label, count in zip(labels, counts)]
    legend_font = copy.copy(chinese_font)
    legend_font.set_size(9)
    title_font = copy.copy(chinese_font)
    title_font.set_size(15)
    title_font.set_weight("bold")
    center_font = copy.copy(chinese_font)
    center_font.set_size(13)
    center_font.set_weight("bold")
    ax.legend(wedges, legend, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, prop=legend_font)
    ax.set_title(title, fontproperties=title_font, pad=14)
    ax.text(0, 0, f"合计\n{total}条", ha="center", va="center", fontproperties=center_font, color="#1F2937")
    ax.set_aspect("equal")
    fig.subplots_adjust(left=0.02, right=0.77, top=0.88, bottom=0.04)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, transparent=False, facecolor="white", bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)


def combined_pie_chart(platform_values: dict[str, int], attitude_values: dict[str, int], output: Path) -> None:
    """Draw both required pies into one image for maximum DOCX compatibility."""
    chinese_font = setup_chinese_font()
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.5), dpi=180)
    panels = [
        (
            axes[0],
            [(k, int(v)) for k, v in platform_values.items() if int(v) > 0],
            "各平台监测记录占比",
            ["#2563EB", "#0EA5E9", "#14B8A6", "#22C55E", "#84CC16", "#F59E0B", "#F97316", "#8B5CF6"],
        ),
        (
            axes[1],
            [(k, int(v)) for k, v in attitude_values.items() if int(v) > 0],
            "用户评论情感态度分布",
            ["#22A06B", "#4F86C6", "#E05A47", "#9CA3AF"],
        ),
    ]
    for ax, pairs, title, colors in panels:
        if not pairs:
            pairs = [("暂无数据", 1)]
            colors = ["#D1D5DB"]
        labels = [x[0] for x in pairs]
        counts = [x[1] for x in pairs]
        total = sum(counts)
        wedges, _ = ax.pie(
            counts,
            startangle=90,
            colors=colors[: len(counts)],
            radius=0.88,
            center=(-0.32, 0),
            wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1.2},
        )
        title_font = copy.copy(chinese_font)
        title_font.set_size(17)
        title_font.set_weight("bold")
        center_font = copy.copy(chinese_font)
        center_font.set_size(13)
        center_font.set_weight("bold")
        legend_font = copy.copy(chinese_font)
        legend_font.set_size(10.5)
        legend = [f"{label} {count}条（{count / total * 100:.1f}%）" for label, count in zip(labels, counts)]
        ax.set_title(title, fontproperties=title_font, pad=12)
        ax.text(-0.32, 0, f"合计\n{total}条", ha="center", va="center", fontproperties=center_font, color="#1F2937")
        ax.legend(wedges, legend, loc="center left", bbox_to_anchor=(0.67, 0.5), frameon=False, prop=legend_font)
        ax.set_aspect("equal")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.88, bottom=0.04, wspace=0.05)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, transparent=False, facecolor="white", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def replace_docx_media(docx_path: Path, media_name: str, replacement: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="report_docx_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as src:
            src.extractall(tmp_path)
        target = tmp_path / "word" / "media" / media_name
        if not target.exists():
            raise FileNotFoundError(f"template media not found: {media_name}")
        shutil.copyfile(replacement, target)
        rebuilt = docx_path.with_suffix(".rebuilt.docx")
        with zipfile.ZipFile(rebuilt, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for path in sorted(tmp_path.rglob("*")):
                if path.is_file():
                    dst.write(path, path.relative_to(tmp_path).as_posix())
        rebuilt.replace(docx_path)


def fill_report(template: Path, output: Path, facts: dict[str, Any], narrative: dict[str, str], combined_chart: Path) -> None:
    doc = Document(template)
    p = doc.paragraphs
    c = facts["cumulative"]
    d = facts["daily_increment"]
    a = facts["comment_attitude"]
    classified = facts["classified_comment_count"]

    set_paragraph_text(p[0], f"2026年民族团结进步宣传周\n预热第{facts['preheat_day_index']}日网络舆情情况及工作建议", bold=True, size=18, center=True)
    set_paragraph_text(p[2], f"1. 监测范围：{'、'.join(facts['platform_names'])}，共{facts['platform_count']}个平台", size=12)
    set_paragraph_text(p[12], f"截至{facts['cutoff_text']}，累计形成相关监测记录{c['total']}条，其中发布内容数据{c['publications']}条、用户评论数据{c['comments']}条。", size=12)
    set_paragraph_text(p[13], f"{facts['date_text']}单日新增相关监测记录{d['total']}条，其中发布内容数据{d['publications']}条、用户评论数据{d['comments']}条。", size=12)
    set_paragraph_text(
        p[15],
        f"{facts['main_platform']}是主要信息供给渠道，数据占比{facts['main_platform_share']}。"
        f"发布内容中短视频共{c['videos']}条，占发布内容数据的{facts['short_video_share']}。"
        f"用户评论数据累计{c['comments']}条，按累计快照差额较前一日增加{d['comments']}条。",
        size=12,
    )
    set_paragraph_text(p[16], f"表1  {facts['date_text']}网络舆情监测情况表", size=11, center=True)

    table = doc.tables[0]
    for idx, code in enumerate(PLATFORM_ORDER, start=1):
        row = facts["platform_rows"][code]
        values = [
            row["name"],
            str(row["cumulative_total"]),
            publication_text(row, "cumulative"),
            str(row["cumulative_comments"]),
            str(row["daily_total"]),
            publication_text(row, "daily"),
            str(row["daily_comments"]),
        ]
        for col, value in enumerate(values):
            set_cell_text(table.rows[idx].cells[col], value)
    total_values = [
        "合计",
        str(c["total"]),
        str(c["publications"]),
        str(c["comments"]),
        str(d["total"]),
        str(d["publications"]),
        str(d["comments"]),
    ]
    for col, value in enumerate(total_values):
        set_cell_text(table.rows[9].cells[col], value, bold=True)

    # Replace the template's placeholder illustration through python-docx so
    # both generated images use fresh, renderer-compatible relationships.
    p[17].clear()
    p[17].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p[17].add_run().add_picture(str(combined_chart), width=Inches(6.0))

    set_paragraph_text(
        p[19],
        f"从当前监测到的用户评论看，网络舆论总体以{narrative['main_attitude']}为主。"
        f"{narrative['attitude_summary']}总体看，{narrative['overall_judgment']}。",
        size=12,
    )
    pending = a["待分类"]
    pending_sentence = f"另有待分类评论{pending}条。" if pending else ""
    set_paragraph_text(
        p[20],
        f"当前共监测用户评论{c['comments']}条，其中一级评论{c['root_comments']}条、楼中楼及回复{c['reply_comments']}条。"
        f"认可支持类{a['认可支持']}条，占已分类评论的{pct(a['认可支持'], classified)}；"
        f"真中性类{a['真中性']}条，占已分类评论的{pct(a['真中性'], classified)}；"
        f"非支持类{a['非支持']}条，占已分类评论的{pct(a['非支持'], classified)}。{pending_sentence}"
        "对非支持类评论须核查具体平台、对应发布内容、代表性评论及截图后形成正式研判。",
        size=12,
    )
    p[22].clear()
    set_paragraph_text(
        p[24],
        issue_paragraph("一是", narrative["issue1_title"], narrative["issue1_evidence"], narrative["issue1_recommendation"]),
        size=12,
    )
    set_paragraph_text(
        p[25],
        issue_paragraph("二是", narrative["issue2_title"], narrative["issue2_evidence"], narrative["issue2_recommendation"]),
        size=12,
    )
    p[26].clear()

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    live_root = here.parent
    repo_root = here.parents[2]
    parser = argparse.ArgumentParser(description="Generate a daily public-opinion report from GitHub aggregate snapshots")
    parser.add_argument("--results-root", type=Path, default=repo_root / "results")
    parser.add_argument("--template", type=Path, default=here / "templates" / "舆情监测专报固定模板.docx")
    parser.add_argument("--prompt", type=Path, default=here / "report_prompt.json")
    parser.add_argument("--output-root", type=Path, default=live_root / "data" / "generated_reports")
    parser.add_argument("--date", help="report date (YYYY-MM-DD); default: latest results directory")
    parser.add_argument("--model", default=os.getenv("REPORT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--endpoint", default=os.getenv("DASHSCOPE_CHAT_COMPLETIONS_URL", DEFAULT_ENDPOINT))
    parser.add_argument("--no-api", action="store_true", help="use deterministic fallback text; useful for offline layout tests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    available = discover_dates(args.results_root)
    if not available:
        raise SystemExit(f"no dated results found under {args.results_root}")
    target = date.fromisoformat(args.date) if args.date else available[-1]
    previous_date = target - timedelta(days=1)
    run_dir = args.output_root / target.isoformat()
    configure_logging(run_dir / "report_generation.log")
    logging.info("report date=%s; results_root=%s", target, args.results_root)
    logging.info("read-only source repository; no source file will be changed")

    current = aggregate_snapshots(latest_snapshots(args.results_root, target))
    previous = aggregate_snapshots(latest_snapshots(args.results_root, previous_date))
    facts = build_facts(current, previous, target)
    facts["provenance"] = {
        "calculation": "latest snapshot per (platform,node) on/before report date; daily increment=current cumulative minus prior-day cumulative, negatives clamped to zero",
        "template": str(args.template),
        "taxonomy": str(Path(__file__).resolve().parent / "taxonomy_v2_1.json"),
    }
    write_json(run_dir / "01_report_facts.json", facts)

    platform_values = {
        PLATFORM_NAMES.get(code, code): current["platforms"][code]["total"]
        for code in PLATFORM_ORDER
        if code in current["platforms"] and current["platforms"][code]["total"] > 0
    }
    attitude_values = {k: v for k, v in facts["comment_attitude"].items() if v > 0}
    platform_chart = run_dir / "02_platform_share_pie.png"
    attitude_chart = run_dir / "03_comment_attitude_pie.png"
    combined_chart = run_dir / "04_report_pies.png"
    pie_chart(platform_values, platform_chart, "各平台监测记录占比", ["#2563EB", "#0EA5E9", "#14B8A6", "#22C55E", "#84CC16", "#F59E0B", "#F97316", "#8B5CF6"])
    pie_chart(attitude_values, attitude_chart, "用户评论情感态度分布", ["#22A06B", "#4F86C6", "#E05A47", "#9CA3AF"])
    combined_pie_chart(platform_values, attitude_values, combined_chart)

    if args.no_api:
        narrative = fallback_narrative(facts)
        trace = {"mode": "offline_fallback", "model": None}
    else:
        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("DASHSCOPE_API_KEY is required (it is intentionally not stored in the project)")
        prompt_cfg = load_prompt_config(args.prompt)
        narrative, trace = call_qwen(facts, prompt_cfg, args.model, args.endpoint, api_key)
    narrative, corrections = enforce_narrative_consistency(facts, narrative)
    trace["local_consistency_corrections"] = corrections
    write_json(run_dir / "05_model_narrative.json", narrative)
    write_json(run_dir / "06_api_trace.json", trace)

    report = run_dir / f"{target.month}月{target.day}日_网络舆情专报.docx"
    fill_report(args.template, report, facts, narrative, combined_chart)
    logging.info("report generated: %s", report)
    logging.info("facts: %s", run_dir / "01_report_facts.json")
    logging.info("log: %s", run_dir / "report_generation.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect.py 统一采集入口

用法：
  python collect.py                        # 运行全部已启用采集器，输出到 inbox/
  python collect.py weibo kuaishou         # 只运行指定采集器
  python collect.py --all                  # 包含未启用采集器（真实平台未接入时通常 0 条）
  python collect.py --demo                 # 用各平台内置示例数据演示 24 字段输出
  python collect.py --demo weibo douyin    # 只演示指定平台
  python collect.py --output /tmp/out      # 指定输出目录
  python collect.py --dry-run              # 只打印不写文件

输出约定：
  每个采集器生成一个 JSON 文件，放入 inbox/（或 --output 指定目录），
  每条记录严格包含“舆情事实表”的 24 个统一字段，供后续清洗入库直接使用。
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from collectors import get_collectors
from ingest import normalize_record

FACT_KEYS = [
    "唯一编号", "采集时间", "发布时间", "平台", "平台组", "具体来源", "账号", "正文", "原始链接",
    "地区", "地区组", "省份", "城市", "IP属地", "语言", "是否少数民族语言", "总体态度", "具体问题类别",
    "点赞量", "评论量", "转发量", "是否重点", "是否计入统计", "备注",
]


def _yn(v):
    return "是" if v else "否"


def to_fact_record(raw, normalized):
    """把归一化记录映射成事实表 24 个字段（中文列名，可直接追加进 Excel）"""
    return {
        "唯一编号": normalized.get("uid") or "",
        "采集时间": normalized.get("collected_at") or "",
        "发布时间": normalized.get("published_at") or "",
        "平台": normalized.get("platform") or "",
        "平台组": normalized.get("platform_group") or "",
        "具体来源": normalized.get("source") or "",
        "账号": normalized.get("account") or "",
        "正文": normalized.get("text") or "",
        "原始链接": normalized.get("url") or "",
        "地区": normalized.get("region") or "",
        "地区组": str(raw.get("地区组") or raw.get("region_group") or "").strip(),
        "省份": normalized.get("province") or "",
        "城市": normalized.get("city") or "",
        "IP属地": normalized.get("ip_location") or "",
        "语言": normalized.get("language") or "",
        "是否少数民族语言": _yn(normalized.get("is_minority")),
        "总体态度": normalized.get("attitude") or "",
        "具体问题类别": normalized.get("issue_category") or "",
        "点赞量": normalized.get("likes") or 0,
        "评论量": normalized.get("comments") or 0,
        "转发量": normalized.get("shares") or 0,
        "是否重点": _yn(normalized.get("is_key")),
        "是否计入统计": str(raw.get("是否计入统计") or raw.get("counted") or "是"),
        "备注": normalized.get("notes") or "",
    }


def run_collector(name, coll, demo, output_dir, dry_run):
    mode = "demo" if demo else "collect"
    if demo:
        records = coll.sample() if hasattr(coll, "sample") else []
    else:
        records = coll.collect() or []

    fact_records = []
    for raw in records:
        try:
            raw_with_origin = dict(raw)
            raw_with_origin["origin"] = name
            normalized = normalize_record(raw_with_origin)
            fact_records.append(to_fact_record(raw, normalized))
        except Exception as e:
            print(f"[{name}] 记录解析失败: {e}")

    if dry_run:
        print(f"[{name}] {coll.label} [{mode}] 原始 {len(records)} 条 → 24字段 {len(fact_records)} 条（dry-run）")
        for r in fact_records[:3]:
            print("    ", r["唯一编号"], r["平台"], r["总体态度"], (r["正文"] or "")[:30])
        return len(fact_records)

    if not fact_records:
        print(f"[{name}] {coll.label} [{mode}] 0 条，跳过写文件")
        return 0

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = f"collect_{name}_{ts}.json"
    path = os.path.join(output_dir, fn)
    payload = {
        "collector": name,
        "collectorLabel": coll.label,
        "mode": mode,
        "collectedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "recordCount": len(fact_records),
        "records": fact_records,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"[{name}] {coll.label} [{mode}] {len(fact_records)} 条 → {path}")
    return len(fact_records)


def main():
    parser = argparse.ArgumentParser(description="统一采集入口：调度各平台采集器并输出 24 字段原始记录")
    parser.add_argument("names", nargs="*", help="采集器名称（默认运行全部已启用采集器）")
    parser.add_argument("--demo", action="store_true", help="使用各平台内置示例数据演示 24 字段输出")
    parser.add_argument("--all", action="store_true", help="包含未启用采集器")
    parser.add_argument("--check", action="store_true", help="只做连通性自检（不采集数据）")
    parser.add_argument("--output", default=None, help="输出目录（默认 inbox/；--demo 默认 demo_output/）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = parser.parse_args()

    collectors = get_collectors()
    if args.names:
        selected = []
        for n in args.names:
            if n not in collectors:
                print(f"[错误] 未知采集器: {n}（可用: {', '.join(collectors)}）")
                return 1
            selected.append(n)
    else:
        selected = [n for n, c in collectors.items() if c.enabled or args.all or args.demo]

    if not selected:
        print("没有可运行的采集器（可用 --all 或 --demo）")
        return 0

    if args.check:
        ok = True
        for name in selected:
            coll = collectors[name]
            if hasattr(coll, "check"):
                ok = coll.check() and ok
            else:
                print(f"[{name}] 该采集器不支持连通性自检")
        return 0 if ok else 1

    if args.output:
        output_dir = args.output
    elif args.demo:
        output_dir = os.path.join(config.BASE_DIR, "demo_output")
    else:
        output_dir = config.INBOX_DIR

    total = 0
    for name in selected:
        total += run_collector(name, collectors[name], args.demo, output_dir, args.dry_run)
    print(f"完成：{len(selected)} 个采集器，共 {total} 条记录 → {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

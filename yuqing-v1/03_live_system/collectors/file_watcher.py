# -*- coding: utf-8 -*-
"""文件导入通道：人工导出/每日更新的渠道，把 json/jsonl/csv 丢进 inbox/ 即可自动入库"""
import csv
import json
import os
from datetime import datetime

from collectors.base import BaseCollector
from config import INBOX_DIR, PROCESSED_DIR


class FileWatcherCollector(BaseCollector):
    name = "file_watcher"
    label = "文件导入（inbox/）"
    enabled = True
    interval = 10
    note = "支持人工导出的渠道：将 json/jsonl/csv 放入 inbox/，系统自动读取、入库并归档到 inbox/processed/"

    def collect(self):
        os.makedirs(INBOX_DIR, exist_ok=True)
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        records = []
        for fname in sorted(os.listdir(INBOX_DIR)):
            if fname.startswith("."):
                continue
            path = os.path.join(INBOX_DIR, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".json", ".jsonl", ".csv"):
                continue
            try:
                items = self._parse(path, ext)
                records.extend(items)
                stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                os.rename(path, os.path.join(PROCESSED_DIR, f"{stamp}-{fname}"))
            except Exception as e:
                os.rename(path, path + ".error")
                print(f"[file_watcher] 解析失败 {fname}: {e}")
        return records

    def _parse(self, path, ext):
        if ext == ".json":
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("records", "items", "数据", "记录"):
                    if isinstance(data.get(key), list):
                        return data[key]
                if data.get("text") or data.get("正文"):
                    return [data]
            return []
        if ext == ".jsonl":
            items = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        items.append(json.loads(line))
            return items
        if ext == ".csv":
            items = []
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    items.append(dict(row))
            return items
        return []

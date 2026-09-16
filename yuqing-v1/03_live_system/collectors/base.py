# -*- coding: utf-8 -*-
"""采集器基类：新平台接入时继承并实现 collect()"""
import json
import urllib.parse
import urllib.request
from datetime import datetime


def http_get_json(url, params=None, headers=None, timeout=15):
    """标准库 GET 请求并解析 JSON（无第三方依赖）"""
    if params:
        sep = "&" if "?" in url else "?"
        url = url + sep + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ts_iso(v):
    """Unix 时间戳 → 'YYYY-MM-DDTHH:MM:SS'"""
    try:
        return datetime.fromtimestamp(int(v)).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ""


class BaseCollector:
    name = "base"
    label = "基础采集器"
    enabled = False
    interval = 60
    note = ""

    def collect(self):
        """返回原始记录列表（dict，字段可用中文别名，见 ingest.FIELD_ALIASES）"""
        raise NotImplementedError

    def sample(self):
        """返回一组示例原始记录（用于 collect.py --demo 演示 24 字段输出）"""
        return []

    def status(self):
        return {
            "name": self.name,
            "label": self.label,
            "enabled": self.enabled,
            "interval": self.interval,
            "note": self.note,
        }

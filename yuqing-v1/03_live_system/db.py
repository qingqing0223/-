# -*- coding: utf-8 -*-
"""SQLite 统一存储层（线程安全，WAL 模式）"""
import json
import os
import sqlite3
import threading

from config import DB_PATH

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT UNIQUE,
    collected_at TEXT NOT NULL,
    published_at TEXT,
    platform TEXT,
    platform_group TEXT,
    source TEXT,
    account TEXT,
    text TEXT NOT NULL,
    url TEXT,
    region TEXT,
    province TEXT,
    city TEXT,
    ip_location TEXT,
    language TEXT,
    is_minority INTEGER DEFAULT 0,
    attitude TEXT,
    attitude_bucket TEXT,
    issue_category TEXT,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    is_key INTEGER DEFAULT 0,
    is_relevant INTEGER DEFAULT 1,
    status TEXT DEFAULT 'accepted',
    notes TEXT,
    origin TEXT DEFAULT 'live'
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_origin ON incidents(origin);
CREATE INDEX IF NOT EXISTS idx_incidents_collected ON incidents(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_published ON incidents(published_at);
CREATE INDEX IF NOT EXISTS idx_incidents_platform ON incidents(platform_group);
CREATE INDEX IF NOT EXISTS idx_incidents_region ON incidents(region);
CREATE INDEX IF NOT EXISTS idx_incidents_province ON incidents(province);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS collector_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collector TEXT NOT NULL,
    ran_at TEXT NOT NULL,
    status TEXT,
    detail TEXT
);
"""


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _lock:
        conn = get_conn()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def execute(sql, params=()):
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def query_all(sql, params=()):
    with _lock:
        conn = get_conn()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()


def query_one(sql, params=()):
    with _lock:
        conn = get_conn()
        try:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def set_meta(key, value):
    execute(
        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value),
    )


def get_meta(key, default=None):
    row = query_one("SELECT value FROM meta WHERE key=?", (key,))
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def insert_incident(rec):
    sql = """
    INSERT OR IGNORE INTO incidents(
        uid, collected_at, published_at, platform, platform_group, source, account, text, url,
        region, province, city, ip_location, language, is_minority, attitude, attitude_bucket,
        issue_category, likes, comments, shares, is_key, is_relevant, status, notes, origin
    ) VALUES(
        :uid, :collected_at, :published_at, :platform, :platform_group, :source, :account, :text, :url,
        :region, :province, :city, :ip_location, :language, :is_minority, :attitude, :attitude_bucket,
        :issue_category, :likes, :comments, :shares, :is_key, :is_relevant, :status, :notes, :origin
    )
    """
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute(sql, rec)
            conn.commit()
            if cur.rowcount == 0:
                existing = conn.execute("SELECT * FROM incidents WHERE uid=?", (rec["uid"],)).fetchone()
                return dict(existing) if existing else None
            row = conn.execute("SELECT * FROM incidents WHERE id=?", (cur.lastrowid,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def log_collector_run(collector, status, detail=""):
    execute(
        "INSERT INTO collector_runs(collector, ran_at, status, detail) VALUES(?,?,?,?)",
        (collector, _now_iso(), status, detail),
    )


def _now_iso():
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def reset_db():
    """删除数据库文件（仅用于 --reset）"""
    with _lock:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        for suffix in ("-wal", "-shm"):
            p = DB_PATH + suffix
            if os.path.exists(p):
                os.remove(p)

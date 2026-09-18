#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时动态态势感知系统服务端（纯标准库：HTTP API + SSE + SQLite + 定时采集）"""
import argparse
import json
import mimetypes
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
import migrate_history
from config import (
    FILE_WATCH_ENABLED,
    FILE_WATCH_INTERVAL,
    HEARTBEAT_INTERVAL,
    HOST,
    LIVE_MIGRATE_HISTORY,
    LIVE_PLATFORM_ENABLED,
    LIVE_PLATFORM_POLL,
    PORT,
    SIM_ENABLED,
    SIM_INTERVAL,
    WEB_DIR,
)
from collectors import get_collectors
from ingest import ingest_records
from stats import build_bootstrap, key_accounts_payload, now_iso, row_to_quote


class LiveServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class):
        super().__init__(server_address, handler_class)
        self.subscribers = set()
        self.sub_lock = threading.Lock()
        self.collectors = get_collectors()

    def subscribe(self):
        q = queue.Queue()
        with self.sub_lock:
            self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        with self.sub_lock:
            self.subscribers.discard(q)

    def broadcast(self, payload):
        msg = ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
        with self.sub_lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(msg)
            except Exception:
                pass

    def run_collector(self, name):
        coll = self.collectors.get(name)
        if coll is None:
            return None
        records = coll.collect() or []
        inserted, skipped = ingest_records(records, origin=coll.name)
        if inserted or skipped:
            print(f"[{name}] 采集 {len(records)} 条，入库 {len(inserted)} 条，跳过 {skipped} 条")
        for row in inserted:
            if row["status"] == "accepted":
                self.broadcast({"type": "incident", "incident": row_to_quote(row), "collector": name})
        db.log_collector_run(name, "ok", f"records={len(records)} inserted={len(inserted)} skipped={skipped}")
        self.broadcast({"type": "refresh", "reason": f"collector:{name}"})
        return {"collector": name, "label": coll.label, "records": len(records), "inserted": len(inserted), "skipped": skipped}


class Handler(BaseHTTPRequestHandler):
    server_version = "YuqingLive/1.0"

    def log_message(self, fmt, *args):
        print("[http]", fmt % args)

    # ---------- helpers ----------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, rel):
        rel = rel.lstrip("/")
        if not rel:
            rel = "index.html"
        root = os.path.realpath(WEB_DIR)
        target = os.path.realpath(os.path.join(root, rel))
        if not target.startswith(root + os.sep) and target != root:
            self._send_json({"error": "forbidden"}, 403)
            return
        if not os.path.isfile(target):
            self._send_json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
            ctype += "; charset=utf-8"
        with open(target, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    # ---------- GET ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/api/bootstrap", "/api/stats"):
            self._send_json(build_bootstrap())
            return
        if path == "/api/health":
            self._send_json({"ok": True, "time": now_iso()})
            return
        if path == "/api/incidents":
            qs = parse_qs(parsed.query)
            limit = min(int(qs.get("limit", ["50"])[0]), 500)
            after = int(qs.get("after_id", ["0"])[0])
            include_pending = qs.get("include_pending", ["0"])[0] == "1"
            sql = "SELECT * FROM incidents WHERE id>?"
            params = [after]
            if not include_pending:
                sql += " AND status='accepted'"
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = db.query_all(sql, params)
            self._send_json({"incidents": rows, "count": len(rows)})
            return
        # 重点账号 / 大V 传播监测：预留的独立读取接口
        if path in ("/api/key-accounts", "/api/key_accounts"):
            self._send_json(key_accounts_payload())
            return
        if path == "/api/collectors":
            runs = {}
            for r in db.query_all(
                "SELECT collector, MAX(ran_at) AS ran_at, status, detail FROM collector_runs GROUP BY collector"
            ):
                runs[r["collector"]] = r
            out = []
            for name, coll in self.server.collectors.items():
                item = coll.status()
                item["lastRun"] = runs.get(name)
                out.append(item)
            self._send_json({"collectors": out})
            return
        if path == "/api/events":
            self._handle_sse()
            return
        if path.startswith("/api/"):
            self._send_json({"error": "unknown api"}, 404)
            return
        self._serve_static(path)

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = self.server.subscribe()
        try:
            while True:
                try:
                    msg = q.get(timeout=HEARTBEAT_INTERVAL)
                except queue.Empty:
                    msg = ("data: " + json.dumps({"type": "heartbeat", "ts": now_iso()}, ensure_ascii=False) + "\n\n").encode("utf-8")
                self.wfile.write(msg)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.server.unsubscribe(q)

    # ---------- POST ----------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/ingest":
            data = self._read_json()
            if data is None:
                self._send_json({"error": "invalid json"}, 400)
                return
            if isinstance(data, dict):
                records = data.get("records") or data.get("items") or []
                if not records and (data.get("text") or data.get("正文")):
                    records = [data]
            else:
                records = data
            if not isinstance(records, list):
                self._send_json({"error": "records must be a list"}, 400)
                return
            inserted, skipped = ingest_records(records, origin=data.get("origin", "api") if isinstance(data, dict) else "api")
            for row in inserted:
                if row["status"] == "accepted":
                    self.server.broadcast({"type": "incident", "incident": row_to_quote(row), "collector": "api"})
            self.server.broadcast({"type": "refresh", "reason": "api-ingest"})
            self._send_json({"inserted": len(inserted), "skipped": skipped, "ids": [r["id"] for r in inserted]})
            return
        if path.startswith("/api/collectors/"):
            name = path.rsplit("/", 1)[-1]
            result = self.server.run_collector(name)
            if result is None:
                self._send_json({"error": "collector not found"}, 404)
                return
            self._send_json(result)
            return
        # 重点账号 / 大V 传播监测：预留的写入接口（creator 监测数据接进来）
        if path in ("/api/key-accounts/ingest", "/api/key_accounts/ingest"):
            data = self._read_json()
            if data is None:
                self._send_json({"error": "invalid json"}, 400)
                return
            if isinstance(data, dict):
                records = data.get("records") or data.get("items") or []
                if not records and (data.get("text") or data.get("正文") or data.get("account") or data.get("账号")):
                    records = [data]
            else:
                records = data
            if not isinstance(records, list):
                self._send_json({"error": "records must be a list"}, 400)
                return
            for rec in records:
                if isinstance(rec, dict):
                    # 该接口写入的一律标记为重点账号
                    rec["is_key"] = 1
            inserted, skipped = ingest_records(records, origin="creator", force_accept=True)
            for row in inserted:
                self.server.broadcast({"type": "incident", "incident": row_to_quote(row), "collector": "key-accounts"})
            self.server.broadcast({"type": "refresh", "reason": "key-accounts-ingest"})
            self._send_json({"inserted": len(inserted), "skipped": skipped, "ids": [r["id"] for r in inserted]})
            return
        if path == "/api/review":
            data = self._read_json() or {}
            iid = data.get("id")
            status = data.get("status")
            if not iid or status not in ("accepted", "rejected", "pending"):
                self._send_json({"error": "id and status(accepted/rejected/pending) required"}, 400)
                return
            db.execute("UPDATE incidents SET status=? WHERE id=?", (status, iid))
            self.server.broadcast({"type": "refresh", "reason": "review"})
            self._send_json({"ok": True, "id": iid, "status": status})
            return
        self._send_json({"error": "unknown api"}, 404)


def _simulator_loop(server):
    while True:
        time.sleep(SIM_INTERVAL)
        try:
            server.run_collector("simulator")
        except Exception as e:
            print("[simulator] error:", e)


def _file_watch_loop(server):
    while True:
        time.sleep(FILE_WATCH_INTERVAL)
        try:
            server.run_collector("file_watcher")
        except Exception as e:
            print("[file_watcher] error:", e)


def _platform_collect_loop(server):
    """自动调度真实平台采集器：按各采集器自身 interval 轮询，入库后 SSE 秒级推送"""
    last = {}
    while True:
        now = time.time()
        for name, coll in server.collectors.items():
            if name in ("simulator", "file_watcher"):
                continue
            if not getattr(coll, "enabled", False):
                continue
            interval = float(getattr(coll, "interval", 600) or 600)
            if now - last.get(name, 0.0) >= interval:
                last[name] = now
                try:
                    server.run_collector(name)
                except Exception as e:
                    print(f"[{name}] 实时采集失败: {e}")
        time.sleep(LIVE_PLATFORM_POLL)


def main():
    parser = argparse.ArgumentParser(description="实时动态态势感知系统")
    parser.add_argument("--reset", action="store_true", help="清空实时库并从第一阶段数据重建基线")
    parser.add_argument("--no-sim", action="store_true", help="关闭模拟采集器")
    parser.add_argument("--selftest", action="store_true", help="自检模式：不监听端口，验证采集→入库→重算")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    if args.reset:
        print("[init] 重置数据库…")
        db.reset_db()
    db.init_db()
    if LIVE_MIGRATE_HISTORY:
        migrate_history.migrate(force=args.reset)
    else:
        print("[migrate] 历史基线迁移已关闭（LIVE_MIGRATE_HISTORY=1 可开启）")

    if args.selftest:
        print("[selftest] 开始自检（不监听端口）…")
        from collectors import get_collectors as _gc
        collectors = _gc()
        for name, coll in collectors.items():
            if not coll.enabled:
                continue
            records = coll.collect() or []
            inserted, skipped = ingest_records(records, origin=coll.name)
            print(f"[selftest] {name}: 采集 {len(records)}，入库 {len(inserted)}，跳过 {skipped}")
            db.log_collector_run(name, "ok", f"selftest records={len(records)} inserted={len(inserted)}")
        data = build_bootstrap()
        live = data.get("live", {})
        print("[selftest] bootstrap 总舆情:", data["topStats"]["totalOpinions"])
        print("[selftest] 实时增量:", live.get("counts", {}).get("total", 0))
        print("[selftest] 实时原话条数:", len(live.get("incidents", [])))
        print("[selftest] 平台组:", len(data.get("platforms", [])))
        print("[selftest] 省级行政区:", len(data.get("provinces", [])))
        print("[selftest] 原话池:", len(data.get("quotes", [])))
        print("[selftest] OK")
        return

    server = LiveServer((args.host, args.port), Handler)
    if SIM_ENABLED and not args.no_sim:
        threading.Thread(target=_simulator_loop, args=(server,), daemon=True).start()
        print(f"[simulator] 已启动，每 {SIM_INTERVAL} 秒采集一次")
    else:
        print("[simulator] 已关闭")
    if FILE_WATCH_ENABLED:
        threading.Thread(target=_file_watch_loop, args=(server,), daemon=True).start()
        print(f"[file_watcher] 已启动，每 {FILE_WATCH_INTERVAL} 秒检查 inbox/")
    if LIVE_PLATFORM_ENABLED:
        threading.Thread(target=_platform_collect_loop, args=(server,), daemon=True).start()
        print("[platform] 真实平台采集已启动：微博/抖音/B站 5 分钟，公众号/百度知道/豆瓣 10 分钟，入库后 SSE 推送")
    else:
        print("[platform] 真实平台自动调度未启用（LIVE_PLATFORM_ENABLED=1 开启）")

    print(f"[server] 实时大屏: http://{args.host}:{args.port}/")
    print(f"[server] API: http://{args.host}:{args.port}/api/bootstrap")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 已停止")


if __name__ == "__main__":
    main()

"""Independent discovery, enrichment and local publication clocks; no remote upload."""
from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import threading
import time
from urllib.parse import urlsplit

from .common import now_cn
from .mp_export import atomic_json, export_submission
from .mp_node_store import NodeStore
from .mp_pipeline import validate_config


def source_config(cfg, source):
    result = dict(cfg)
    result['wechat_mp_work_root'] = str(Path(cfg['wechat_mp_work_root']) / 'sources' / source)
    result['wechat_mp_resolve_article_urls'] = False
    result['wechat_mp_acceptance_mode'] = False
    # Normal monitoring never waits indefinitely for a human captcha.  A
    # source requiring verification is paused until --resume-source is used.
    result['wechat_mp_manual_verify_wait_seconds'] = 0
    result['wechat_mp_web_verify_inline'] = False
    return result


def discover(cfg, source, emit):
    local = source_config(cfg, source)
    local['wechat_mp_on_page'] = lambda rows, progress: emit({'records': rows, **{k: v for k, v in progress.items() if k != 'records'}})
    if source == 'sogou':
        from .mp_sogou import collect_many
        return collect_many(local, cfg['keywords'])
    from .mp_web_discovery import collect_web
    return collect_web(local, cfg['keywords'], source)


def enrich(cfg, job):
    from playwright.sync_api import sync_playwright
    from .mp_web_discovery import fetch_public_article, _wait_manual
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(Path(cfg['wechat_mp_work_root']) / 'detail_browser_profile'),
            channel=cfg.get('wechat_mp_browser_channel', 'chrome'), headless=False)
        try:
            page = context.new_page()
            url = job['row'].get('canonical_url') or job['row']['url']
            result = fetch_public_article(page, url)
            if result.get('status') == 'VERIFY_REQUIRED':
                def waiting():
                    atomic_json(Path(cfg['wechat_mp_work_root']) / 'detail_progress.json',
                                {'status': 'VERIFY_REQUIRED', 'job_id': job['id']})
                if _wait_manual(page, 0, waiting):
                    result = fetch_public_article(page, page.url)
            return result
        finally:
            context.close()


def publish_workbook(cfg, state):
    catalog = json.loads(Path(cfg.get('wechat_mp_key_accounts', 'config/key_accounts.wechat_mp.json')).read_text(encoding='utf-8'))
    coverage = {source: result.get('status', 'UNKNOWN') for source, result in state['source_status'].items()}
    return export_submission(state['records'], cfg, catalog, now_cn().isoformat(timespec='seconds'),
                             {'status': 'LOCAL_SNAPSHOT', 'source_status': state['source_status'], 'keyword_coverage': coverage}, force=False)


def start_http(cfg):
    """Loopback-only static snapshot server; no crawler or browser dependency."""
    root = Path(cfg['wechat_mp_frontend_root'])
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = urlsplit(self.path).path
            if route not in ('/', '/health', '/latest.json', *('/table%d.json' % n for n in range(1, 6))):
                self.send_error(404)
                return
            try:
                # All table endpoints use the single generation snapshot.
                snapshot = json.loads((root / 'latest.json').read_text(encoding='utf-8'))
                if route == '/health':
                    meta = snapshot.get('metadata', {})
                    body = {'status': 'ok', 'updated_at': meta.get('exported_at'),
                            'generation_id': meta.get('generation_id'),
                            'last_observation_at': meta.get('last_observation_at'),
                            'collection': meta.get('collection'), 'upload_enabled': False}
                elif route.startswith('/table'):
                    tables = snapshot['tables']
                    key = route[1:-5]
                    body = tables[key] if isinstance(tables, dict) else tables[int(key[-1])-1]
                else:
                    body = snapshot
                payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                # Do not grant arbitrary third-party sites permission to read
                # loopback snapshots. The local dashboard can use localhost.
                origin = self.headers.get('Origin', '')
                if origin.startswith(('http://localhost:', 'http://127.0.0.1:')) or origin in ('http://localhost', 'http://127.0.0.1'):
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
                self.end_headers()
                self.wfile.write(payload)
            except (OSError, ValueError, KeyError):
                self.send_error(503, 'No complete local snapshot yet')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', int(cfg.get('wechat_mp_frontend_port', 8765))), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def serve_snapshot_forever(cfg):
    """Serve an *existing* latest.json without importing or writing any data."""
    server = start_http(cfg)
    print(f"[wechat_mp] existing snapshot: http://127.0.0.1:{server.server_port}/latest.json; Ctrl+C stops HTTP", flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def run_node(cfg, *, once=False, offline=False, serve=False, run_seconds=None, resume_source=None):
    validate_config(cfg)
    from .mp_frontend import export_frontend
    store = NodeStore(cfg)
    for directory in cfg.get('wechat_mp_history_batches', []):
        origin = Path(directory)
        if not (origin / 'search_contents.jsonl').is_file():
            # Portable, byte-for-byte historical fixture. It is used only if
            # the original local batch is absent; never write to either input.
            bundled = Path('acceptance_data') / origin.name
            if (bundled / 'search_contents.jsonl').is_file():
                origin = bundled
        store.import_history(origin)
    if resume_source:
        if resume_source == 'details':
            for job in store.state['queue_jobs'].values():
                if job['status'] == 'VERIFY_REQUIRED':
                    job['status'] = 'RETRY'
                    # An explicit operator resume overrides the persisted captcha backoff.
                    job['next_attempt_at'] = now_cn().isoformat(timespec='seconds')
        else:
            store.state['source_status'].pop(resume_source, None)
        store.save()
    export_frontend(cfg, store.state)
    server = start_http(cfg) if serve else None
    if server:
        print(f"[wechat_mp] loopback snapshot HTTP: http://127.0.0.1:{server.server_port}/latest.json", flush=True)
    events = queue.Queue()
    active = {}
    next_search = {}
    rounds = set()
    last_publication = time.monotonic()
    workbook_after = 0.0
    start = time.monotonic()
    def launch(key, function, *args):
        def worker():
            try:
                events.put((key, function(*args), True))
            except Exception as exc:
                events.put((key, {'status': 'ERROR', 'error': type(exc).__name__, 'records': []}, True))
        t = threading.Thread(target=worker, name='wechat_mp_' + key, daemon=True)
        active[key] = t
        t.start()
    sources = cfg.get('wechat_mp_discovery_sources', ['sogou', 'bing'])
    if any(source not in ('sogou', 'google', 'bing') for source in sources):
        raise ValueError('Unsupported WeChat MP source')
    publication_interval = max(1, int(cfg.get('wechat_mp_frontend_export_seconds', 60)))
    try:
        while True:
            dirty = False
            try:
                while True:
                    key, result, final = events.get_nowait()
                    if final:
                        active.pop(key, None)
                    if key == 'workbook':
                        atomic_json(Path(cfg['wechat_mp_work_root']) / 'workbook_status.json', result)
                        workbook_after = time.monotonic() + (60 if result.get('status') == 'ERROR' else 30)
                    elif key == 'details':
                        job_id = store.state.get('active_detail_job')
                        if job_id:
                            store.complete_job(job_id, result)
                        store.state.pop('active_detail_job', None)
                        store.save()
                    else:
                        store.ingest(key, result)
                        if final:
                            rounds.add(key)
                            next_search[key] = time.monotonic() + int(cfg.get('wechat_mp_interval_seconds', 300))
                    dirty = True
            except queue.Empty:
                pass
            if not offline:
                for source in sources:
                    paused = store.state['source_status'].get(source, {}).get('status') == 'VERIFY_REQUIRED'
                    if source not in active and not paused and (not once or source not in rounds) and time.monotonic() >= next_search.get(source, 0):
                        previous = store.state['source_status'].get(source, {})
                        store.state['source_status'][source] = {**previous, 'status': 'RUNNING',
                            'started_at': now_cn().isoformat(timespec='seconds')}
                        store.save()
                        launch(source, discover, cfg, source, lambda result, s=source: events.put((s, result, False)))
                if cfg.get('wechat_mp_enable_detail_queue', True) and 'details' not in active:
                    job = store.take_job()
                    if job:
                        store.state['active_detail_job'] = job['id']
                        store.save()
                        launch('details', enrich, cfg, job)
            if dirty or time.monotonic()-last_publication >= publication_interval:
                for source in sources:
                    if source not in active:
                        continue
                    base = Path(source_config(cfg, source)['wechat_mp_work_root']) / 'in_progress'
                    progress = base / ('progress.json' if source == 'sogou' else source + '_progress.json')
                    try:
                        data = json.loads(progress.read_text(encoding='utf-8'))
                        if data.get('status') == 'VERIFY_REQUIRED':
                            store.state['source_status'][source] = {k: v for k, v in data.items() if k != 'records'}
                            store.save()
                    except (OSError, ValueError):
                        pass
                export_frontend(cfg, store.state)
                last_publication = time.monotonic()
            if not offline and cfg.get('wechat_mp_enable_workbook_export', True) and 'workbook' not in active and time.monotonic() >= workbook_after:
                launch('workbook', publish_workbook, cfg, deepcopy(store.state))
            done = offline or once and all(s in rounds or store.state['source_status'].get(s, {}).get('status') == 'VERIFY_REQUIRED' for s in sources)
            if done and not active and not serve:
                break
            if run_seconds is not None and time.monotonic()-start >= run_seconds:
                break
            time.sleep(.25)
    except KeyboardInterrupt:
        print('[wechat_mp] 停止；已落盘候选和队列保留，重启继续。', flush=True)
    finally:
        store.save()
        export_frontend(cfg, store.state)
        if server:
            server.shutdown()
            server.server_close()
    return {'records': len(store.state['records']), 'source_status': store.state['source_status'],
            'frontend': cfg['wechat_mp_frontend_root'], 'upload_enabled': False}

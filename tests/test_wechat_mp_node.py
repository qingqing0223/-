from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from wechat.mp_node_store import NodeStore, merge_discoveries
from wechat.mp_records import assign_identity

KEYWORD='民族团结进步倡议'
def record(**updates):
    value={'title':'2026年民族团结进步宣传周倡议', 'author':'测试帐号',
           'content':'2026年民族团结进步宣传周', 'publish_time':'2026-09-23T09:00:00+08:00',
           'collected_at':'2026-09-23T10:00:00+08:00', 'url':'https://weixin.sogou.com/link?token=1',
           'source_keyword':KEYWORD, 'matched_keywords':[KEYWORD], 'publish_date_exact':'2026-09-23',
           'views':None,'likes':None,'comments':None,'shares':None,'reposts':None,'favorites':None}
    value.update(updates)
    return assign_identity(value)

class NodeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg={'wechat_mp_work_root':self.temp.name,'monitoring_start_time':'2026-09-16T00:00:00+08:00',
                  'keywords':[KEYWORD], 'wechat_mp_detail_retry_seconds':60}
        self.store=NodeStore(self.cfg)

    def test_unresolved_url_does_not_block_candidate_or_null(self):
        raw=record()
        self.store.ingest('sogou',{'status':'PARTIAL','records':[raw]})
        saved=self.store.state['records'][0]
        self.assertTrue(saved['candidate_eligible'])
        self.assertEqual(saved['url_resolution'],'URL_UNRESOLVED')
        self.assertTrue(saved['is_valid'])
        self.assertIsNone(saved['views'])
        self.assertNotIn('discovery_sources',raw)

    def test_cross_source_dedup_keeps_keywords_evidence_and_time(self):
        a=record(discovery_sources=['sogou'],discovery_evidence=[{'source':'sogou'}])
        b=record(url='https://mp.weixin.qq.com/s/example',canonical_url='https://mp.weixin.qq.com/s/example',
                 source_keyword='第二词',matched_keywords=['第二词'],discovery_sources=['bing'],
                 discovery_evidence=[{'source':'bing'}],collected_at='2026-09-23T12:00:00+08:00')
        result=merge_discoveries([a],[b])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['content_id'],a['content_id'])
        self.assertEqual(set(result[0]['discovery_sources']),{'sogou','bing'})
        self.assertEqual(set(result[0]['matched_keywords']),{KEYWORD,'第二词'})
        self.assertEqual(len(result[0]['discovery_evidence']),2)
        self.assertEqual(result[0]['collected_at'],a['collected_at'])

    def test_pre_start_not_exportable_and_unknown_account_quarantined(self):
        self.store.ingest('sogou',{'records':[record(publish_time='2026-09-15T09:00:00+08:00')]})
        self.assertFalse(self.store.state['records'][0]['candidate_eligible'])
        self.store.ingest('google',{'records':[record(author='',publish_time='',url='https://mp.weixin.qq.com/s/other')]})
        self.assertEqual(len(self.store.state['records']),1)
        self.assertEqual(len(self.store.state['discoveries']),1)

    def test_detail_retry_restart_and_preserve_publication(self):
        self.store.ingest('sogou',{'records':[record()]})
        now=datetime.fromisoformat('2026-09-24T10:00:00+08:00')
        job=self.store.take_job(now)
        self.assertIsNotNone(job)
        self.store.complete_job(job['id'],{'status':'ERROR','error':'TimeoutError'},now)
        self.assertIsNone(self.store.take_job(now+timedelta(seconds=59)))
        restarted=NodeStore(self.cfg)
        retry=restarted.take_job(now+timedelta(seconds=61))
        self.assertEqual(retry['attempts'],2)
        detail={'status':'SUCCESS','verified_metadata':True,'title':record()['title'],'author':'测试帐号',
                'publish_time':'2026-09-23T09:00:30+08:00','content':'2026年民族团结进步宣传周完整正文',
                'canonical_url':'https://mp.weixin.qq.com/s/real'}
        self.assertTrue(restarted.complete_job(job['id'],detail,now+timedelta(seconds=62)))
        row=restarted.state['records'][0]
        self.assertEqual(row['publish_time'],'2026-09-23T09:00:00+08:00')
        self.assertEqual(row['content'],detail['content'])
        self.assertEqual(row['detail_status'],'COMPLETE')
        self.assertIsNone(row['views'])

    def test_captcha_job_pauses_while_base_is_available(self):
        self.store.ingest('sogou',{'records':[record()]})
        now=datetime.fromisoformat('2026-09-24T10:00:00+08:00')
        job=self.store.take_job(now)
        self.store.complete_job(job['id'],{'status':'VERIFY_REQUIRED'},now)
        self.assertIsNone(self.store.take_job(now+timedelta(days=1)))
        self.assertTrue(self.store.state['records'][0]['candidate_eligible'])

    def test_history_import_once_does_not_become_new_discovery(self):
        directory=Path(self.temp.name)/'history_batch'
        directory.mkdir()
        raw=record(collected_at='2026-09-23T10:00:00+08:00')
        path=directory/'search_contents.jsonl'
        path.write_text(json.dumps(raw,ensure_ascii=False)+'\n',encoding='utf-8')
        before=path.read_bytes()
        self.store.import_history(directory)
        self.store.import_history(directory)
        self.assertEqual(len(self.store.state['records']),1)
        self.assertEqual(self.store.state['new_unique_discoveries'],0)
        self.assertEqual(self.store.state['queue_jobs'],{})
        self.assertEqual(path.read_bytes(),before)

    def test_detail_cannot_attach_wrong_article(self):
        self.store.ingest('sogou',{'records':[record()]})
        now=datetime.fromisoformat('2026-09-24T10:00:00+08:00')
        job=self.store.take_job(now)
        result=self.store.complete_job(job['id'],{'status':'SUCCESS','verified_metadata':True,
            'title':'不同的文章','author':'测试帐号','publish_time':record()['publish_time'],'content':'不同文章'},now)
        self.assertFalse(result)
        self.assertEqual(self.store.state['records'][0]['content'],record()['content'])


class OfflineAcceptanceTests(unittest.TestCase):
    """Offline integration checks. Synthetic rows never enter the shipped snapshot."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(__file__).resolve().parents[1]
        original_batch = self.root / 'data_submissions/wechat_mp/2026-09-21_wechatmp02'
        self.batch = original_batch if (original_batch / 'search_contents.jsonl').is_file() else (
            self.root / 'acceptance_data/2026-09-21_wechatmp02')
        self.cfg = json.loads((self.root / 'config/monitoring.wechat.node.json').read_text(encoding='utf-8'))
        self.cfg.update(wechat_mp_work_root=str(Path(self.temp.name) / 'node'),
                        wechat_mp_frontend_root=str(Path(self.temp.name) / 'frontend'),
                        wechat_mp_history_batches=[str(original_batch)],
                        wechat_mp_frontend_port=0,
                        wechat_mp_enable_workbook_export=False)

    def test_real_history_full_offline_import_restart_export_http_and_poms(self):
        from hashlib import sha256
        from urllib.request import urlopen
        from wechat.mp_frontend import export_frontend
        from wechat.mp_node import start_http, run_node
        from wechat.mp_poms import validate_schema
        from unittest.mock import patch

        originals = [json.loads(line) for line in (self.batch / 'search_contents.jsonl').read_text('utf-8-sig').splitlines() if line.strip()]
        before = {file.name: sha256(file.read_bytes()).hexdigest() for file in self.batch.iterdir() if file.is_file()}
        with patch('wechat.mp_node.discover', side_effect=AssertionError('browser must not run')), \
                patch('wechat.mp_node.enrich', side_effect=AssertionError('detail browser must not run')), \
                patch('wechat.mp_node.publish_workbook', side_effect=AssertionError('offline workbook must not run')):
            result = run_node(self.cfg, offline=True)
        self.assertEqual(result['records'], 16)
        store = NodeStore(self.cfg)
        self.assertEqual(store.import_history(self.batch), 0)
        saved = {r['content_id']: r for r in store.state['records']}
        self.assertEqual(set(saved), {r['content_id'] for r in originals})
        for row in originals:
            for field in ('title', 'author', 'publish_time', 'content', 'review_status', 'views', 'likes', 'comments'):
                self.assertEqual(saved[row['content_id']][field], row[field], field)
        self.assertEqual(sum(r['review_status'] == '是' for r in saved.values()), 15)
        self.assertEqual(sum(r['review_status'] == '待核验' for r in saved.values()), 1)
        self.assertEqual(store.state['queue_jobs'], {})
        front = export_frontend(self.cfg, store.state)
        self.assertEqual(front['table_counts'], [16, 0, 15, 0, 15])
        self.assertEqual(front['poms_table_counts'], [16, 0, 15, 0, 15])
        self.assertEqual(front['schema_conflicts'], [])
        snapshot = json.loads(Path(front['latest']).read_text('utf-8'))
        self.assertEqual(snapshot['metadata']['new_discoveries_today']['total_candidates'], 0)
        self.assertEqual(snapshot['metadata']['history']['total_candidates'], 16)
        self.assertIsNone(snapshot['tables']['table3'][0]['阅读/播放量'])
        self.assertEqual(snapshot['metadata']['collection']['status'], 'NO_LIVE_EVIDENCE')
        validate_schema([snapshot['poms_tables'][f'table{i}'] for i in range(1, 6)])
        server = start_http(self.cfg)
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/health', timeout=2) as response:
                health = json.loads(response.read())
            self.assertEqual(health['status'], 'ok')
            self.assertEqual(health['generation_id'], snapshot['metadata']['generation_id'])
            self.assertEqual(health['collection']['status'], 'NO_LIVE_EVIDENCE')
            with urlopen(base + '/latest.json', timeout=2) as response:
                self.assertEqual(json.loads(response.read()), snapshot)
            for i, length in enumerate([16, 0, 15, 0, 15], 1):
                with urlopen(base + f'/table{i}.json', timeout=2) as response:
                    self.assertEqual(len(json.loads(response.read())), length)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(before, {file.name: sha256(file.read_bytes()).hexdigest() for file in self.batch.iterdir() if file.is_file()})

    def test_independent_sources_and_captcha_without_playwright(self):
        from unittest.mock import patch
        from wechat.mp_node import run_node
        self.cfg.update(wechat_mp_discovery_sources=['google', 'bing', 'sogou'],
                        wechat_mp_enable_detail_queue=False)
        def fake_discover(cfg, source, emit):
            if source == 'google':
                return {'status': 'VERIFY_REQUIRED', 'records': [], 'reason': 'official_captcha'}
            if source == 'bing':
                raise TimeoutError('simulated network failure')
            candidate = record()
            emit({'status': 'PARTIAL', 'records': [candidate], 'fresh_observations': 1})
            return {'status': 'SUCCESS', 'records': [candidate], 'fresh_observations': 0}
        with patch('wechat.mp_node.discover', side_effect=fake_discover):
            result = run_node(self.cfg, once=True, run_seconds=3)
        status = result['source_status']
        self.assertEqual(status['google']['status'], 'VERIFY_REQUIRED')
        self.assertEqual(status['bing']['status'], 'ERROR')
        self.assertEqual(status['sogou']['status'], 'SUCCESS')
        snapshot = json.loads((Path(self.cfg['wechat_mp_frontend_root']) / 'latest.json').read_text('utf-8'))
        self.assertEqual(snapshot['metadata']['history']['total_candidates'], 16)
        self.assertEqual(snapshot['metadata']['collection']['status'], 'LIVE_EVIDENCE_OBSERVED')
        self.assertTrue(any(r['title'] == record()['title'] for r in snapshot['records']))

    def test_blocked_source_does_not_block_snapshot_and_restart(self):
        import threading
        from unittest.mock import patch
        from wechat.mp_node import run_node
        self.cfg.update(wechat_mp_history_batches=[], wechat_mp_discovery_sources=['google', 'bing'],
                        wechat_mp_enable_detail_queue=False)
        release = threading.Event()
        entered = threading.Event()
        def fake_discover(cfg, source, emit):
            if source == 'google':
                entered.set()
                release.wait(4)
                return {'status': 'ERROR', 'records': []}
            emit({'status': 'PARTIAL', 'records': [record()], 'fresh_observations': 1})
            return {'status': 'SUCCESS', 'records': [], 'fresh_observations': 0}
        try:
            with patch('wechat.mp_node.discover', side_effect=fake_discover):
                run_node(self.cfg, run_seconds=0.8)
            self.assertTrue(entered.is_set())
            snapshot = json.loads((Path(self.cfg['wechat_mp_frontend_root']) / 'latest.json').read_text('utf-8'))
            self.assertEqual(len(snapshot['tables']['table1']), 1)
            self.assertEqual(snapshot['metadata']['source_status']['google']['status'], 'RUNNING')
            restarted = NodeStore(self.cfg)
            self.assertEqual(restarted.state['source_status']['google']['status'], 'INTERRUPTED')
        finally:
            release.set()

    def test_blocked_detail_worker_survives_restart_and_preserves_base(self):
        import threading
        from unittest.mock import patch
        from wechat.mp_node import run_node
        self.cfg.update(wechat_mp_history_batches=[], wechat_mp_discovery_sources=[],
                        wechat_mp_enable_detail_queue=True)
        seed = NodeStore(self.cfg)
        seed.ingest('sogou', {'status': 'SUCCESS', 'records': [record()]})
        entered, release = threading.Event(), threading.Event()
        def blocking_enrich(*args):
            entered.set()
            release.wait(4)
            return {'status': 'ERROR', 'error': 'test_timeout'}
        try:
            with patch('wechat.mp_node.enrich', side_effect=blocking_enrich):
                run_node(self.cfg, run_seconds=0.8)
            self.assertTrue(entered.is_set())
            snapshot = json.loads((Path(self.cfg['wechat_mp_frontend_root']) / 'latest.json').read_text('utf-8'))
            self.assertEqual(len(snapshot['tables']['table1']), 1)
            self.assertIsNone(snapshot['records'][0]['views'])
            restarted = NodeStore(self.cfg)
            self.assertEqual(len(restarted.state['queue_jobs']), 1)
            self.assertEqual(next(iter(restarted.state['queue_jobs'].values()))['status'], 'RETRY')
        finally:
            release.set()

    def test_smoke_web_import_has_no_side_effects(self):
        import runpy
        from unittest.mock import patch
        with patch('wechat.mp_web_discovery.collect_web', side_effect=AssertionError('unexpected network/browser')):
            runpy.run_path(str(self.root / 'data/wechat_mp/open_source_review/smoke_web.py'), run_name='offline_import_only')

    def test_missing_original_batch_uses_byte_identical_bundled_history(self):
        from unittest.mock import patch
        from wechat.mp_node import run_node
        self.cfg['wechat_mp_history_batches'] = [str(Path(self.temp.name) / 'missing' / '2026-09-21_wechatmp02')]
        with patch('wechat.mp_node.discover', side_effect=AssertionError('offline must not browse')):
            result = run_node(self.cfg, offline=True)
        self.assertEqual(result['records'], 16)
        snapshot = json.loads((Path(self.cfg['wechat_mp_frontend_root']) / 'latest.json').read_text('utf-8'))
        self.assertEqual(snapshot['metadata']['history']['valid_articles'], 15)
        self.assertIn('acceptance_data', snapshot['metadata']['history_input_paths']['2026-09-21_wechatmp02'])

    def test_standalone_http_subprocess_does_not_modify_snapshot(self):
        import hashlib
        import socket
        import subprocess
        import sys
        import time
        from urllib.error import URLError
        from urllib.request import urlopen
        from wechat.mp_node import run_node
        run_node(self.cfg, offline=True)
        snapshot_file = Path(self.cfg['wechat_mp_frontend_root']) / 'latest.json'
        before = hashlib.sha256(snapshot_file.read_bytes()).hexdigest()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cfg = dict(self.cfg, wechat_mp_frontend_port=port)
        config_file = Path(self.temp.name) / 'standalone.json'
        config_file.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        process = subprocess.Popen([sys.executable, 'scripts/run_wechat_mp_node.py', '--serve-only',
                                    '--config', str(config_file)], cwd=self.root,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(40):
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health', timeout=.5) as response:
                        health = json.loads(response.read())
                    break
                except (OSError, URLError):
                    if process.poll() is not None:
                        self.fail('Independent HTTP process exited prematurely: ' + process.stderr.read().decode(errors='replace'))
                    time.sleep(.1)
            else:
                self.fail('Independent HTTP never became available')
            self.assertEqual(health['status'], 'ok')
            self.assertEqual(health['collection']['status'], 'NO_LIVE_EVIDENCE')
            self.assertIsNone(process.poll(), 'HTTP must not exit after a single request')
            with urlopen(f'http://127.0.0.1:{port}/table1.json', timeout=2) as response:
                self.assertEqual(len(json.loads(response.read())), 16)
            self.assertEqual(hashlib.sha256(snapshot_file.read_bytes()).hexdigest(), before)
        finally:
            process.terminate()
            process.communicate(timeout=5)

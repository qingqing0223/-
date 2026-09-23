"""Single-writer durable discovery state and retry queue for WeChat MP only."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from urllib.parse import urlsplit

from .common import now_cn, stable_id
from .mp_export import atomic_json, write_jsonl
from .mp_records import START, assess_record, canonical_article_url, merge_records


def unique(items):
    # Retain evidence in first-observed order, not the order of a later import.
    return list({json.dumps(x, ensure_ascii=False, sort_keys=True): x for x in items}.values())


def merge_discoveries(existing, incoming):
    """Reuse existing identity rules, retaining all independent public evidence."""
    result = deepcopy(existing)
    for row in incoming:
        compatible = [old for old in result if len(merge_records([old], [row])) == 1]
        merged = merge_records(result, [row])
        if compatible:
            # merge_records uses the oldest persisted ID for cross-source bridges.
            item = next(x for x in merged if x['content_id'] == compatible[0]['content_id'])
            group = [compatible[0], row]
            for key in ('discovery_sources', 'discovery_evidence', 'matched_keywords'):
                item[key] = unique([v for x in group for v in x.get(key, [])])
            for key in ('first_discovered_at', 'collected_at'):
                values = [x[key] for x in group if x.get(key)]
                if values:
                    item[key] = min(values)
            if compatible[0].get('history_batch') or row.get('history_batch'):
                # A history import after a live discovery must still mark the
                # same article as historically known, never newly published.
                item['history_batch'] = compatible[0].get('history_batch') or row['history_batch']
        result = merged
    return result


class NodeStore:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['wechat_mp_work_root'])
        self.path = self.root / 'node_state.json'
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'schema_version': 1, 'records': [], 'discoveries': [], 'queue_jobs': {},
            'source_status': {}, 'started_at': now_cn().isoformat(), 'history_imports': [],
            'enrichment_successes': 0, 'new_unique_discoveries': 0,
        }
        # Interrupted jobs are retried only after their persisted backoff has elapsed.
        for job in self.state['queue_jobs'].values():
            if job['status'] == 'RUNNING':
                job.update(status='RETRY', last_error='worker_interrupted')
        for source, status in self.state['source_status'].items():
            if status.get('status') == 'RUNNING':
                status.update(status='INTERRUPTED', reason='collector_interrupted_on_restart')
        # A hard process kill can occur after the source checkpoint recorded a
        # captcha but before the main node consumed the final queue event.
        for source in ('sogou', 'google', 'bing'):
            progress = self.root / 'sources' / source / 'in_progress' / (
                'progress.json' if source == 'sogou' else source + '_progress.json')
            try:
                receipt = json.loads(progress.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if receipt.get('status') == 'VERIFY_REQUIRED':
                status = self.state['source_status'].setdefault(source, {})
                if status.get('status') not in ('VERIFY_REQUIRED', 'DISABLED'):
                    status.update(status='VERIFY_REQUIRED', reason='recovered_source_captcha_checkpoint')

    def save(self):
        self.state['updated_at'] = now_cn().isoformat(timespec='seconds')
        atomic_json(self.path, self.state)
        write_jsonl(self.root / 'candidates.jsonl', [r for r in self.state['records'] if r.get('candidate_eligible')])

    def assess(self, row):
        result = assess_record(row, self.config.get('monitoring_start_time', START),
                               self.config.get('keywords'), self.config.get('monitoring_end_time'))
        if not all(row.get(k) for k in ('title', 'author', 'publish_time', 'discovery_evidence')):
            result.update(candidate_eligible=False, is_valid=False, review_status='待核验',
                          invalid_reason='缺少可核验的标题、帐号、发布时间或搜索证据，等待详情核验')
        # No permanent URL is required; independently verified card metadata suffices.
        from .mp_web_discovery import stable_public_url
        if not stable_public_url(result.get('canonical_url', '')):
            result['canonical_url'] = ''
        result['url_type'] = 'WECHAT_CANONICAL' if result['canonical_url'] else ('SOGOU_REDIRECT' if urlsplit(result.get('url', '')).hostname == 'weixin.sogou.com' else 'PUBLIC_RESULT')
        result['url_resolution'] = 'RESOLVED' if result['url_type'] == 'WECHAT_CANONICAL' else 'URL_UNRESOLVED'
        return result

    def import_history(self, directory):
        directory = Path(directory)
        key = directory.name
        if key in self.state['history_imports']:
            return 0
        path = directory / 'search_contents.jsonl'
        if not path.is_file():
            raise FileNotFoundError(f'Historical input missing: {path}')
        rows = [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
        for row in rows:
            row['history_batch'] = key
        count = self.ingest('sogou', {'records': rows, 'status': 'HISTORICAL_IMPORT'}, enqueue=False, history=True)
        self.state['history_imports'].append(key)
        self.state.setdefault('history_import_paths', {})[key] = str(path)
        self.save()
        return count

    def ingest(self, source, result, *, enqueue=True, history=False):
        stamp = now_cn().isoformat(timespec='seconds')
        raw = deepcopy(result.get('records') or [])
        if raw:
            write_jsonl(self.root / 'raw_discoveries' / (now_cn().strftime('%Y%m%d_%H%M%S_%f') + '.jsonl'), raw)
        before = len(self.state['records'])
        for original in raw:
            row = deepcopy(original)
            row.setdefault('collected_at', stamp)
            row.setdefault('first_discovered_at', row['collected_at'] if history else stamp)
            row['discovery_sources'] = unique(row.get('discovery_sources', []) + [source])
            if not row.get('discovery_evidence'):
                row['discovery_evidence'] = [{'source': source, 'search_url': row.get('search_page_url'),
                    'result_url': row.get('url'), 'observed_at': row['collected_at'],
                    'keywords': row.get('matched_keywords', []), 'title': row.get('title'), 'author': row.get('author'),
                    'publish_time': row.get('publish_time')}]
            for metric in ('views', 'likes', 'comments', 'shares', 'reposts', 'favorites'):
                row.setdefault(metric, None)
            discovery_key = stable_id(source, row.get('url', ''), row.get('title', ''))
            row['discovery_id'] = discovery_key
            row = self.assess(row)
            if all(row.get(k) for k in ('title', 'author', 'publish_time')):
                self.state['records'] = merge_discoveries(self.state['records'], [row])
                self.state['records'] = [self.assess(r) for r in self.state['records']]
                merged = next((r for r in self.state['records'] if len(merge_records([r], [row])) == 1), row)
                job_key = merged['content_id']
            else:
                discoveries = {r['discovery_id']: r for r in self.state['discoveries']}
                old = discoveries.get(discovery_key, {})
                row['matched_keywords'] = unique(old.get('matched_keywords', []) + row.get('matched_keywords', []))
                row['discovery_evidence'] = unique(old.get('discovery_evidence', []) + row.get('discovery_evidence', []))
                discoveries[discovery_key] = row
                self.state['discoveries'] = list(discoveries.values())
                job_key = discovery_key
            if enqueue and row.get('url') and not row.get('content_scope') == 'full_article':
                if job_key not in self.state['queue_jobs']:
                    self.state['queue_jobs'][job_key] = {'id': job_key, 'row': deepcopy(merged) if all(row.get(k) for k in ('title', 'author', 'publish_time')) else row, 'status': 'PENDING',
                        'attempts': 0, 'next_attempt_at': stamp}
                elif self.state['queue_jobs'][job_key]['status'] in ('PENDING', 'RETRY'):
                    # New real evidence may add a working URL or verified card
                    # fields while a previous retry is waiting; keep its backoff.
                    job = self.state['queue_jobs'][job_key]
                    job['row'] = deepcopy(merged) if all(row.get(k) for k in ('title', 'author', 'publish_time')) else row
        added = len(self.state['records']) - before
        if not history:
            self.state['new_unique_discoveries'] += added
            previous = self.state['source_status'].get(source, {})
            status = {**previous, **{k: v for k, v in result.items() if k != 'records'}, 'last_attempt_at': stamp}
            if raw and result.get('status') not in ('ERROR', 'COLLECTOR_ERROR', 'VERIFY_REQUIRED') and result.get('fresh_observations', len(raw)) > 0:
                status['last_evidence_at'] = stamp
            self.state['source_status'][source] = status
        self.save()
        return added

    def take_job(self, clock=None):
        clock = clock or now_cn()
        for job in self.state['queue_jobs'].values():
            if job['status'] in ('PENDING', 'RETRY') and datetime.fromisoformat(job['next_attempt_at']) <= clock:
                job['attempts'] += 1
                job.update(status='RUNNING', next_attempt_at=(clock + timedelta(seconds=60)).isoformat())
                self.save()
                return deepcopy(job)
        return None

    def complete_job(self, job_id, detail, clock=None):
        clock = clock or now_cn()
        job = self.state['queue_jobs'].get(job_id)
        if job is None or job['status'] != 'RUNNING':
            # A duplicate/late worker result must not overwrite a newer result.
            return False
        original = job['row']
        status = detail.get('status', 'ERROR')
        # Details must identify the same article; search snippets never supply a guessed account.
        from .mp_records import normalize_name
        consistent = all(not original.get(k) or normalize_name(original[k]) == normalize_name(detail.get(k, '')) for k in ('title', 'author'))
        success = bool(detail.get('verified_metadata') and consistent and detail.get('title')
                       and detail.get('author') and detail.get('publish_time') and detail.get('content'))
        if success:
            enriched = deepcopy(original)
            for key in ('title', 'author', 'publish_time', 'canonical_url', 'content', 'publish_date_exact'):
                if detail.get(key):
                    enriched[key] = detail[key]
            enriched.update(detail_status='COMPLETE', content_scope='full_article', detail_collected_at=clock.isoformat(), detail_completed_at=clock.isoformat())
            before = len(self.state['records'])
            self.state['records'] = merge_discoveries(self.state['records'], [enriched])
            for i, row in enumerate(self.state['records']):
                if len(merge_records([row], [enriched])) == 1:
                    # Preserve original publication evidence; newer authoritative time is explicit.
                    row['publication_time_observations'] = unique(row.get('publication_time_observations', []) + [
                        {'source': 'search', 'value': original.get('publish_time')},
                        {'source': 'public_article', 'value': detail['publish_time']}])
                    row.update(content=detail['content'], content_scope='full_article', detail_status='COMPLETE',
                               detail_collected_at=clock.isoformat(), detail_completed_at=clock.isoformat())
                    self.state['records'][i] = self.assess(row)
            self.state['new_unique_discoveries'] += len(self.state['records']) - before
            self.state['discoveries'] = [r for r in self.state['discoveries'] if r.get('discovery_id') != original.get('discovery_id')]
            self.state['enrichment_successes'] += 1
            job.update(status='COMPLETE', completed_at=clock.isoformat())
        else:
            attempt = job['attempts']
            limit = int(self.config.get('wechat_mp_detail_max_attempts', 3))
            delay = min(3600, int(self.config.get('wechat_mp_detail_retry_seconds', 300)) * 2 ** max(0, attempt - 1))
            job.update(status='VERIFY_REQUIRED' if status == 'VERIFY_REQUIRED' else 'FAILED' if attempt >= limit else 'RETRY',
                       last_error='article_identity_mismatch' if detail.get('verified_metadata') and not consistent else detail.get('error', status),
                       next_attempt_at=(clock + timedelta(seconds=delay)).isoformat())
        # Receipts contain only public article fields and errors, never browser
        # cookies or local profile state.
        atomic_json(self.root / 'detail_receipts' / (job_id + '_' + str(job['attempts']) + '.json'), detail)
        self.save()
        return success

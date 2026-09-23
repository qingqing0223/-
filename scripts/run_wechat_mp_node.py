"""Local WeChat MP discovery node. No POMS or paid service upload/calls."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wechat.mp_node import run_node, serve_snapshot_forever

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config/monitoring.wechat.node.json')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--prepare-history', action='store_true', help='Offline seed and export only; no browser/network')
    parser.add_argument('--serve', action='store_true', help='Serve local frontend JSON on loopback')
    parser.add_argument('--serve-only', action='store_true', help='Independently serve an existing snapshot until Ctrl+C; no import, crawler or browser')
    parser.add_argument('--run-seconds', type=int)
    parser.add_argument('--resume-source', choices=['sogou', 'google', 'bing', 'details'])
    args = parser.parse_args()
    os.chdir(ROOT)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    if args.serve_only:
        if args.prepare_history or args.once or args.serve or args.resume_source:
            parser.error('--serve-only cannot be combined with import, crawler or resume options')
        serve_snapshot_forever(cfg)
        return
    print(json.dumps(run_node(cfg, once=args.once, offline=args.prepare_history,
        serve=args.serve, run_seconds=args.run_seconds, resume_source=args.resume_source), ensure_ascii=False))

if __name__ == '__main__':
    main()

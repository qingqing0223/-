"""Upload POMS JSON arrays using the documented batch endpoints and X-API-Key.

Server URL and credentials stay in environment variables. Never auto-invoked.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wechat.mp_poms import POMS_FIELDS, TABLE_NAMES
from wechat.mp_poms_input import check_samples, convert_batch, validate_arrays


def prepare_uploads(batch_dir: Path, cfg: dict, require_endpoint: bool = True) -> list[tuple[str, str, bytes]]:
    prepared = []
    arrays = [json.loads((batch_dir / f"table{number}_batch.json").read_text(encoding="utf-8-sig")) for number in range(1, 6)]
    validate_arrays(arrays)
    base = os.environ.get(cfg.get("url_env", "POMS_URL"), "").rstrip("/")
    for number, fields in enumerate(POMS_FIELDS, 1):
        table = f"table{number}"
        endpoint = cfg.get("endpoints", {}).get(table) or (base + "/api/v1/tables/" + TABLE_NAMES[number - 1] + "/batch" if base else "")
        url = urlsplit(endpoint)
        if require_endpoint and (url.scheme not in ("http", "https") or not url.hostname or "POMS_HOST" in endpoint or "YOUR_" in endpoint or url.username or url.password or url.query or url.fragment):
            raise ValueError(f"{table}: configure the actual POMS endpoint without inline credentials")
        rows = arrays[number - 1]
        prepared.append((table, endpoint, json.dumps(rows, ensure_ascii=False, allow_nan=False).encode("utf-8")))
    return prepared


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--server-config", type=Path, help="Optional environment variable names / endpoint overrides")
    parser.add_argument("--dry-run", action="store_true", help="Validate local files without network access")
    parser.add_argument("--convert", action="store_true", help="Convert the batch's CSV/JSONL before upload")
    parser.add_argument("--convert-only", action="store_true", help="Convert and check files without uploading")
    parser.add_argument("--source", choices=["auto", "csv", "jsonl"], default="auto")
    parser.add_argument("--config", type=Path, help="Monitoring scope/config for JSONL or CSV conversion")
    parser.add_argument("--samples-dir", type=Path, default=ROOT / "batch_test_samples")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    check_samples(args.samples_dir)
    if args.convert or args.convert_only:
        monitoring = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else None
        conversion = convert_batch(args.batch_dir, source=args.source, config=monitoring, samples_dir=args.samples_dir)
        print(json.dumps(conversion, ensure_ascii=False))
    cfg = json.loads(args.server_config.read_text(encoding="utf-8-sig")) if args.server_config else {}
    prepared = prepare_uploads(args.batch_dir, cfg, require_endpoint=not (args.dry_run or args.convert_only))
    if args.dry_run or args.convert_only:
        print(json.dumps({"validated": [t for t, _, _ in prepared], "network_requests": 0}))
        return 0
    headers = {"Content-Type": "application/json; charset=utf-8"}
    token = os.environ.get(cfg.get("token_env", "POMS_API_KEY"))
    if not token:
        raise ValueError("POMS_API_KEY credential environment variable is not set")
    if "\r" in token or "\n" in token:
        raise ValueError("Invalid credential header value")
    headers["X-API-Key"] = token
    for table, endpoint, payload in prepared:
        try:
            with urlopen(Request(endpoint, data=payload, headers=headers, method="POST"), timeout=60) as response:
                code = response.status
                if not 200 <= code < 300:
                    raise ValueError(f"{table}: unexpected HTTP status {code}")
                result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, list) or len(result) != len(json.loads(payload)):
                    print(f"{table}: unexpected response format/count; stopped, check server import results", file=sys.stderr)
                    return 1
        except HTTPError as exc:
            print(f"{table}: HTTP {exc.code}; stopped, no automatic retry", file=sys.stderr)
            return 1
        except URLError:
            print(f"{table}: network failure; server receipt is uncertain, verify before retry", file=sys.stderr)
            return 1
        except (ValueError, TimeoutError):
            print(f"{table}: invalid response or timeout; receipt uncertain, check server before retry", file=sys.stderr)
            return 1
        print(f"{table}: HTTP {code}, returned records={len(result)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        # Never print request headers, environment values, or backend response bodies.
        print(f"POMS: {exc}" if isinstance(exc, ValueError) else "POMS: cannot read/write local batch files", file=sys.stderr)
        raise SystemExit(2)

# Promotion-week monitoring raw-data policy

## Why the public repository does not receive full raw JSONL

The current repository is public. Full crawler output can contain public comment text, platform URLs, user-facing identifiers, nicknames, and other user-level fields. Publishing the complete raw JSONL into this repository would unnecessarily expose user-level data and would also cause the Git history to grow very quickly during five-minute monitoring.

Therefore the public repository is used as a **control, aggregate-result, and diagnostic layer**, not as a full raw-data lake.

## What every student node uploads every five minutes

Each platform node updates its normal result shard under:

`results/<date>/nodes/<platform>/<node-id>.json`

The shard now contains both the aggregate monitoring summary and a `raw_diagnostics` section derived from the latest crawler JSONL. The diagnostic section includes:

- latest raw-run/cycle identifier;
- JSONL file name and relative local path;
- content/comment file type;
- file byte size and row count;
- SHA-256 file hash;
- modified time;
- raw top-level field names and Python value types;
- nested field names for objects such as `user`, `user_info`, `author`, `member`, and `reply_control`;
- stable one-way hashes of content/comment/parent/root identifiers so reply linkage can be checked without publishing raw IDs;
- safe numeric/time/count fields;
- platform-displayed coarse public IP-location fields when available.

The public diagnostic snapshot intentionally excludes:

- raw post/comment text;
- raw user identifiers;
- raw content/comment identifiers;
- raw URLs;
- real IP addresses;
- precise location data.

## Full original JSONL retention

The full original JSONL and crawler logs remain in each student's local `data_root` under `raw_runs/`. Do not delete these files during the active monitoring period. Keep enough free disk space and preserve the original directory structure because these files are the source of truth for local re-analysis.

If the project later requires centralized retention of full raw JSONL, use a **separate private data repository or private storage service** with explicit access control. Do not place full raw user-level data into this public code repository.

## Five-minute requirement

Monitoring and GitHub node-summary synchronization are configured for a 300-second target. A normal monitoring cycle is scheduled start-to-start at approximately five-minute intervals when the previous cycle finishes within that window. If a crawl itself exceeds five minutes, the software records a real-time SLA miss and does not overlap a second collector process. Login, verification, soft-empty, and network-error states use safe cooldowns instead of forcing repeated requests.

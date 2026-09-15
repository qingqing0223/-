"""Command-line integration for JSONL, CSV, and one-off text."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .client import DEFAULT_BASE_URL, DEFAULT_MODEL, OpinionMonitorV2
from .schema import InputError


def read_records(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        raise InputError("input must be a .jsonl or .csv file")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise InputError(f"record {index} must be an object")
        row.setdefault("sample_id", f"record-{index:06d}")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="固定类别的v2.1舆情status/type分类")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="单条公众原话")
    source.add_argument("--input", type=Path, help="JSONL或CSV批量输入")
    parser.add_argument("--context", default="", help="单条原话的母帖上下文")
    parser.add_argument("--output", type=Path, help="批量输出JSONL；单条默认stdout")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--continue-on-error", action="store_true",
                        help="批量处理中为失败记录写error，不把失败伪装成类别")
    args = parser.parse_args(argv)
    try:
        client = OpinionMonitorV2(
            api_key_env=args.api_key_env, model=args.model, base_url=args.base_url,
            concurrency=args.concurrency, timeout=args.timeout,
            retries=args.retries, max_tokens=args.max_tokens,
        )
        if args.text is not None:
            result = client.classify(args.text, args.context)
            output = json.dumps(result.to_dict(), ensure_ascii=False)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(output + "\n", encoding="utf-8")
            else:
                print(output)
            return 0

        assert args.input is not None
        rows = read_records(args.input)
        if args.continue_on_error:
            ordered: list[dict | None] = [None] * len(rows)
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                jobs = {
                    pool.submit(client.classify, row.get("content"), row.get("context")): index
                    for index, row in enumerate(rows)
                }
                for future in as_completed(jobs):
                    index = jobs[future]
                    try:
                        ordered[index] = future.result().to_dict()
                    except Exception as exc:
                        ordered[index] = {"error": f"{type(exc).__name__}: {exc}"}
            results = [dict(row) for row in ordered]
        else:
            results = [result.to_dict() for result in client.classify_many(rows)]
        wrapped = [
            {"sample_id": str(row["sample_id"]), **result}
            for row, result in zip(rows, results)
        ]
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as handle:
                for row in wrapped:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            for row in wrapped:
                print(json.dumps(row, ensure_ascii=False))
        errors = sum("error" in row for row in wrapped)
        if errors:
            print(f"completed with {errors} failed records", file=sys.stderr)
            return 1
        return 0
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

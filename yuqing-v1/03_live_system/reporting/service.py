from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

class ReportServiceError(RuntimeError):
    pass


def _generator():
    """Load optional report dependencies only when a report operation runs."""
    from . import generator

    return generator


class ReportService:
    """Discover result dates, generate reports asynchronously, and cache them.

    The report input is deliberately independent from dashboard SQLite/data.js.
    Only repository ``results/YYYY-MM-DD/nodes`` snapshots are consumed.
    """

    def __init__(self) -> None:
        self.live_root = Path(__file__).resolve().parents[1]
        self.repo_root = Path(__file__).resolve().parents[3]
        self.results_root = Path(
            os.getenv("REPORT_RESULTS_ROOT", str(self.repo_root / "results"))
        ).resolve()
        self.output_root = Path(
            os.getenv(
                "REPORT_OUTPUT_ROOT",
                str(self.live_root / "data" / "generated_reports"),
            )
        ).resolve()
        self.template = Path(
            os.getenv(
                "REPORT_TEMPLATE",
                str(Path(__file__).resolve().parent / "templates" / "舆情监测专报固定模板.docx"),
            )
        ).resolve()
        self.prompt = Path(
            os.getenv(
                "REPORT_PROMPT",
                str(Path(__file__).resolve().parent / "report_prompt.json"),
            )
        ).resolve()
        default_model = "qwen3.8-max"
        self.model = os.getenv("REPORT_MODEL", default_model).strip() or default_model
        self.endpoint = os.getenv(
            "DASHSCOPE_CHAT_COMPLETIONS_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ).strip()
        self.allow_current = os.getenv("REPORT_ALLOW_CURRENT_DAY", "0") == "1"
        self.timezone = ZoneInfo(os.getenv("REPORT_TIMEZONE", "Asia/Shanghai"))
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self.output_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _parse_date(value: str) -> date:
        try:
            parsed = date.fromisoformat(str(value or ""))
        except ValueError as exc:
            raise ReportServiceError("日期格式必须为 YYYY-MM-DD") from exc
        return parsed

    def _today(self) -> date:
        return datetime.now(self.timezone).date()

    def available_dates(self) -> list[str]:
        dates = []
        generator = _generator()
        for day in generator.discover_dates(self.results_root):
            if any((self.results_root / day.isoformat() / "nodes").glob("*/*.json")):
                dates.append(day.isoformat())
        return sorted(dates, reverse=True)

    def _source_files(self, target: date) -> list[Path]:
        files: set[Path] = set()
        generator = _generator()
        for cutoff in (target - timedelta(days=1), target):
            for node in generator.latest_snapshots(self.results_root, cutoff).values():
                source = str(node.get("_source_file") or "")
                if source:
                    files.add(Path(source).resolve())
        files.update(
            {
                Path(generator.__file__).resolve(),
                self.prompt,
                self.template,
                Path(__file__).resolve().parent / "taxonomy_v2_1.json",
            }
        )
        return sorted(path for path in files if path.exists())

    def source_fingerprint(self, target: date) -> str:
        digest = hashlib.sha256()
        for path in self._source_files(target):
            try:
                label = str(path.relative_to(self.repo_root))
            except ValueError:
                label = str(path)
            digest.update(label.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _day_dir(self, target: date) -> Path:
        return self.output_root / target.isoformat()

    def _metadata(self, target: date) -> dict[str, Any]:
        path = self._day_dir(target) / "metadata.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _artifact_paths(self, target: date) -> dict[str, Path]:
        prefix = f"{target.month}月{target.day}日_网络舆情态势报告"
        day_dir = self._day_dir(target)
        return {
            "docx": day_dir / f"{prefix}.docx",
            "pdf": day_dir / f"{prefix}.pdf",
        }

    def _cache_state(self, target: date, fingerprint: str) -> tuple[bool, list[str], dict[str, Any]]:
        metadata = self._metadata(target)
        paths = self._artifact_paths(target)
        formats = [name for name, path in paths.items() if path.is_file()]
        current = bool(formats) and metadata.get("source_fingerprint") == fingerprint
        return current, formats, metadata

    def describe_date(self, date_text: str) -> dict[str, Any]:
        target = self._parse_date(date_text)
        source_dir = self.results_root / target.isoformat() / "nodes"
        has_source = source_dir.exists() and any(source_dir.glob("*/*.json"))
        if not has_source:
            return {
                "date": target.isoformat(),
                "status": "no_data",
                "message": "该日期暂无爬取和分析结果",
                "formats": [],
                "cached": False,
            }

        fingerprint = self.source_fingerprint(target)
        cache_current, formats, metadata = self._cache_state(target, fingerprint)
        with self._lock:
            job = dict(self._jobs.get(target.isoformat()) or {})
        if job.get("status") == "generating":
            return {
                "date": target.isoformat(),
                "status": "generating",
                "message": "报告正在生成，请稍候",
                "formats": formats if cache_current else [],
                "cached": cache_current,
                "started_at": job.get("started_at"),
            }
        if job.get("status") == "error":
            return {
                "date": target.isoformat(),
                "status": "error",
                "message": job.get("message") or "报告生成失败",
                "formats": formats if cache_current else [],
                "cached": cache_current,
            }

        collecting = target >= self._today() and not self.allow_current
        if collecting:
            message = "当天数据仍在统计和分析中"
            if cache_current:
                message += "；可下载数据更新前生成的缓存版本"
            return {
                "date": target.isoformat(),
                "status": "collecting",
                "message": message,
                "formats": formats if cache_current else [],
                "cached": cache_current,
                "generated_at": metadata.get("generated_at"),
            }

        if cache_current:
            return {
                "date": target.isoformat(),
                "status": "ready",
                "message": "报告已生成，可直接下载",
                "formats": formats,
                "cached": True,
                "generated_at": metadata.get("generated_at"),
            }
        return {
            "date": target.isoformat(),
            "status": "available",
            "message": "该日期数据已归档，首次下载前需要生成报告",
            "formats": [],
            "cached": False,
        }

    def list_reports(self) -> dict[str, Any]:
        dates = self.available_dates()
        return {
            "dates": [self.describe_date(day) for day in dates],
            "default_date": dates[0] if dates else None,
            "storage_root": str(self.output_root),
        }

    def start_generation(self, date_text: str) -> dict[str, Any]:
        current = self.describe_date(date_text)
        if current["status"] in {"no_data", "collecting"}:
            return current
        if current["status"] in {"ready", "generating"}:
            return current

        target = self._parse_date(date_text)
        with self._lock:
            existing = self._jobs.get(target.isoformat()) or {}
            if existing.get("status") == "generating":
                return self.describe_date(date_text)
            self._jobs[target.isoformat()] = {
                "status": "generating",
                "started_at": datetime.now(self.timezone).isoformat(timespec="seconds"),
                "message": "",
            }
        thread = threading.Thread(
            target=self._generate_worker,
            args=(target,),
            name=f"daily-report-{target.isoformat()}",
            daemon=True,
        )
        thread.start()
        return self.describe_date(date_text)

    def _generate_worker(self, target: date) -> None:
        try:
            self._generate(target)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._jobs[target.isoformat()] = {
                    "status": "error",
                    "message": message[:800],
                    "finished_at": datetime.now(self.timezone).isoformat(timespec="seconds"),
                }
        else:
            with self._lock:
                self._jobs.pop(target.isoformat(), None)

    def _generate(self, target: date) -> None:
        generator = _generator()
        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise ReportServiceError("服务端尚未配置 DASHSCOPE_API_KEY，无法调用 Qwen3.8 Max")

        fingerprint = self.source_fingerprint(target)
        current = generator.aggregate_snapshots(
            generator.latest_snapshots(self.results_root, target)
        )
        previous = generator.aggregate_snapshots(
            generator.latest_snapshots(self.results_root, target - timedelta(days=1))
        )
        facts = generator.build_facts(current, previous, target)
        facts["provenance"] = {
            "calculation": "latest snapshot per (platform,node) on/before report date; daily increment=current cumulative minus prior-day cumulative, negatives clamped to zero",
            "template": str(self.template),
            "taxonomy": str(Path(__file__).resolve().parent / "taxonomy_v2_1.json"),
            "source_fingerprint": fingerprint,
        }

        self.output_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{target.isoformat()}-", dir=self.output_root))
        try:
            generator.write_json(stage / "01_report_facts.json", facts)
            platform_values = {
                generator.PLATFORM_NAMES.get(code, code): current["platforms"][code]["total"]
                for code in generator.PLATFORM_ORDER
                if code in current["platforms"] and current["platforms"][code]["total"] > 0
            }
            attitude_values = {k: v for k, v in facts["comment_attitude"].items() if v > 0}
            platform_chart = stage / "02_platform_share_pie.png"
            attitude_chart = stage / "03_comment_attitude_pie.png"
            combined_chart = stage / "04_report_pies.png"
            generator.pie_chart(
                platform_values,
                platform_chart,
                "各平台监测记录占比",
                ["#2563EB", "#0EA5E9", "#14B8A6", "#22C55E", "#84CC16", "#F59E0B", "#F97316", "#8B5CF6"],
            )
            generator.pie_chart(
                attitude_values,
                attitude_chart,
                "用户评论情感态度分布",
                ["#22A06B", "#4F86C6", "#E05A47", "#9CA3AF"],
            )
            generator.combined_pie_chart(platform_values, attitude_values, combined_chart)

            prompt_cfg = generator.load_prompt_config(self.prompt)
            narrative, trace = generator.call_qwen(
                facts, prompt_cfg, self.model, self.endpoint, api_key
            )
            narrative, corrections = generator.enforce_narrative_consistency(
                facts, narrative
            )
            trace["local_consistency_corrections"] = corrections
            generator.write_json(stage / "05_model_narrative.json", narrative)
            generator.write_json(stage / "06_api_trace.json", trace)

            prefix = f"{target.month}月{target.day}日_网络舆情态势报告"
            docx_path = stage / f"{prefix}.docx"
            generator.fill_report(
                self.template, docx_path, facts, narrative, combined_chart
            )
            completed = subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(stage),
                    str(docx_path),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            pdf_path = stage / f"{prefix}.pdf"
            if completed.returncode != 0 or not pdf_path.is_file():
                raise ReportServiceError(
                    "Word已生成，但PDF转换失败："
                    + (completed.stderr or completed.stdout or "unknown error")[-500:]
                )

            metadata = {
                "date": target.isoformat(),
                "generated_at": datetime.now(self.timezone).isoformat(timespec="seconds"),
                "source_fingerprint": fingerprint,
                "model": self.model,
                "formats": ["docx", "pdf"],
                "source_files": facts.get("source_files") or [],
            }
            generator.write_json(stage / "metadata.json", metadata)

            day_dir = self._day_dir(target)
            day_dir.mkdir(parents=True, exist_ok=True)
            for source in stage.iterdir():
                os.replace(source, day_dir / source.name)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def download_path(self, date_text: str, format_name: str) -> Path:
        target = self._parse_date(date_text)
        format_name = str(format_name or "").lower()
        if format_name not in {"docx", "pdf"}:
            raise ReportServiceError("下载格式只能是 docx 或 pdf")
        state = self.describe_date(target.isoformat())
        if format_name not in state.get("formats", []):
            raise ReportServiceError(state.get("message") or "报告尚未生成")
        path = self._artifact_paths(target)[format_name]
        if not path.is_file():
            raise ReportServiceError("报告文件不存在")
        return path

# 苏琦实时大屏对接说明

目标链路：

```text
MediaCrawler（微博/小红书/抖音/快手）
    ↓ 每轮新增
志鹏 v2 分类（status + type）
    ↓ dashboard_adapter/suqi_pusher.py
苏琦实时系统 POST /api/ingest
    ↓ SQLite incidents
/api/bootstrap + SSE /api/events
    ↓
实时大屏
```

## 已核对的苏琦后端接口

苏琦仓库 `singernavyblue/Real-time-situation-map` 的 `yuqing-v1/03_live_system/server.py` 已提供：

- `GET /api/health`
- `POST /api/ingest`
- `GET /api/bootstrap`
- `GET /api/incidents`
- `GET /api/events`（SSE）

因此本仓库不需要把数据推到 GitHub Pages；应把每轮新增结果 POST 到运行中的实时后端 `/api/ingest`。

## 默认地址

本仓库配置默认：

```text
http://127.0.0.1:8765/api/ingest
```

仅当苏琦的 `server.py` 与监测程序运行在同一台电脑时，这个地址才成立。

如果大屏后端运行在同一局域网另一台电脑，例如 `192.168.1.20`，可在 PowerShell 临时设置：

```powershell
$env:SUQI_INGEST_URL="http://192.168.1.20:8765/api/ingest"
```

程序优先使用环境变量 `SUQI_INGEST_URL`，不会要求改代码。

## 健康检查

```powershell
python .\scripts\check_suqi_dashboard.py
```

返回 `ok: true` 后再启动持续监测。

## v2 → 大屏字段映射

志鹏 v2 原始结果始终保留在本地 `classified_results.jsonl`。
推送大屏时只做展示层翻译：

| v2 status/type | 大屏 attitude | 大屏 issue_category |
| --- | --- | --- |
| normal / support | 支持认可 | 空 |
| neutral / null | 中性信息 | 空 |
| attention / information_gap | 中性信息 | 咨询疑问 |
| attention / consultation | 中性信息 | 咨询疑问 |
| problematic / concern | 非支持/非肯定 | 担忧影响 |
| problematic / criticism | 非支持/非肯定 | 明确批评 |
| problematic / skepticism | 非支持/非肯定 | 明确批评* |
| problematic / implementation_issue | 非支持/非肯定 | 实施问题 |
| problematic / fairness_dispute | 非支持/非肯定 | 公平争议 |
| problematic / complaint_rights | 非支持/非肯定 | 投诉维权 |
| problematic / discriminatory_expression | 非支持/非肯定 | 歧视偏见 |

\* 苏琦当前 `stats.py` 将“质疑”合并进“明确批评”。原始 `v2_type=skepticism` 会写入 `notes`，后续如果大屏增加独立“质疑”类别，可以无损拆回。

## 去重

推送给大屏的 `uid` 使用：

```text
mediacrawler-{platform}-{sample_id}
```

苏琦后端 SQLite 的 `uid` 为 UNIQUE，因此重复推送不会形成重复记录。

## 失败处理

若大屏后端临时不可达：

- 本地采集与 v2 分类仍继续；
- `classified_results.jsonl` 不丢失；
- `latest_status.json` 会记录 `dashboard_push.ok=false` 和错误信息；
- 当前版本不会自动补发历史失败批次，后续可以增加 outbox/retry 队列。

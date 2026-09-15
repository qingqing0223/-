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

苏琦当前 `config.py` 的默认监听地址也是 `127.0.0.1:8765`。如果后端运行在同一局域网另一台电脑，需要在后端机器上把监听地址改为可被局域网访问，例如：

```powershell
$env:LIVE_HOST="0.0.0.0"
$env:LIVE_PORT="8765"
python .\server.py
```

然后在采集电脑设置：

```powershell
$env:SUQI_INGEST_URL="http://192.168.1.20:8765/api/ingest"
```

程序优先使用环境变量 `SUQI_INGEST_URL`，不会要求改代码。

如果两台电脑不在同一网络，需要把后端部署到双方都可访问的服务器或经批准的内网/VPN环境；GitHub Pages 本身不能充当写入接口。

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

\* 苏琦当前 `stats.py` 将“质疑”并入“明确批评”。原始 `v2_type=skepticism` 会写入 `notes`，后续如果大屏增加独立“质疑”类别，可以无损拆回。

## 去重

推送给大屏的 `uid` 使用：

```text
mediacrawler-{platform}-{sample_id}
```

苏琦后端 SQLite 的 `uid` 为 UNIQUE，因此重复推送不会形成重复记录。

## 失败补发

当前版本已经加入持久化 outbox：

```text
E:\MediaCrawlerData\promotion_week_monitor\outbox\suqi_pending.jsonl
```

如果大屏后端暂时不可达：

- 本地采集与 v2 分类继续；
- 本轮待推送记录写入 outbox；
- 下一轮会先合并未送达记录再自动重试；
- 苏琦后端按 `uid` 去重，因此整批重试是幂等的；
- `latest_status.json` 会记录 `outbox_before`、`outbox_after` 和错误信息。

## 当前仍建议苏琦侧做的两个小改动

基础数据流已经可以通过现有 `/api/ingest` 接通，不改苏琦仓库也能工作。但为了完全保持志鹏 v2 语义，后续建议：

1. 对 `origin=mediacrawler_v2` 的记录直接视为已完成主题筛选，避免二次关键词相关性规则把已经通过关键词检索的数据打成 `pending`；
2. 在二级分类中把 `skepticism` 单独显示为“质疑”，而不是并入“明确批评”。

这两项需要苏琦仓库写权限后再直接改。

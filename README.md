# Realtime Opinion Monitor — Phase 3

当前端到端链路：

**微博 / 小红书 / 抖音 / 快手 → MediaCrawler关键词搜索 → 增量去重 → 志鹏 v2 分类 → 苏琦实时大屏后端 `/api/ingest` → `/api/bootstrap` + SSE → 大屏**

## 当前6个重点关键词

1. 2026年民族团结进步宣传周
2. 首个民族团结进步宣传周
3. 促进民族团结进步，奋进伟大复兴征程
4. 民族团结进步倡议
5. 民族团结进步宣传周主场活动
6. 石榴花开——铸牢中华民族共同体意识

平台代码：
- `wb` 微博
- `xhs` 小红书
- `dy` 抖音
- `ks` 快手

## 监测模式

每轮只做“浅层发现”：
- 搜索6个关键词
- 获取内容基础字段
- 不抓全部评论/楼中楼
- 以 `platform + 内容ID` 跨轮次去重
- 只把新增内容送入志鹏v2分类
- 分类完成后自动推送给苏琦实时大屏后端

深度评论采集另开任务，不放进5分钟主循环。

## Windows路径

默认MediaCrawler：

```text
E:\MediaCrawler_clean
```

默认监测数据：

```text
E:\MediaCrawlerData\promotion_week_monitor
```

## 安装

```powershell
cd <项目目录>
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DASHSCOPE_API_KEY="YOUR_NEW_KEY"
```

不要使用已经暴露在聊天截图中的旧Key。

## 苏琦实时大屏对接

已核对 `singernavyblue/Real-time-situation-map` 当前实时后端代码，其 `server.py` 已提供：

```text
GET  /api/health
POST /api/ingest
GET  /api/bootstrap
GET  /api/incidents
GET  /api/events   # SSE
```

本项目已经增加 `dashboard_adapter/suqi_pusher.py`，每轮新数据完成 v2 分类后会自动 POST 到 `/api/ingest`。

默认地址：

```text
http://127.0.0.1:8765/api/ingest
```

这只适用于苏琦后端和本监测程序运行在同一台电脑。

如果苏琦后端在另一台电脑或服务器上，设置：

```powershell
$env:SUQI_INGEST_URL="http://<后端IP或域名>:8765/api/ingest"
```

先检查连接：

```powershell
python .\scripts\check_suqi_dashboard.py
```

详细字段映射见：

```text
docs/SUQI_DASHBOARD_INTEGRATION.md
```

## 第一次先跑一轮

```powershell
.\scripts\test_one_cycle_windows.ps1
```

确认：

```text
MediaCrawler 四平台搜索
→ 增量去重
→ v2 分类
→ dashboard_push.ok=true
```

再持续运行：

```powershell
.\scripts\start_monitor_windows.ps1
```

## 每5分钟的实际含义

配置目标周期为300秒。

如果一轮四个平台总耗时小于5分钟，则等到下一个5分钟周期。
如果一轮本身超过5分钟，程序不会叠加开启另一轮浏览器，而是当前轮结束后立即开始下一轮。

因此：
**已经具备5分钟调度逻辑，但“四平台+六关键词是否能在这台电脑上稳定5分钟完成一轮”仍必须实测。**

默认：

```json
"max_parallel_platforms": 1
```

这是保守设置。老师要求的“单机能并行几个”需要先比较1、2、3个平台并行的耗时、CPU/内存、验证码和风控，再决定是否把它改成2或更高。

## v2分类

保留志鹏当前v2原始口径：

- status: `normal / neutral / attention / problematic`
- type: `support / information_gap / consultation / concern / criticism / skepticism / implementation_issue / fairness_dispute / complaint_rights / discriminatory_expression / null`

原始分类结果：

```text
E:\MediaCrawlerData\promotion_week_monitor\classified\classified_results.jsonl
```

最近一轮状态：

```text
E:\MediaCrawlerData\promotion_week_monitor\status\latest_status.json
```

其中会记录：

```json
"dashboard_push": {
  "enabled": true,
  "ok": true,
  "sent": 12,
  "inserted": 12,
  "skipped": 0
}
```

## 风控

本项目不会自动解决、识别或绕过验证码。
出现验证码、登录失效、软空等情况时，应停止该平台的自动请求并人工恢复会话。

## GitHub安全

不要提交：
- API Key
- .env
- Cookie
- browser_data
- 原始舆情数据
- 登录信息

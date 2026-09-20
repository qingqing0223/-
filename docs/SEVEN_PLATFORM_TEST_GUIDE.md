# 七平台联调测试说明（Windows）

本轮目标是把 项目当前接入的 7 个平台逐个平台验证到同一条链路：

`平台关键词搜索 → JSONL → 标准化 → 增量去重 → 志鹏 v2 → 苏琦 /api/ingest → 大屏`

平台代码：

- `xhs` 小红书
- `dy` 抖音
- `ks` 快手
- `bili` B站
- `wb` 微博
- `toutiao` 今日头条
- `zhihu` 知乎

## 每位同学先做一次环境更新

```powershell
cd E:\realtime-opinion-monitor
git pull --ff-only
python .\scripts\preflight.py
python -m unittest tests.test_platform_normalizer
```

`preflight.py` 会检查本地 MediaCrawler 原生平台与项目今日头条适配器是否就绪、配置文件是否包含 7 个平台，以及核心模块能否导入。

## 启动大屏后端

如大屏后端尚未启动：

```powershell
cd E:\Real-time-situation-map\yuqing-v1\03_live_system
python server.py --no-sim
```

保持该窗口运行。

## 每位同学只测试自己负责的平台

回到集成仓库：

```powershell
cd E:\realtime-opinion-monitor
.\scripts\test_platform_single_cycle_windows.ps1 -Platform bili
```

把 `bili` 替换成自己负责的平台代码即可。

建议分工：

| 平台 | 代码 |
|---|---|
| 小红书 | xhs |
| 抖音 | dy |
| 快手 | ks |
| B站 | bili |
| 微博 | wb |
| 今日头条 | toutiao |
| 知乎 | zhihu |

## 一轮测试需要回传的结果

请截图或复制脚本最后的 `Test summary`，至少包含：

- `crawler_status`
- `crawler_state`
- `return_code`
- `duration_seconds`
- `new_records`
- `classified_records`
- `dashboard_ok`
- `dashboard_sent`
- `dashboard_inserted`
- `dashboard_skipped`
- `outbox_after`

同时打开 `http://127.0.0.1:8765/`，确认对应平台数据是否进入大屏。

## 结果判定

### 通过

通常应看到：

```text
crawler_status = ok
crawler_state = SUCCESS
dashboard_ok = True
outbox_after = 0
```

若 `classified_records > 0` 且 `dashboard_inserted > 0`，说明该轮有真实新增内容进入分类和大屏。

### 没有新增数据

如果搜索成功但 `classified_records = 0`，不一定是故障，可能是关键词当轮没有新命中，或命中内容已被跨轮去重。可以换一个公开、热度较高但无敏感操作需求的测试关键词再跑一次。

### 登录/验证

若状态为：

```text
VERIFY_REQUIRED
LOGIN_REQUIRED
```

停止自动重试，按平台官方页面完成人工登录/验证后，再执行一次测试。不要通过代码绕过验证码或安全验证。

### 网络/其他错误

若状态为：

```text
NETWORK_ERROR
CRAWLER_FAILED
RUNNER_ERROR
```

请同时发送：

- `Test summary`
- 该轮 `stdout.log`
- 该轮 `stderr.log`

由集成端继续针对平台适配。

## 当前验收状态

截至代码扩展完成时：

- 抖音：已有端到端成功记录
- 快手：已有端到端成功记录
- 小红书：曾端到端成功，当前仍可能遇人工验证
- 微博：已有适配基础，登录/验证链仍需继续验收
- B站：已接入统一代码链，待本轮真实平台测试
- 今日头条：已接入统一代码链，待本轮真实平台测试
- 知乎：已接入统一代码链，待本轮真实平台测试

代码接入完成不等于平台已实际验收通过；正式部署前以本轮真实测试结果为准。

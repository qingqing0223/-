# 微信公众号 TechDesign V3 采集与验收

当前批次切换为2026-09-21，见 [今日任务说明](WECHAT_MP_2026-09-21.md)。候选核验规则已更新：表1保留时间合格的全部实际搜索候选，区分是/否/待核验；表3/5仍按明确有效文章统计。下文旧“仅有效记录进入正式五表”的描述不再适用于表1。

此链路只生成采集组表1—表5，不调用模型、不进行舆情态度分类，也不自动发布到 GitHub 或旧大屏。

## 运行

在仓库根目录使用 Python 3.10+、Chrome、Node.js 和 `@oai/artifact-tool`。
Python 依赖见 `requirements-wechat-mp.txt`。本机已创建 `.venv`。
只安装公众号链依赖时，可运行 `scripts/setup_wechat_windows.ps1 -Platform wechat_mp`。
Excel 导出优先使用 Codex 内置 Node.js 和 artifact-tool；其他机器可配置
`wechat_mp_node_executable` 和 `wechat_mp_artifact_module`（模块入口 file URL），
或在 Node.js 可解析的依赖目录安装 `@oai/artifact-tool`。

```powershell
.\.venv\Scripts\python.exe run_wechat_platform.py --platform wechat_mp --config config/monitoring.wechat.windows.json --once
.\.venv\Scripts\python.exe scripts/verify_wechat_mp_final.py --config config/monitoring.wechat.windows.json
```

去掉 `--once` 可持续运行。也可运行：

```powershell
.\scripts\start_wechat_platform_windows.ps1 -Platform wechat_mp -NodeId wechatmp01 -Config .\config\monitoring.wechat.windows.json -Once
```

公众号模式拒绝 `-PushGithub`。公众号启动、升级脚本不会调用 Git，不要求 API Key。
视频号仍使用原有逻辑；安装脚本不带平台参数时仍保留原有安装行为。

## 数据与口径

- 正式开始：2026-09-16 00:00:00 +08:00。六个正式关键词逐一搜索，翻页至自然终点或明确记录异常/上限。
- `data/wechat_mp/state_v3.json` 为新版本持久化状态；不自动导入旧分类结果，避免已错误填0或错误发布时间的数据污染。
- `data/wechat_mp/raw_runs` 保留逐轮公开卡片数据，`excluded_records.jsonl` 保留无效/待核验记录及原因；早于起点、时间缺失、未来时间、主题证据不足均不进入正式五表。
- 主题判断仅使用公开标题/摘要，不把搜索词当主题证据。摘要不足时宁可待核验。首个宣传周需结合2026发布时间；其他主题/倡议/石榴花开需明确本次活动上下文。
- 正文列是搜索结果摘要，不代表全文。可靠发布时间优先卡片公开 `timeConvert(epoch)`，其次专用时间区文本，不从正文提取日期。
- ID 优先真实公众号 canonical URL（剔除追踪参数）。公开跳转无法解析时，以规范化标题+帐号生成回退标识；可靠绝对日期可区分重发。相对时间不会参与 ID。
- 同标题同帐号且没有稳定URL/可靠日期时可能无法区分不同重发；`identity_method` 标明回退，不能声称绝对无碰撞。
- `matched_keywords` 跨关键词、跨轮次合并。重启保留首次 ID 与首次采集时间，另存最后观察时间。
- 重点帐号在 `config/key_accounts.wechat_mp.json`；仅 Unicode/空白规范化后精确匹配，不删除“日报”等后缀，不做模糊包含匹配。
- 表2、表4为空表，表3未知指标留空；表5的相关发文量是本节点采集到的有效文章数，并非全平台总量。
- 表5汇总仅在该帐号所有已采集文章有该指标时求和，否则为空。总互动量需要全部互动分项均已知。
- 帐号ID、主页、粉丝、关注、所属机构、原创/转载、IP属地没有公开证据时均为空，不从帐号名称猜测。
- 提交目录为 `data_submissions/wechat_mp/YYYY-MM-DD_wechatmp01`。CSV没有数据类型，Excel使用配套XLSX，或将CSV的ID列指定为文本导入。

## 三个独立时钟

- `wechat_mp_interval_seconds`：底层搜索周期（默认300秒）。一轮未结束时不会重叠启动；耗时较长时下一轮在结束后开始。
- `wechat_mp_content_export_seconds`：表1/2输出周期（默认900秒）。
- `wechat_mp_interaction_export_seconds`：表3/4/5输出周期（默认3600秒）。

输出时钟在主循环中独立运行，读取最近完成的搜索轮次；首次有结果立即全部导出。
工作簿显示两组表各自输出时间。表3统计时间为实际观察时间，不用导出时间伪装为新观测。
两组表按各自周期更新，短暂行数差异是允许的；`--once` 或重新导出可生成同一批全表快照。
每天的提交目录保存累计有效记录，不只保存当天新发现记录。

```powershell
.\.venv\Scripts\python.exe scripts/export_wechat_mp_v3.py --config config/monitoring.wechat.windows.json
```

## 验证与隐私

验证码只等待人工完成；超时停止并保留已经获得的数据。网络失败记录关键词与异常类型，其他关键词继续，持续运行时下一轮重试。
`SUCCESS` 表示所有关键词到达自然终点；上限、重复页、空DOM异常或网络错误记录为 `PARTIAL`，不冒充搜索完成。
逐条解析隔离异常。工作目录和浏览器 profile 被 Git 忽略；不要提交登录态、Cookie、密钥、真实网络IP。
调试HTML只保留公开卡片来源区，移除链接等属性。提交目录不包含浏览器文件。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_wechat_mp_v3.py -q
```

验收脚本实际读取 JSONL、CSV、XLSX，检查有效性、去重、关键词、列顺序、文本ID、空值和评论空表。

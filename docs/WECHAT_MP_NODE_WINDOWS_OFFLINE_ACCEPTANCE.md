# 微信公众号节点：Windows 离线验收与持续运行（2026-09-23）

本说明只涉及 `wechat_mp`。先备份原开发副本，尤其是 `data_submissions/wechat_mp/2026-09-21_wechatmp02`。修复版 ZIP 保留整个项目代码与必需模块，但**不包含任何原运行目录、浏览器资料、Cookie、API Key 或其他平台的运行数据**，以免解压覆盖已有记录。ZIP 的 `acceptance_data/2026-09-21_wechatmp02/search_contents.jsonl` 是原始历史 JSONL 的逐字节副本，用于原始批次不在本地时离线验收，不是新采集数据。

## 1. 更新开发副本及准备环境

以下 PowerShell 在已下载 ZIP 的前提下运行；将 `$zip` 改成自己的实际下载路径。

```powershell
$root = 'D:\Deployment\qingqing0223\wechat-mp-v3'
$zip = "$env:USERPROFILE\Downloads\wechat_mp_v3_repaired_2026-09-23.zip"
$stage = Join-Path $env:TEMP 'wechat_mp_repair_stage'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
# 单独备份历史批次；有其他运行状态时也建议复制保留。
$history = Join-Path $root 'data_submissions\wechat_mp\2026-09-21_wechatmp02'
if (Test-Path $history) {
    Copy-Item $history "$history.backup-before-repair" -Recurse -Force
}
Expand-Archive -LiteralPath $zip -DestinationPath $stage
# ZIP 仅包含源代码/配置、非敏感示例及单独验收材料，不包含任何正式运行数据目录。
Get-ChildItem -LiteralPath $stage -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $root -Recurse -Force
}
Set-Location $root
if (-not (Test-Path '.\.venv\Scripts\python.exe')) { py -3.11 -m venv .venv }
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
& $python -m pip install playwright pytest openpyxl
```

离线导入及 HTTP 服务不依赖浏览器、付费接口或 `artifact_tool`。正常联网发现需要本机已经装好的 Chrome（配置使用 `chrome` channel）及 Playwright。已有运行环境通常无需再安装浏览器。旧版 V3 工作簿导出优先调用原 Node `@oai/artifact-tool` 脚本；如果它未安装，新增的可选 Python `artifact_tool` 后备脚本可工作。需要工作簿导出时可在现有环境中安装对应依赖；缺少依赖**不会阻止前端基础 JSON 导出**。

## 2. 离线导入历史，不打开浏览器

```powershell
Set-Location 'D:\Deployment\qingqing0223\wechat-mp-v3'
$python = '.\.venv\Scripts\python.exe'
& $python scripts/run_wechat_mp_node.py --prepare-history
& $python scripts/run_wechat_mp_node.py --prepare-history  # 验证重复导入不会重复增加记录
```

默认先读取 `data_submissions/wechat_mp/2026-09-21_wechatmp02/search_contents.jsonl`；仅在它不存在时回退到 ZIP 内的 `acceptance_data` 原样副本。历史始终标记为 `2026-09-21_wechatmp02`，不会被标记成今日新发现。输出保存在独立的 `data/wechat_mp/2026-09-23_wechatmp03/node_state.json` 和 `data_submissions/wechat_mp/2026-09-23_wechatmp03/frontend/`，不覆盖 9 月 21 日批次。

## 3. 启动无需爬虫、持续运行的 HTTP 服务

在**一个独立 PowerShell 窗口**执行：

```powershell
Set-Location 'D:\Deployment\qingqing0223\wechat-mp-v3'
.\.venv\Scripts\python.exe scripts/run_wechat_mp_node.py --serve-only
```

进程一直提供已有 `latest.json`，不触发历史导入、不打开 Chrome、不调用搜索/付费接口。用 **Ctrl+C** 停止；重新执行同一条命令即可重启。如果只想一条命令离线导入并保持 HTTP 存活，也可以用 `--prepare-history --serve`。注意只有一个进程可以占用 8765 端口。

## 4. 本机 HTTP 验收与更新时间

另开 PowerShell 窗口运行：

```powershell
$base = 'http://127.0.0.1:8765'
$health = Invoke-RestMethod "$base/health"
$health | ConvertTo-Json -Depth 8
$latest = Invoke-RestMethod "$base/latest.json"
$latest.metadata.cumulative
$latest.metadata.history
$latest.metadata.new_discoveries_today
$latest.metadata.collection
1..5 | ForEach-Object {
    $n = $_
    $rows = @(Invoke-RestMethod "$base/table$n.json")
    "table$n : $($rows.Count) rows"
}
"JSON exported at: $($latest.metadata.exported_at)"
"Newest actual observation: $($latest.metadata.last_observation_at)"
"Actual fresh source evidence: $($latest.metadata.collection.last_live_evidence_at)"
"Schema conflicts: $($latest.metadata.schema_conflict_count)"
```

预期仅导入已提供历史时：16 条候选、15 条有效、1 条待核验；五表 16/0/15/0/15；`new_discoveries_today=0`；`collection.status=NO_LIVE_EVIDENCE`。**`exported_at` 是快照生成时间，绝不能当成新采集时间。** `/latest.json` 包含同一代的五表、原始记录、缺失字段、来源状态、隔离记录和 POMS 传输视图；五个独立 HTTP 表接口每次均读取当时同一份完整最新快照。

## 5. 正常持续监测、异常暂停、停止和重启

若前面 `--serve-only` 进程已在运行，保持它不动，在**另一个窗口**执行：

```powershell
Set-Location 'D:\Deployment\qingqing0223\wechat-mp-v3'
.\.venv\Scripts\python.exe scripts/run_wechat_mp_node.py
```

默认仅启用搜狗和 Bing；Google 验证路径关闭，详情队列关闭；搜狗/Bing 每 900 秒计划一轮，前端快照最多每 60 秒定时导出一次（接到新候选后立即刷新）。V3 工作簿沿用表1/2每 900 秒、表3/4/5每 3600 秒的导出间隔；它是独立的可选任务，发生依赖错误也不阻塞前端 JSON。任一来源验证码出现时仅暂停该来源，不循环绕过验证。可以人工处理后执行：

```powershell
# 先 Ctrl+C 停止旧采集进程，然后根据实际情况明确恢复来源：
.\.venv\Scripts\python.exe scripts/run_wechat_mp_node.py --resume-source sogou
# 或： --resume-source bing
# 如之后在 JSON 配置显式启用 google，可用： --resume-source google
# 详情队列经人工确认后再启用：--resume-source details
```

**不可同时运行两个采集进程**写入同一工作目录；`--serve-only` 只是静态只读服务，可以与一个采集进程并行。Ctrl+C 停止后保留候选、来源检查点和详情队列；原命令再次执行会按持久化状态恢复。`--once` 适合临时单轮检查，但并不意味着实时源已验收通过。本交付没有执行联网真实性验收。

## 6. 本地快照和 POMS/学校后端对接

- 本地数据源：`GET /latest.json` 可一次获得原始基础数据及五张表；`GET /table1.json`～`/table5.json` 便于现有前端直接对接；`/health` 返回输出时间、来源状态与真实最新观察时间。原始 `null` 就是未知。调用方应根据 `history_batch`、`first_discovered_at`、`publish_time`、`metadata.collection` 区分历史、今天、真实新采集和刷新快照。
- POMS 传输文件：`frontend/table1_batch.json`～`table5_batch.json`，以及 `latest.json` 中的 `poms_tables`。根据 `docs/批量输入输出接口指南.md`，学校后端批量接口为 `POST /api/v1/tables/<英文表名>/batch`（表1 `published_content_basic_information`、表2 `comment_basic_information`、表3 `published_content_interaction_data`、表4 `comment_content_interaction_data`、表5 `account_information`）；需后端提供并批准的 `X-API-Key`，先表1再表2—表5。**本节点只产生文件，绝不自动上传。**
- 与 POMS 传输限制：其强制数字字段对未获取指标可能使用零占位，待核验也可能序列化为布尔 `false`。这些都是**协议占位，不是实际观测、否定审核结论或统计结果**；转换详情保存于 `latest.json.metadata.poms_placeholders` 和原始五表，双方应单独传递/保留该元数据。POMS 表级校验失败的单条记录被隔离并写 `schema_conflicts.json`，不会阻断其它记录；正式上传前应审阅冲突和字段语义。
- `127.0.0.1` 仅本机可见，另一台机器无法访问。跨机器大屏必须由学校后端做经认证的数据接入或提供安全内网代理；**不要通过 `0.0.0.0` 或端口映射将这个未认证服务暴露公网**。

## 7. 回归测试及跨日期配置

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_wechat_mp_node.py tests/test_wechat_mp_frontend.py tests/test_wechat_mp_web_discovery.py tests/test_wechat_mp_v3.py tests/test_wechat_mp_poms.py tests/test_wechat_mp_display.py tests/test_wechat_mp_daily_batch.py
```

这些测试使用临时文件或模拟浏览器，不应启动真实联网抓取。部分历史 V3 工作簿测试还需要 Node `@oai/artifact-tool` 或 Python `artifact_tool`。当前配置的 `current_period_start`、`wechat_mp_submission_date`、`wechat_mp_node_id` 及对应工作/前端目录**固定为 2026‑09‑23 批次**；转入 9 月 24 日或其它日期之前必须一起修改这些值，不能把前一天的历史当成今天的新数据，亦不可指向原 9 月 21 日批次输出目录。

# 民族网络舆情动态态势感知系统（第二阶段 · 实时版）

在第一阶段静态大屏（`01_code_docs/dashboard`）的基础上，新增统一数据层和实时链路：

```
微博/抖音/快手/微信等平台
        ↓ 采集器（collectors/）
统一服务器（server.py，HTTP + SSE + SQLite）
        ↓ 相关性判断 → 字段归一化 → 入库
后台实时重算（stats.py：平台/地区/省级/语言/态度/趋势/高热）
        ↓ SSE 推送
大屏前端实时刷新（右侧实时舆情流 + 全屏统计联动）
```

历史 Excel 数据（第一阶段）作为基线一次性迁入 SQLite；新采集的数据以“实时增量”叠加在基线上，所有统计图同步更新。

## 快速开始

```bash
cd yuqing-v1/03_live_system
./start.sh            # 启动服务，默认 http://127.0.0.1:8765
```

浏览器打开 http://127.0.0.1:8765/ 即可看到实时版大屏。

### Windows 普通 PowerShell 快捷启动

在普通 Windows PowerShell 中执行：

```powershell
cd "项目目录\yuqing-v1\03_live_system"
.\start_live_dashboard.ps1
```

脚本会自动开启真实平台采集、关闭模拟数据和文件监听，启动服务后打开
`http://127.0.0.1:8765/`。如果 PowerShell 禁止执行本地脚本，可只对当前窗口放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start_live_dashboard.ps1
```

需要换端口时使用 `.\start_live_dashboard.ps1 -Port 9000`，不自动打开浏览器时使用
`.\start_live_dashboard.ps1 -NoBrowser`。

如果系统自带 Python 不可用（例如缺少 Xcode Command Line Tools），`start.sh` 会自动切换到 Codex 自带运行时。

### 每日态势报告下载

大屏右上角的“下载最新态势报告”支持按日期生成和下载 Word/PDF。该功能仅读取仓库根目录下的 `results/YYYY-MM-DD/nodes/`，与大屏 SQLite 数据解耦，不会触发采集或分析任务。

```bash
python -m pip install -r requirements-report.txt
export DASHSCOPE_API_KEY="你的 DashScope API Key"
./start.sh
```

报告默认按日期保存在 `data/generated_reports/YYYY-MM-DD/`。当源数据、Prompt、分类口径或模板未变化时，后续下载直接使用缓存；源文件变化后才会重新生成。当天默认显示“数据仍在统计和分析中”，历史日期可正常生成。详细说明见 `reporting/README.md`。

## 统一大屏：一套页面、两种模式

大屏页面统一维护在 `web/` 目录，不再区分静态版/动态版两套页面：

- **动态模式（默认）**：`start.sh` 启动后，页面通过 `/api/bootstrap` 读取合并数据，并通过 SSE（`/api/events`）秒级刷新；
- **静态模式**：没有服务器时，页面自动回退读取 `web/assets/data.js`（GitHub Pages 部署的就是这套页面，可直接打开网址查看），详情页同样会回退到本地 `data.js`；
- **自动刷新**：`web/大屏自动刷新.html` 每 300 秒重新加载一次大屏，适合大屏长期展示。

更新静态数据：运行 `run_pipeline.sh`（或 `build_data.py --atomic`），会重新生成 `web/assets/data.js` 和 `web/assets/china.js`；推送 `main` 后 GitHub Pages 自动重新部署。

### 预热阶段口径（2026 民族团结进步宣传周）

`phase.json` 设定大屏只统计 `stats_start`（默认 `2026-09-16T00:00:00`）之后**实际入库**的数据，第一阶段历史基线与之前的测试数据保留在库中但不参与展示；顶部 KPI、右上 9 个平台独立分布、固定 10 个重点地区、按小时趋势、重点账号面板都取自同一批入库记录。

重点账号（creator）数据接口：`POST /api/key-accounts/ingest`（写入）、`GET /api/key-accounts`（读取）。详见 `docs/预热阶段大屏口径说明.md`。

## collect.py 统一采集入口

采集器统一由 `collect.py` 调度，输出统一为“舆情事实表”24 个字段的 JSON，放入 `inbox/`：

```bash
python collect.py                  # 运行全部已启用采集器（模拟器 + 文件导入）
python collect.py weibo kuaishou   # 只运行指定采集器
python collect.py --demo           # 用六个平台的内置示例数据演示 24 字段输出（写入 demo_output/）
python collect.py --demo weibo     # 只演示微博
python collect.py --output /tmp/x  # 指定输出目录
python collect.py --dry-run        # 只打印不写文件
```

输出文件示例（`collect_weibo_20260814_192820.json`）：

```json
{
  "collector": "weibo",
  "collectorLabel": "微博/热榜",
  "mode": "demo",
  "collectedAt": "2026-08-14T19:28:20",
  "recordCount": 2,
  "records": [
    {
      "唯一编号": "weibo-6cb9221fc61ffc75",
      "采集时间": "2026-08-14T19:28:20",
      "发布时间": "2026-08-14T09:47:00",
      "平台": "微博",
      "平台组": "微博/热榜",
      "具体来源": "微博搜索·民族团结法",
      "账号": "@示例用户A",
      "正文": "支持民族团结进步促进法，各民族要像石榴籽一样紧紧抱在一起。",
      "原始链接": "https://weibo.com/demo/0001",
      "地区": "四川",
      "地区组": "四川、甘肃民族地区",
      "省份": "四川",
      "城市": "成都",
      "IP属地": "四川",
      "语言": "中文",
      "是否少数民族语言": "否",
      "总体态度": "支持认可",
      "具体问题类别": "-",
      "点赞量": 328,
      "评论量": 56,
      "转发量": 12,
      "是否重点": "否",
      "是否计入统计": "是",
      "备注": "collect.py --demo 示例记录（编造）"
    }
  ]
}
```

真实渠道接入时，只需要在对应采集器（`collectors/weibo.py` 等）的 `collect()` 里返回同样结构的原始记录（字段可用中文别名），`collect.py` 会自动归一化、生成唯一编号并写入 `inbox/`。

## clean_and_append.py 清洗入事实表

把 `inbox/` 里的原始记录去重后追加进原子化工作簿的「舆情事实表」，缺必填字段的记录自动写入「待清洗区」：

```bash
python clean_and_append.py --xlsx "路径/Excel数据库改造示例.xlsx"
python clean_and_append.py                        # 自动查找原子化工作簿
ATOMIC_XLSX="路径/库.xlsx" python clean_and_append.py
python clean_and_append.py --inbox /tmp/inbox --dry-run   # 只统计不写入
python clean_and_append.py --no-move                      # 处理完不移动 inbox 文件
python clean_and_append.py --backup                       # 覆盖前先备份工作簿
```

去重规则：以「舆情事实表」已有唯一编号为准；同批文件内重复也会跳过。处理成功的文件会归档到 `inbox/processed/`。

完整流水线：

```bash
python collect.py                                   # ① 采集 → inbox/
python clean_and_append.py --xlsx "路径/库.xlsx"    # ② 清洗去重 → 舆情事实表
python 01_code_docs/scripts/build_data.py --atomic "路径/库.xlsx"   # ③ 重算 data.js
```

`build_data.py` 写 `data.js` 时已使用“临时文件 + 原子替换”，大屏不会读到写了一半的文件。

## 历史 Excel 全量导入（02_data → 舆情事实表）

如需把 `yuqing-v1/02_data/` 下各文件的有效舆情明细/扁平化数据/公众评论明细/非支持原话
全量导入原子化工作簿（默认先清空旧事实表）：

```bash
python import_history_to_fact.py --xlsx "路径/Excel数据库改造示例.xlsx" --dry-run   # 先看统计
python import_history_to_fact.py --xlsx "路径/Excel数据库改造示例.xlsx" --backup     # 正式导入
```

导入后仍需执行 `build_data.py --atomic` 重算大屏数据。

## 真实渠道：B站 / 微博 / 抖音 / 微信公众号 / 百度知道 / 豆瓣 / 省市政务与媒体网站（已实现）；知乎 / 快手 / 小红书待接入；Reddit 默认关闭

**B站**：已实现并实测通过——使用公开搜索接口（无需登录），自动获取指纹 cookie（buvid3/buvid4），带 412/429 风控重试；默认每个视频补充点赞/评论/转发。

```bash
python collect.py bilibili          # 手动采集 B站
LIVE_SEARCH_KEYWORDS="民族团结进步促进法,民族歧视" python collect.py bilibili
```

**Reddit**：已实现但**默认关闭**（当前监控以国内平台为主，微博热榜 + B站 + 文件导出已够用）。
如后续需要海外舆情，按下面步骤申请密钥并把 `collectors/reddit.py` 里 `enabled` 改为 `True`，
其余代码无需改动。未开启时定时流水线不会请求 Reddit。

```bash
export REDDIT_CLIENT_ID="你的client_id"
export REDDIT_CLIENT_SECRET="你的client_secret"
python collect.py reddit
```

常用环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| LIVE_SEARCH_KEYWORDS | 民族团结进步促进法,民族团结,民族歧视,促进法 民族 | 搜索关键词（逗号分隔） |
| LIVE_MAX_RESULTS | 10 | 每个关键词最多取几条 |
| LIVE_REQUEST_INTERVAL | 2 | 请求间隔（秒，防风控） |
| LIVE_BILIBILI_ENRICH | 1 | B站是否补充点赞/评论/转发 |
| REDDIT_CLIENT_ID / SECRET | 空 | Reddit 官方 API 密钥 |
| REDDIT_USER_AGENT | yuqing-monitor/1.0 | Reddit 要求的 UA |
| WEIBO_MODE | auto | 微博模式：hot / export / openapi / mobile / auto |
| WEIBO_HOT_KEYWORDS | 民族团结,民族,促进法... | 微博热榜保留话题关键词 |
| WEIBO_HOT_COUNTED | 是 | 热榜话题是否计入统计 |
| WEIBO_HOT_AS_LIKES | 1 | 热度值是否近似填入点赞量（进入高热内容） |
| WEIBO_EXPORT_DIR | data/weibo_exports/ | 第三方导出文件目录 |
| WEIBO_APP_KEY / SECRET / ACCESS_TOKEN | 空 | 微博开放平台 API（可选） |
| WEIBO_COOKIE | 空 | 微博移动端搜索 Cookie（可选，实验） |
| DOUYIN_HOT_KEYWORDS | 民族团结,民族,... | 抖音热榜保留话题关键词 |
| DOUYIN_HOT_COUNTED | 是 | 抖音热榜话题是否计入统计 |
| DOUYIN_HOT_AS_LIKES | 1 | 抖音热度值近似填入点赞量 |
| WECHAT_SOGOU_PAGES | 1 | 搜狗微信搜索页数 |
| WECHAT_SOGOU_INTERVAL | 5 | 搜狗关键词间休息秒数 |
| BAIDU_ZHIDAO_PAGES | 1 | 百度知道搜索页数 |
| BAIDU_ZHIDAO_INTERVAL | 5 | 百度知道关键词间休息秒数 |
| DOUBAN_GROUP_PAGES | 1 | 豆瓣小组讨论搜索页数 |
| DOUBAN_GROUP_INTERVAL | 5 | 豆瓣关键词间休息秒数 |
| LIVE_SITE_NEWS_ENABLED | 1 | 是否启用省市政务/媒体网站采集器 |
| LIVE_SITE_NEWS_MAX_SITES | 15 | 每轮最多采集几个网站（0=全部） |
| LIVE_SITE_NEWS_MAX_ITEMS | 10 | 每个网站最多保留几条命中记录 |
| LIVE_SITE_NEWS_SOURCES | 空 | 逗号分隔过滤：省份/站点名/类别 |
| LIVE_SITE_NEWS_SOURCES_JSON | site_sources.json | 网站源配置路径 |

采集到的真实记录同样走 `clean_and_append.py` 入库、`build_data.py --atomic` 重算；`总体态度` 默认标“待核实”，后续接入模型或人工复核后改为正式态度。

### 点亮 Reddit：申请密钥与验证

1. 登录 Reddit，打开 [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)；
2. 点击 “are you a developer? create an app”；
3. 名称填 `yuqing-monitor`，类型选 **script**，redirect uri 填 `http://localhost:8080`（必填项，脚本类型实际用不到）；
4. 提交后页面显示两行密钥：第一行是 client_id，第二行是 client_secret；
5. 复制 `.env.example` 为 `.env` 并填入两行密钥，把 `REDDIT_USER_AGENT` 里的占位换成你的 Reddit 用户名；
6. 验证：

```bash
python collect.py --check reddit
# 看到 “OAuth token 获取成功” 即点亮成功
```

7. 试采：

```bash
python collect.py reddit --dry-run    # 只看结果不写文件
python collect.py reddit              # 正式采集，写入 inbox/
```

常见问题：

- `401 Unauthorized`：client_id / secret 复制错误，重新检查 `.env`；
- `403 Blocked`：当前网络 IP 被 Reddit 拦截，换住宅网络或代理后重试；
- token 过期：采集器每次启动会自动重新获取，无需手工处理。

**微博**：已实现三个通道，默认 `WEIBO_MODE=auto` 即可使用：

1. **热榜公开接口（无需登录，实测可用）**：每次采集抓取微博实时热榜，只保留命中
   `WEIBO_HOT_KEYWORDS`（默认：民族团结 / 民族 / 促进法 / 少数民族 / 民族地区 / 歧视）的话题。
   每个话题按“一条舆情”入库，热度值默认近似填入点赞量（`WEIBO_HOT_AS_LIKES=1`），
   这样话题会出现在大屏“高热内容”里，备注中写明是热度值而非点赞量。

```bash
python collect.py weibo            # 采集热榜（+导出文件）
python collect.py --check weibo    # 自检：接口是否可达、命中几条
```

2. **第三方导出文件（准实时 / 每天）**：从第三方微博工具、微博采集器或人工整理导出的
   `csv / json / jsonl` 文件，丢进 `data/weibo_exports/`，`collect.py weibo` 会自动读取、
   按统一 24 字段转换、写入 `inbox/`，处理完的文件归档到 `data/weibo_exports/processed/`。

```bash
mkdir -p data/weibo_exports
# 把 weibo_export.csv / weibo_export.json 放进 data/weibo_exports/
python collect.py weibo
```

导出文件列名兼容常见写法（微博正文 / 发布人 / 点赞数 / 评论数 / 转发数 / 发布时间 / 链接 /
IP属地 / 态度 等），模板见 `docs/统一数据字段.md`。

3. **开放平台 API（可选，一般需企业资质）**：在微博开放平台创建应用后，把
   `WEIBO_APP_KEY / WEIBO_APP_SECRET`（或直接填 `WEIBO_ACCESS_TOKEN`）写入 `.env`；
   搜索接口通常还需要申请高级权限。配置后 `auto` 模式会自动叠加官方 API 采集。

4. **移动端搜索（实验，可选）**：登录 m.weibo.cn 后复制 Cookie 填入 `WEIBO_COOKIE` 即可
   启用关键词搜索采集；有风控/封号风险，建议低频使用。

**抖音**：已接入热榜公开接口（无需登录，实测可用）。每次采集抓取抖音实时热榜，只保留命中
`DOUYIN_HOT_KEYWORDS`（默认：民族团结 / 民族 / 促进法 / 少数民族 / 民族地区 / 歧视）的话题；
热度值默认近似填入点赞量（`DOUYIN_HOT_AS_LIKES=1`），话题会进入大屏“高热内容”，备注中写明是热度值。
关键词搜索接口实测返回“请先登录，再继续搜索吧”，暂未接入。

```bash
python collect.py douyin            # 采集抖音热榜
python collect.py --check douyin    # 自检
```

**微信公众号**：已接入搜狗微信文章搜索（无需登录，实测可用）。按 `LIVE_SEARCH_KEYWORDS`
搜索公众号文章，获取标题、公众号名、发布时间、摘要、跳转链接；搜狗有验证码风控，
所以采集间隔默认 10 分钟一次、关键词之间休息 5 秒（`WECHAT_SOGOU_INTERVAL` 可调）。
视频号暂无公开接口，仍走人工/第三方导出。

```bash
python collect.py wechat            # 采集公众号文章
python collect.py --check wechat    # 自检
```

**百度知道**：已接入搜索公开页（无需登录，实测可用）。按 `LIVE_SEARCH_KEYWORDS` 搜索问答，
每条结果取问题标题、最佳回答摘要、回答日期、回答者、回答数；无点赞/评论/转发字段，
互动量记 0、回答数写入备注。百度知道有验证码风控，默认 10 分钟一次。

```bash
python collect.py baidu_zhidao            # 采集百度知道
python collect.py --check baidu_zhidao    # 自检
```

**豆瓣**：已接入小组讨论搜索公开页（无需登录，实测可用）。按 `LIVE_SEARCH_KEYWORDS` 搜索，
每条结果取帖子标题、话题链接、发布时间、回复数、所属小组；列表页没有正文/作者，
正文暂用标题，回复数如实填入“评论量”。默认 10 分钟一次。

```bash
python collect.py douban            # 采集豆瓣小组讨论
python collect.py --check douban    # 自检
```

**省市政务/媒体网站**：已接入通用 HTML 标题级采集——覆盖省政府门户、省民宗委、省级主流媒体、
网信办/举报平台、自治州/自治县政府门户。站点清单由《各地区监测网站汇总表》核验生成，存在
`site_sources.json`；连通性核验为 HTTP 200 的站点默认启用，403/412/超时站点保留但 `enabled=false`。

```bash
python collect.py site_news                        # 采集全部已启用站点（默认每轮最多 15 个）
LIVE_SITE_NEWS_SOURCES=河北,山西 python collect.py site_news   # 只采集指定省份/站点
LIVE_SITE_NEWS_MAX_SITES=0 python collect.py site_news         # 不限站点数
```

当前为“标题级”采集：命中 `LIVE_SEARCH_KEYWORDS` 的新闻标题转成 24 字段记录入库；
正文、评论、态度字段后续再加详情页模板扩展。

**小红书**：已实测，搜索页 SSR 不含结果、搜索 API 返回 404、探索页虽可无登录读取
推荐笔记但无法按关键词检索（实测命中 0 条）；暂走人工/第三方导出（`inbox/`）。

**知乎**：已实测，热榜 API 返回 401、搜索 API 返回 400、网页 403、公开 RSS 超时，
暂无法无登录接入；如后续需要，可评估浏览器 Cookie 方案或走人工导出（`inbox/`）。

**快手**：已实测，网页热榜 GraphQL 接口需要登录态/签名（直接请求返回 400），
暂无法无登录接入；先用 `inbox/` 第三方导出/人工补充，后续再专项评估。

## 定时任务：一键流水线（run_pipeline.sh / run_pipeline.bat）

`run_pipeline.sh`（macOS/Linux）和 `run_pipeline.bat`（Windows）把上面三步串成一条命令，自带防重入锁和日志：

```bash
./run_pipeline.sh "路径/Excel数据库改造示例.xlsx"
# 或 ATOMIC_XLSX=路径 ./run_pipeline.sh
# 日志写入 logs/pipeline.log；默认输出到 dashboard/assets/data.js
```

## macOS launchd（每 5 分钟）

已提供模板：[launchd/com.yuqing.pipeline.plist](launchd/com.yuqing.pipeline.plist)（改好 `ATOMIC_XLSX` 和脚本绝对路径后）：

```bash
cp launchd/com.yuqing.pipeline.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.yuqing.pipeline.plist
launchctl kickstart gui/$(id -u)/com.yuqing.pipeline   # 立即执行一次
tail -f logs/pipeline.log                              # 查看日志
launchctl bootout gui/$(id -u)/com.yuqing.pipeline     # 停用
```

## Windows 计划任务（每 5 分钟）

```bat
schtasks /Create /TN "YuqingLivePipeline" /TR "\"D:\态势图\yuqing-v1\03_live_system\run_pipeline.bat\"" /SC MINUTE /MO 5 /F
```

或 PowerShell：

```powershell
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument '/c "D:\态势图\yuqing-v1\03_live_system\run_pipeline.bat"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)
Register-ScheduledTask -TaskName "YuqingLivePipeline" -Action $action -Trigger $trigger -Force
```

## 真正实时：SSE 秒级推送（可选）

上面是“静态大屏 5 分钟准实时”（Excel → data.js → 页面 300 秒刷新）。如果要多一位数的“实时动态”，
项目自带实时服务端 [server.py](server.py)：采集到新数据后**立即写入 SQLite 并通过 SSE 推送给页面**，
新舆情会实时滚入右侧列表、统计同步刷新。

一键启用（会按各采集器自身频率自动调度真实平台）：

```bash
LIVE_PLATFORM_ENABLED=1 ./start.sh
# 微博/抖音/B站：每 5 分钟；公众号/百度知道/豆瓣：每 10 分钟
# 打开 http://127.0.0.1:8765/ 即可看到 SSE 实时版大屏
```

各平台能做到的“最新鲜度”：

| 平台 | 采集频率 | 平台自身更新速度 | 实际体验 |
| --- | --- | --- | --- |
| 微博热榜 | 5 分钟 | 榜单分钟级变化 | 接近实时 |
| 抖音热榜 | 5 分钟 | 榜单分钟级变化 | 接近实时 |
| B站搜索 | 5 分钟 | 新视频发布后即可被搜到 | 准实时（5 分钟） |
| 微信公众号（搜狗） | 10 分钟 | 搜狗收录有延迟，且要防验证码 | 准实时（10-30 分钟） |
| 百度知道 | 10 分钟 | 问答收录有延迟 | 准实时（10-30 分钟） |
| 豆瓣小组讨论 | 10 分钟 | 新帖发布后收录较快 | 准实时（10 分钟） |

注意：实时版数据存在 `data/live.db`，静态版数据存在原子化 Excel，是两套独立存储。
两个都开不会有数据冲突，但会对平台多发请求；日常建议二选一——
看实时动态用 `LIVE_PLATFORM_ENABLED=1 ./start.sh`，做存档/报表用定时流水线。

## 大屏自动刷新（不改原前端）

方案一：浏览器自动刷新插件（Chrome/Edge 搜索 “Auto Refresh”，设置 300 秒刷新大屏页面）。

方案二：使用项目自带的包装页 [web/大屏自动刷新.html](web/大屏自动刷新.html)，双击打开后每 300 秒重新加载原 `index.html`：

```text
大屏自动刷新.html           # 默认 300 秒刷新一次
大屏自动刷新.html?seconds=600  # 自定义刷新间隔
```

原 `01_code_docs/dashboard/index.html` 不做任何修改。

常用参数：

```bash
./start.sh --port 9000        # 换端口
./start.sh --no-sim           # 关闭模拟采集器
./start.sh --reset            # 清空实时库并从第一阶段数据重建基线
```

## 目录结构

```text
03_live_system/
├── server.py            # 服务端：静态页面 + API + SSE + 定时采集
├── db.py                # SQLite 统一存储
├── ingest.py            # 字段归一化、相关性判断、入库
├── stats.py             # 历史基线 + 实时增量统计合并
├── migrate_history.py   # 第一阶段 data.js → SQLite 迁移
├── classify.py          # 民族相关舆情关键词判断
├── config.py            # 配置（环境变量可覆盖）
├── collectors/          # 采集器框架与各平台接入位
│   ├── simulator.py     # 模拟采集器（演示实时链路）
│   ├── file_watcher.py  # 文件导入（inbox/ 丢 json/csv/jsonl）
│   ├── bilibili.py      # 已接入：B站公开搜索接口（实测通过）
│   ├── reddit.py        # 可选：Reddit OAuth/公开接口（默认关闭，需海外舆情时开启）
│   ├── weibo.py         # 已接入：微博热榜公开接口 + 第三方导出 + 开放平台 API（可选）
│   ├── douyin.py        # 已接入：抖音热榜公开接口（实测通过）
│   ├── wechat.py        # 已接入：搜狗微信文章搜索（实测通过）
│   ├── baidu_zhidao.py  # 已接入：百度知道搜索公开页（实测通过）
│   ├── douban.py        # 已接入：豆瓣小组讨论搜索公开页（实测通过）
│   ├── zhihu.py         # 知乎：实测被登录墙/风控拦截，暂未接入
│   ├── xiaohongshu.py   # 小红书：实测搜索需登录/签名，暂未接入
│   └── kuaishou.py      # 快手待接入（GraphQL 需登录/签名，暂走导出）
├── web/                 # 实时版大屏（复用第一阶段页面）
└── docs/统一数据字段.md   # 两阶段通用字段规范
```

## 核心 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/bootstrap` | 全量大屏数据（历史基线 + 实时增量） |
| GET | `/api/incidents?limit=50&after_id=0` | 最新舆情明细 |
| GET | `/api/collectors` | 各采集器状态与最近运行记录 |
| GET | `/api/events` | SSE 实时推送（新舆情 / 刷新 / 心跳） |
| POST | `/api/ingest` | 手动/程序推送舆情（单条或批量） |
| GET | `/api/key-accounts` | 重点账号/大V 传播数据聚合（账号、平台、发帖量、点赞、评论、转发） |
| POST | `/api/key-accounts/ingest` | 重点账号（creator）数据写入，自动标记重点账号并跳过关键词过滤 |
| POST | `/api/collectors/{name}/run` | 手动触发某采集器执行一次 |
| POST | `/api/review` | 审核 pending 记录（accepted/rejected） |

## 接入真实渠道的步骤

1. 各方向负责人填写 `collectors/渠道采集能力调查.md`，判断实时/准实时/人工；
2. 能实时或准实时的渠道，在 `collectors/` 下新建采集器，继承 `BaseCollector` 并实现 `collect()`：
   ```python
   class MyCollector(BaseCollector):
       name = "my_channel"
       label = "我的渠道"
       enabled = True
       interval = 300
       def collect(self):
           return [{"发布时间": "...", "平台": "...", "正文": "...", ...}]
   ```
3. 在 `collectors/__init__.py` 注册类；
4. 重启服务，`/api/collectors` 中可见新采集器并定时运行。

暂时只能人工导出的渠道，把文件（字段见 `docs/统一数据字段.md`）放进 `03_live_system/inbox/`，系统会自动读取入库。

## 数据说明

- 历史基线：`data.js`（平台 12,351 / 地区 1,586 / 31 省 / 482 条原话 / 37 天趋势等），迁移为 `origin=history` 记录；
- 原子化工作簿的「监测来源与查看信息」已改为自动统计：`build_data.py --atomic` 每次重算时
  从事实表生成（监测来源 = 各平台去重账号数，查看信息 = 记录条数），无需人工维护；
- 大屏地区轮播为省级口径：每个省份一条轮播、地图高亮单个省（`regions` 数据自带
  `provinces` 字段），原地区组信息保留在 `sourceGroup` 用于地区信息流匹配；
- 实时增量：模拟器默认每 12 秒生成 1-3 条演示数据，验证「采集 → 判断 → 归一化 → 入库 → 重算 → 推送 → 前端刷新」全链路；接入真实渠道后请关闭模拟器（`--no-sim` 或 `LIVE_SIM_ENABLED=0`）；
- 未命中民族相关关键词的记录进入 `pending`，需人工审核后才进入统计；
- 数据库为 `data/live.db`，删除后运行 `./start.sh --reset` 可从第一阶段数据重建。

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| LIVE_HOST / LIVE_PORT | 127.0.0.1 / 8765 | 监听地址 |
| LIVE_DB_PATH | data/live.db | 数据库路径 |
| LIVE_SIM_ENABLED | 1 | 模拟采集器开关 |
| LIVE_SIM_INTERVAL | 12 | 模拟采集间隔（秒） |
| LIVE_FILE_WATCH_ENABLED | 1 | 文件导入开关 |
| LIVE_FILE_WATCH_INTERVAL | 10 | 文件检查间隔（秒） |
| LIVE_PLATFORM_ENABLED | 0 | 实时服务端是否自动调度真实平台采集器 |
| LIVE_PLATFORM_POLL | 10 | 实时调度轮询间隔（秒） |
| WEIBO_MODE | auto | 微博采集模式 |
| WEIBO_HOT_KEYWORDS | 民族团结,民族,... | 热榜保留话题关键词 |
| WEIBO_HOT_COUNTED | 是 | 热榜话题是否计入统计 |
| WEIBO_HOT_AS_LIKES | 1 | 热度值近似填入点赞量 |
| WEIBO_EXPORT_DIR | data/weibo_exports/ | 第三方导出文件目录 |
| WEIBO_APP_KEY / SECRET / ACCESS_TOKEN | 空 | 微博开放平台 API（可选） |
| WEIBO_COOKIE | 空 | 微博移动端 Cookie（可选，实验） |
| DOUYIN_HOT_KEYWORDS | 民族团结,民族,... | 抖音热榜保留话题关键词 |
| DOUYIN_HOT_COUNTED | 是 | 抖音热榜话题是否计入统计 |
| DOUYIN_HOT_AS_LIKES | 1 | 抖音热度值近似填入点赞量 |
| WECHAT_SOGOU_PAGES | 1 | 搜狗微信搜索页数 |
| WECHAT_SOGOU_INTERVAL | 5 | 搜狗关键词间休息秒数 |
| BAIDU_ZHIDAO_PAGES | 1 | 百度知道搜索页数 |
| BAIDU_ZHIDAO_INTERVAL | 5 | 百度知道关键词间休息秒数 |
| DOUBAN_GROUP_PAGES | 1 | 豆瓣小组讨论搜索页数 |
| DOUBAN_GROUP_INTERVAL | 5 | 豆瓣关键词间休息秒数 |

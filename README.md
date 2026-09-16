# Realtime Opinion Monitor — 宣传周准实时监测

当前主链：

**小红书 / 抖音 / 快手 / B站 / 微博 / 百度贴吧 / 知乎 → MediaCrawler → 增量去重 → 志鹏 v2 → 来源类型/语言/地区整理 → 苏琦 `/api/ingest` → SQLite → `/api/bootstrap` + SSE → 大屏**

默认采用**单平台独立任务**，目标周期 300 秒。平台出现官方验证码、重新登录或安全验证时停止自动请求，人工完成官方验证后再继续；项目不实现验证码绕过。

## 1. 七个平台

当前统一代码入口已经扩展为：

- `xhs` 小红书
- `dy` 抖音
- `ks` 快手
- `bili` B站
- `wb` 微博
- `tieba` 百度贴吧
- `zhihu` 知乎

代码接入状态与“真实平台验收通过”要区分：

- 抖音：已有端到端成功记录
- 快手：已有端到端成功记录
- 小红书：曾端到端成功，当前仍可能遇人工验证
- 微博：已有适配基础，登录/验证链仍需继续验收
- B站：已接入统一链，待真实平台测试
- 百度贴吧：已接入统一链，待真实平台测试
- 知乎：已接入统一链，待真实平台测试

同学联调说明见 `docs/SEVEN_PLATFORM_TEST_GUIDE.md`。

## 2. 当前核心能力

- 关键词搜索、跨轮次去重、只处理新增内容
- v2 原始 `status/type` 自动分类，不改动协作者口径
- 权威媒体/新闻、自媒体、普通用户、律师/专家、二创/剪辑五类来源辅助分类
- 帖子/视频/评论统一字段化：正文、发布时间、账号、URL、点赞、评论、分享等
- B站额外保留播放、收藏、弹幕、投币等公开互动字段，供后续展示/分析使用
- 地区字段自动推给大屏；平台公开返回地区时可统计，不推断原始 IP
- 汉语及少数民族语言识别：藏语、维吾尔语、蒙古语、壮语；并预留哈萨克语、彝语、朝鲜语
- 自动 POST 到苏琦后端；失败批次进入 outbox，恢复后补发
- 运行状态区分 `SUCCESS / VERIFY_REQUIRED / LOGIN_REQUIRED / NETWORK_ERROR / CRAWLER_FAILED`
- 隐私安全的 GitHub 聚合结果同步：只提交统计，不提交原始正文、账号、URL、Cookie、数据库和 API Key
- 重点账号 creator 模式已扩展到七个平台的统一框架；正式使用前需分别验证 creator ID 格式及平台稳定性
- 部署前 `preflight.py` 自动检查 Python/uv/API Key/配置文件/核心模块，并检查本地 MediaCrawler 是否具备七个平台入口

## 3. 当前宣传周中文关键词

默认配置 `config/monitoring.windows.json`：

1. 2026年民族团结进步宣传周
2. 首个民族团结进步宣传周
3. 促进民族团结进步，奋进伟大复兴征程
4. 民族团结进步倡议
5. 民族团结进步宣传周主场活动
6. 石榴花开——铸牢中华民族共同体意识

采集侧基础关键词按统一配置维护；志鹏侧的态度词/态度标签迭代与采集关键词分开处理。

## 4. 少数民族语言监测

语言识别模块：`pipeline/language_detector.py`。

当前优先读取平台已有 `language/lang` 等字段；没有显式字段时，再按文字系统做保守检测：藏文、蒙古文、维吾尔文特征、壮文保守词形，同时支持彝文、朝鲜文等脚本识别。

多语言词包：`config/multilingual_keywords.json`。只有 `verified=true` 的词会自动加入搜索，避免未经核准的机器翻译直接作为正式检索词。

单平台测试：

```powershell
.\scripts\test_multilingual_single_platform.ps1 -Platform bili
```

## 5. 地区/IP属地

只使用平台公开返回的省级/地区级标签，不保存或推断原始 IP 地址。当前 MediaCrawler 教学版在部分平台可能不输出地区字段，因此 `region_rate=0` 不等于整条采集链失败。

测试：

```powershell
.\scripts\test_region_map_single_platform.ps1 -Platform dy -Keyword "民族团结"
```

重点检查 `region_records`、`region_rate`、`dashboard_push.ok`。

## 6. 大屏平台独立展示补丁

苏琦当前上游实时统计默认会把部分平台合并成平台组，例如“知乎/B站/百度知道”。老师最新要求是**一平台一条、不要合并**。

本仓库提供本地补丁：

```powershell
python .\scripts\patch_suqi_separate_platforms.py
```

它会让实时统计优先使用精确平台名。应用后重启 `server.py` 并刷新大屏。

注意：该补丁只解决实时平台分开展示，**不会清除旧历史基线**。正式宣传周预热阶段仍需单独建立“从指定开始时间计数”的清洁任务口径。

## 7. 单平台 5 分钟准实时监测

```powershell
.\scripts\start_single_platform_windows.ps1 -Platform zhihu
```

或启用安全 watchdog：

```powershell
.\scripts\watch_single_platform_windows.ps1 -Platform zhihu
```

watchdog 对普通网络/进程异常可延时重启；发现 `VERIFY_REQUIRED / LOGIN_REQUIRED` 会停止，不反复触发平台安全验证。

如果一轮运行超过 300 秒，不叠加启动下一浏览器任务，而是在当前轮结束后立即进入下一轮。“5分钟”是目标调度周期，不保证所有平台每轮都能在5分钟内完成。

## 8. 七平台同学测试

首次：

```powershell
cd E:\realtime-opinion-monitor
git pull --ff-only
python .\scripts\preflight.py
python -m unittest tests.test_platform_normalizer -v
```

确保苏琦后端已运行后，每位同学只测自己负责的平台：

```powershell
.\scripts\test_platform_single_cycle_windows.ps1 -Platform bili
```

可替换为 `xhs / dy / ks / bili / wb / tieba / zhihu`。

测试完成请保留最后的 `Test summary`，重点回传：`crawler_status`、`crawler_state`、`return_code`、`duration_seconds`、`new_records`、`classified_records`、`dashboard_ok`、`dashboard_inserted`、`outbox_after`。

## 9. 部署预检与一键启动

```powershell
python .\scripts\preflight.py
```

单平台总控入口：

```powershell
.\scripts\start_all.ps1 -Platform ks
```

会完成预检、检查/拉起苏琦后端、打开大屏，并默认通过安全 watchdog 运行指定平台。

多语言：

```powershell
.\scripts\start_all.ps1 -Platform bili -Multilingual
```

可选 GitHub 脱敏汇总同步：

```powershell
.\scripts\start_all.ps1 -Platform ks -EnableGithubSync -PushGithub
```

可选重点账号监测（需先配置 `config/key_accounts.json`）：

```powershell
.\scripts\start_all.ps1 -Platform ks -EnableKeyAccounts
```

## 10. GitHub 聚合结果自动同步

`scripts/publish_results_to_github.py` 与 `scripts/start_results_sync_windows.ps1` 默认可生成：

```text
results/latest_summary.json
results/daily/YYYY-MM-DD.json
```

汇总覆盖七平台数据目录，并包含平台量、地区覆盖、语言、v2 分类、来源类型以及可用的公开互动计数；不包含原始正文、账号名或 URL。

## 11. 重点账号传播监测

模板：`config/key_accounts.example.json`，已包含七个平台入口。复制为 `config/key_accounts.json` 后填写经确认的 creator ID/主页标识并启用。

新内容只分类一次，后续轮次复用原分类并更新可获得的公开互动计数。B站、贴吧、知乎以及微博 creator 模式仍需同学真实平台验收后再作为正式能力使用。

## 12. 视频内部 ASR/OCR

当前视频快线自动使用标题、发布文案、标签进行 v2 判断，并预留 `asr_text / ocr_text` 字段。

**视频下载 → ASR → OCR → 二次 v2 更新仍属于待接入慢线能力。**这不阻塞当前5分钟关键词发现主链。

## 13. 安全与数据边界

不要提交 API Key、`.env`、Cookie、browser_data、登录信息、原始舆情全文、本地 SQLite、原始用户 ID 或正式重点账号内部清单。GitHub 自动同步只 stage `results/` 下的脱敏聚合结果。

## 14. 仍需实际验收

代码已扩展到七个平台，但正式部署前仍需真实 Windows/平台环境逐个平台验收登录、搜索返回、JSONL字段、v2分类、大屏入库、长期风控稳定性；少数民族语言真实命中率、地区字段可用率、重点账号 creator ID 格式、GitHub 自动 push、视频 ASR/OCR 也需继续验收。

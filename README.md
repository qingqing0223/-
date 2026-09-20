# Realtime Opinion Monitor — 宣传周准实时监测

当前主链：

**小红书 / 抖音 / 快手 / B站 / 微博 / 今日头条 / 知乎 / 微信公众号 / 视频号 → 平台适配器（MediaCrawler + 今日头条 Playwright 适配器） → 作品/视频/一级评论/楼中楼 → 增量去重 → 评论父子关系重建 → 志鹏 v2 → 来源类型/语言/地区整理 → 苏琦 `/api/ingest` → SQLite → `/api/bootstrap` + SSE → 大屏**

默认采用**单平台独立任务**，目标周期 300 秒。平台出现官方验证码、重新登录或安全验证时停止自动请求，人工完成官方验证后再继续；项目不实现验证码绕过。

## 1. 七个平台

当前统一代码入口已经扩展为：

- `xhs` 小红书
- `dy` 抖音
- `ks` 快手
- `bili` B站
- `wb` 微博
- `toutiao` 今日头条
- `zhihu` 知乎

代码接入状态与“真实平台验收通过”要区分；各平台仍受登录状态、官方接口返回范围、平台自身分页上限和风控影响。

## 2. 当前核心能力（全矩阵模式）

默认配置现已统一开启：

- 事件关键词搜索
- 搜索结果持续分页，尽量运行到平台返回“无更多结果”为止；MediaCrawler 本身要求整数上限，因此使用 `100000` 作为防止异常死循环的安全上限
- 候选作品跨轮次去重，只处理新增内容
- 5分钟目标周期增量轮询；若一轮超过300秒，则该轮结束后立即进入下一轮，不并发叠加浏览器任务
- 帖子/视频详情字段化：正文/文案、发布时间、账号、URL、点赞、评论、分享等公开字段
- 一级评论抓取
- 楼中楼/二级评论抓取
- 评论父子关联字段：`comment_id / parent_comment_id / root_comment_id / comment_level / sub_comment_count`
- 评论作者公开信息字段化：昵称、平台公开/脱敏作者标识、头像/主页字段（平台有返回时）
- 平台公开 IP属地/地区字段读取与省级归一化；不推断或保存真实原始 IP
- 评论、帖子、视频统一标准化入表
- 志鹏 v2.2 `status/type` 自动分类：L1 为 `normal / attention / problematic`，`attention`（中性信息）下设 `neutral / information_gap / consultation` 三个 L2
- 权威媒体/新闻、自媒体、普通用户、律师/专家、二创/剪辑五类来源辅助分类
- 汉语及少数民族语言识别：藏语、维吾尔语、蒙古语、壮语；并预留哈萨克语、彝语、朝鲜语
- 自动 POST 到苏琦后端；失败批次进入 outbox，恢复后补发
- 运行状态区分 `SUCCESS / VERIFY_REQUIRED / LOGIN_REQUIRED / NETWORK_ERROR / CRAWLER_FAILED`
- 安全 watchdog：普通网络/进程故障冷却后重启；遇登录/验证码/官方安全验证停止等待人工处理，不绕过验证
- 隐私安全的 GitHub 聚合结果同步：只提交统计，不提交原始正文、账号、URL、Cookie、数据库和 API Key
- GitHub 汇总增加评论层级统计：评论总数、一级评论、楼中楼、父评论关联率、评论地区覆盖率

学生历史生成的 `monitoring.local.json` 会在新版 `preflight.py` 或正式启动脚本运行时自动升级上述能力开关，同时保留每台机器自己的路径和本地设置。

## 3. 当前宣传周中文关键词

默认主机、学生、地区及多语言配置均包含：

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

## 5. 地区/IP属地

只使用平台公开返回的省级/地区级标签，不保存或推断原始 IP 地址。帖子和评论均进入同一地区归一化流程。平台不返回地区时保持为空，不做猜测。

## 6. 评论与父子关系

正式配置现已开启：

```text
get_comment = yes
get_sub_comment = yes
ingest_comments = true
max_comments_count_singlenotes = 100000
comments_until_exhausted = true
```

标准化结果保留 `content_id`、`comment_id`、`parent_comment_id`、`root_comment_id`、`comment_level`、`sub_comment_count`，用于一级评论/楼中楼关联、评论态度统计和地区统计。

## 7. 搜索分页到自然终点

MediaCrawler 命令行必须提供最大作品数，无法使用真正的“无限”数值。项目采用：

```text
search_until_exhausted = true
crawler_max_notes_count = 100000
```

MediaCrawler 原生平台按自身 `has_more/no_more` 等分页信号结束；今日头条适配器按公开搜索页滚动结果自然停止或安全上限停止；`100000` 只是异常保护上限。平台自身可能仍存在搜索结果数量上限、登录限制或风控限制，因此“自然终点”指当前官方会话实际可返回的终点。

## 8. 大屏供数

主机配置继续启用苏琦 `/api/ingest`。学生机不直接访问负责人电脑的 `127.0.0.1`，因此学生配置保留 `dashboard.enabled=false`，由学生机自动同步脱敏聚合到 GitHub；负责人主机汇总/大屏链保持开启。

## 9. 部署预检

```powershell
python .\scripts\preflight.py --config .\config\monitoring.local.json
```

新版 preflight 会自动升级旧的本地 `*.local.json` 到全矩阵模式，并检查：

- 七平台配置
- 全矩阵开关
- Python / Git / uv / API Key
- MediaCrawler 原生平台入口 + 项目内置今日头条 Playwright 适配器
- pipeline / monitor / dashboard_adapter 核心模块

## 10. 学生正式启动

```powershell
.\scripts\start_student_platform_windows.ps1 `
  -Platform dy `
  -NodeId dy01 `
  -Config .\config\monitoring.local.json `
  -PushGithub
```

将 `dy` 替换为本人负责的平台。启动脚本也会再次把旧本地配置升级为全矩阵模式。

## 11. GitHub 聚合结果自动同步

学生节点结果写入：

```text
results/YYYY-MM-DD/nodes/<platform>/<node>.json
```

只同步脱敏聚合统计，不同步原始正文、账号名、URL、Cookie 或 API Key。汇总包括平台量、帖子/视频/评论类型、v2 分类、来源类型、地区覆盖、语言、互动量及评论父子关系覆盖指标。

## 12. 视频内部 ASR/OCR

当前视频快线自动使用标题、发布文案、标签进行 v2 判断，并预留 `asr_text / ocr_text` 字段。

**视频下载 → ASR → OCR → 二次 v2 更新仍属于待接入慢线能力。**因此“视频作品被统计”已经实现，但“所有视频内部语音和画面文字都完成多模态解析”仍不能标记为全部完成。

## 13. 安全与数据边界

不要提交 API Key、`.env`、Cookie、browser_data、登录信息、原始舆情全文、本地 SQLite、原始用户 ID 或正式重点账号内部清单。GitHub 自动同步只 stage `results/` 下的脱敏聚合结果。

## 14. 实际运行说明

全矩阵模式显著增加请求量，特别是一级评论、楼中楼和持续分页，因此单轮很可能超过5分钟。程序不会为了追求固定5分钟而叠加新的并发轮次；遇官方登录、验证码或安全验证会停下来等待人工处理。平台自身不返回的字段、已删除/私密内容以及官方搜索结果上限不能由程序补造。

# Realtime Opinion Monitor — 宣传周准实时监测

当前主链：

**微博 / 小红书 / 抖音 / 快手 → MediaCrawler → 增量去重 → 志鹏 v2 → 来源类型/语言/地区整理 → 苏琦 `/api/ingest` → SQLite → `/api/bootstrap` + SSE → 大屏**

默认采用**单平台独立任务**，目标周期 300 秒。平台出现官方验证码、重新登录或安全验证时停止自动请求，人工完成官方验证后再继续；项目不实现验证码绕过。

## 1. 当前核心能力

- 关键词搜索、跨轮次去重、只处理新增内容
- v2 原始 `status/type` 自动分类，不改动协作者口径
- 权威媒体/新闻、自媒体、普通用户、律师/专家、二创/剪辑五类来源辅助分类
- 内容/视频标题文案、互动量、发布时间、公开地区/IP属地标签统一字段化
- 地区字段自动推给大屏，后续详情拿到地区时允许补写同一 UID；点赞/评论/分享计数可向上更新
- 汉语及少数民族语言识别：藏语、维吾尔语、蒙古语、壮语；并预留哈萨克语、彝语、朝鲜语
- 自动 POST 到苏琦后端；失败批次进入 outbox，后续恢复后补发
- 运行状态区分 `SUCCESS / VERIFY_REQUIRED / LOGIN_REQUIRED / NETWORK_ERROR / CRAWLER_FAILED`
- 隐私安全的 GitHub 聚合结果同步：只提交统计，不提交原始正文、账号、URL、Cookie、数据库和 API Key
- 重点账号 creator 模式基础链：可周期检查新发内容，并刷新公开点赞/评论/分享计数
- 部署前 `preflight.py` 自动检查 Python/uv/API Key/配置文件/核心模块/大屏/Git 基础状态

## 2. 当前宣传周中文关键词

默认配置 `config/monitoring.windows.json`：

1. 2026年民族团结进步宣传周
2. 首个民族团结进步宣传周
3. 促进民族团结进步，奋进伟大复兴征程
4. 民族团结进步倡议
5. 民族团结进步宣传周主场活动
6. 石榴花开——铸牢中华民族共同体意识

平台代码：`wb` 微博、`xhs` 小红书、`dy` 抖音、`ks` 快手。

## 3. 少数民族语言监测

语言识别模块：`pipeline/language_detector.py`

当前会优先读取平台/导出数据已有的 `language/lang` 等字段；没有显式字段时，再按文字系统做保守检测：

- 藏文 Unicode → 藏语
- 蒙古文 Unicode → 蒙古语
- 维吾尔文常用阿拉伯字母特征 → 维吾尔语（中等置信度）
- 壮语因使用拉丁字母，不能仅靠 Unicode 与英文可靠区分，因此使用显式语言字段 + 保守词形标记
- 同时支持彝文、朝鲜文等脚本识别

多语言搜索词包：`config/multilingual_keywords.json`。**只有 `verified=true` 的词会自动加入搜索**，防止机器翻译错误导致漏检/误检。

当前已加入公开资料可核对的通用检索词：藏语“民族团结”、维吾尔语“民族团结”、蒙古语“民族团结”，以及广西民族报壮文版中对应“民族团结/民族团结进步”的壮文写法。它们用于宽召回，不冒充“民族团结进步宣传周”完整官方译名；如民委后续提供宣传周正式多语种材料，应直接把正式译名补入词包。

有界多语言测试配置：

```powershell
.\scripts\test_multilingual_single_platform.ps1 -Platform dy
```

结果会直接给出 `language_counts`、`minority_language_records` 和 `minority_language_rate`。

## 4. 地区/IP属地和中国地图

只使用平台公开返回的省级/地区级标签，不保存或推断原始 IP 地址。

地区测试：

```powershell
.\scripts\test_region_map_single_platform.ps1 -Platform dy -Keyword "民族团结"
```

重点检查：

```text
region_records
region_rate
dashboard_push.ok
```

苏琦本地数据库如需支持“后续拿到地区再补写”和互动量更新，运行一次：

```powershell
python .\scripts\patch_suqi_region_upsert.py
```

随后重启苏琦 `server.py`。

## 5. 单平台 5 分钟准实时监测

```powershell
.\scripts\start_single_platform_windows.ps1 -Platform ks
```

或启用安全 watchdog：

```powershell
.\scripts\watch_single_platform_windows.ps1 -Platform ks
```

watchdog 对普通网络/进程异常可延时重启；发现 `VERIFY_REQUIRED` / `LOGIN_REQUIRED` 会停止，不反复触发平台安全验证。

如果一轮运行超过 300 秒，不叠加启动下一浏览器任务，而是在当前轮结束后立即进入下一轮。因此“5分钟”是目标调度周期，不是所有平台都保证固定 5 分钟完成。

## 6. 部署预检与一键启动

先检查本机环境：

```powershell
python .\scripts\preflight.py
```

当前 Windows 总控入口：

```powershell
.\scripts\start_all.ps1 -Platform ks
```

它会：

```text
部署预检
→ 检查苏琦后端
→ 后端未启动则自动拉起
→ 打开大屏
→ 启动指定平台
→ 默认使用安全 watchdog
```

多语言配置：

```powershell
.\scripts\start_all.ps1 -Platform dy -Multilingual
```

同时启动聚合结果 GitHub 同步（本机 Git 已配置写权限后）：

```powershell
.\scripts\start_all.ps1 -Platform ks -EnableGithubSync -PushGithub
```

如果已经配置 `config/key_accounts.json`，还可以同时启动同平台重点账号监测：

```powershell
.\scripts\start_all.ps1 -Platform ks -EnableKeyAccounts
```

## 7. GitHub 聚合结果自动同步

脚本：`scripts/publish_results_to_github.py`、`scripts/start_results_sync_windows.ps1`。

默认每 15 分钟生成：

```text
results/latest_summary.json
results/daily/YYYY-MM-DD.json
```

内容只包含平台量、地区覆盖、语言分布、少数民族语言分布、v2 分类、来源类型、互动量及运行状态，不包含原始文本、账号名或 URL。

只生成本地汇总：

```powershell
.\scripts\start_results_sync_windows.ps1
```

使用本机已有 Git 凭据自动 commit + push：

```powershell
.\scripts\start_results_sync_windows.ps1 -Push
```

## 8. 重点账号传播监测

模板：`config/key_accounts.example.json`。

先复制为：

```text
config/key_accounts.json
```

该正式账号清单已加入 `.gitignore`，不会被误提交到公开仓库。填入经确认的各平台 `creator_id` 并启用后：

```powershell
.\scripts\start_key_accounts_windows.ps1
```

该链路使用 MediaCrawler creator 模式：新内容只分类一次，后续周期复用原分类并刷新公开点赞/评论/分享计数，再推送大屏。若平台要求重新登录/验证，会停止自动轮询等待人工处理。

## 9. 视频内部 ASR/OCR

当前视频快线已经自动使用标题、发布文案、标签进行 v2 判断，并预留 `asr_text / ocr_text` 字段；只要后续视频 worker 写入这两个字段，现有分类代码会自动把它们合并到 `analysis_text`。

**视频下载 → ASR → OCR → 二次 v2 更新目前仍属于待接入的慢线能力，尚不能标记为已完成。**不应让它阻塞 5 分钟实时发现主链。

## 10. 安全与数据边界

不要提交：

- API Key / `.env`
- Cookie、browser_data、登录信息
- 原始舆情全文数据
- 本地 SQLite 数据库
- 原始用户 ID
- 正式重点账号内部清单 `config/key_accounts.json`

GitHub 只同步 `results/` 下的脱敏聚合统计。

## 11. 仍需实际验收的项目

代码已尽量自动化，但以下项目必须在实际 Windows/平台环境继续验收：少数民族语言真实命中率、地区地图动态变化、GitHub 本机自动 push 凭据、重点账号各平台 creator_id 格式与互动字段稳定性，以及长期运行下的平台登录/风控稳定性。

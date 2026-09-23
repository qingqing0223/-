# 微信公开搜索开源实现审计

审计日期：2026-09-23。范围仅为用户指定的两个 GitHub 仓库、现有搜狗实现及一次有明确请求上限的浏览器适配测试。不调用 SocialDataX、不安装第三方项目、不执行下载脚本、不修改历史 Excel/POMS。

## 结论

两个项目的发现入口均为搜狗微信，不能算新增独立数据源。TypeScript 项目明确沿用了 Python 项目的 URL 解析方法。它们所谓 `real_url` 是从搜狗跳转页面获得的微信地址，**不等同于永久地址，也没有再次访问或签名失效校验**。不能因 README 宣称“真实链接”就计为本项目的稳定 canonical URL 成功。

选择 `wx-search-cli` 作为最小安全适配的参考。只沿用公开结果选择器及 `#js_content` 正文提取思路，网络访问使用正常有头 Chrome。没有移植手动组装跳转字符串、模拟浏览器请求头或旧 Cookie。浏览器正常执行服务器给出的跳转 JavaScript，不解密、不构造或改写临时签名。

## 源码和依赖

| 项目 | 已检查的源码 | 依赖与执行边界 |
|---|---|---|
| [tjx666/wx-search-cli](https://github.com/tjx666/wx-search-cli) | `src/search.ts`、`src/parsers.ts`、`src/content.ts`、`src/constants.ts`、`package.json` | Node >=18.17；运行时 cheerio ^1.0.0，开发用 TypeScript/Vitest。package 无 install/postinstall 钩子，prepublishOnly 运行构建。本次未执行 npm/npx/bun 安装或入口。 |
| [fancyboi999/weixin_search_mcp](https://github.com/fancyboi999/weixin_search_mcp) | `weixin_search_mcp/tools/weixin_search.py`、`weixin_search_mcp/main.py`、`pyproject.toml` | Python >=3.12；requests、lxml、FastMCP/MCP、FastAPI/Uvicorn、pydantic、loguru、dotenv 等。搜索本身不需要完整 MCP 服务。本次未执行其网络函数或 MCP 入口。 |

公开源文件下载留在 `data/wechat_mp/open_source_review/wx-search-cli/` 和 `data/wechat_mp/open_source_review/weixin_search_mcp/`，仅用于审计。下载文件未作为正式模块导入。

Python 源码 `get_real_url_from_sogou` 内包含作者硬编码的历史 Cookie。本项目不使用、不复制到请求头，也不在本报告中展示其内容。原始函数不符合本项目的正常浏览器会话约束。

## URL 处理实质差异

| 环节 | wx-search-cli | weixin_search_mcp | 本项目既有实现 |
|---|---|---|---|
| 搜索 | fetch 公开 `/weixin?type=2...` | requests GET 同一公开页面 | 有头 Playwright 导航同一页面 |
| 结果抽取 | 指定标题 ID、卡片 s-p/span.s2 | XPath 对应相同公开节点 | 卡片级标题、账号、明确发布时间区；保留摘要和关键词 |
| 会话 | 取本次搜索 Set-Cookie，再手动转发给跳转请求 | 硬编码旧 Cookie | 浏览器自己的正常会话，无伪造登录态 |
| 跳转目标 | 从 `/link` HTML 找 `url += '...'` 字符串，连接、去掉 @，必要时补协议主机前缀 | 类似字符串拼接，且扫描起点会跳过第一个片段 | 点击公开链接，让正常页面导航执行；读地址栏、canonical/og:url |
| 正文 | 获取页面后读 `#js_content` 文本 | lxml 读取 `#js_content` 文本 | 旧链主要采集搜索摘要；详情阶段可独立增加公开正文 DOM 读取 |
| 稳定性判断 | 不排除临时签名地址，无复访校验 | 同左 | 旧 `canonical_article_url` 只保留短链或 biz/mid/idx；本次探针使用更严格的 `stable_public_url`，拒绝 signature/timestamp 等临时参数、保留 sn，另加正文复访校验 |
| 验证码 | 检测 anti-spider 特征后返回空/异常 | 检测后返回空/异常 | 暂停等待人工验证，可保存检查点 |

上述字符串拼接是对公开跳转脚本的解释，不是“获取永久链接”的新数据能力。即使正常浏览器得到正文，地址仍可能带临时签名。为遵守本次边界，不采用自行去噪重建 URL 的方式；仅浏览器正常执行页面。实际可移植价值是卡片/正文选择器、明确的验证拦截检测、详情失败时保留搜索记录，不是批量恢复永久地址的保证。

源码引用：[TypeScript 搜索](https://github.com/tjx666/wx-search-cli/blob/main/src/search.ts)、[TypeScript 解析器](https://github.com/tjx666/wx-search-cli/blob/main/src/parsers.ts)、[正文访问](https://github.com/tjx666/wx-search-cli/blob/main/src/content.ts)、[Python 搜索实现](https://github.com/fancyboi999/weixin_search_mcp/blob/main/weixin_search_mcp/tools/weixin_search.py)。

## 最小隔离测试

脚本：`data/wechat_mp/open_source_review/probe_one.py`。

```powershell
.\.venv\Scripts\python.exe .\data\wechat_mp\open_source_review\probe_one.py --keyword "民族团结进步宣传周"
```

- 只搜索一个关键词第一页，只打开第一个结果；没有分页和全结果详情循环。
- 正常有头 Chrome，不设置自定义 UA/Cookie、不调用第三方接口。
- 验证码写入 `VERIFY_REQUIRED` 检查点，默认等待人工最多20分钟；不自动解题、不反复刷新。
- 记录公开搜索 URL、卡片、真实导航 URL、页面文档响应状态、正文和失败原因；不记录请求头、Cookie、浏览器存储或真实网络 IP。
- 同时区分到达微信域名、取得正文、得到规范稳定 URL 三种结果。只有存在稳定地址候选、正文正常且新页面复访正文一致，才记 `STABLE_URL_VERIFIED`。
- 结果文件默认 `data/wechat_mp/open_source_review/live_receipt.json`。发布输出使用脱敏汇总，不将临时 URL 当官方永久 ID。

此文件创建时仅完成源码检查及 `py_compile` 语法检查，**尚未执行 live 测试**；真实数量以随后生成的 `live_receipt.json` 和主监测节点验收报告为准。不得把本报告中的测试方案当作成功结果。

直接调用上游 `search` 函数会对第一页所有结果逐条做 URL 请求，不能满足本次“仅一条解析”限制。隔离探针是经审查的最小浏览器适配，不能宣传为上游原包已成功运行。Google/Bing 应独立作为发现源接入，搜狗 URL 失败不得影响已具备证据的候选入库、导出和前端更新。

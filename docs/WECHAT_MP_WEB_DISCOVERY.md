# 微信公众号 Google/Bing 公开发现源

## 参考源码审计

审核对象：[job-radar-wechat-formal](https://github.com/Wenshuishi0528/job-radar-wechat-formal)。只阅读源码，没有执行它的脚本、安装其依赖或克隆项目。

- [web_search_importer.py](https://github.com/Wenshuishi0528/job-radar-wechat-formal/blob/main/services/api/app/web_search_importer.py) 中 `build_search_query` 使用 `site:mp.weixin.qq.com/s`；`build_plain_search_url` 构造普通 Google/Bing 搜索页；网络读取使用标准库 urllib。它会提取 Google 包裹链接及解码 Bing `u=a1...` 参数。本项目不移植这些解码步骤。
- [wechat_articles.py](https://github.com/Wenshuishi0528/job-radar-wechat-formal/blob/main/services/api/app/wechat_articles.py) 为公众号内容索引和公开页面解析提供独立模块。
- [requirements.txt](https://github.com/Wenshuishi0528/job-radar-wechat-formal/blob/main/requirements.txt) 列出 FastAPI、uvicorn、pydantic、python-multipart、certifi；本次不引入这些依赖，仅使用本仓库已有 Playwright 和标准库。

## 实现接口

`wechat.mp_web_discovery.collect_web(config, keywords, source)`，source 为 `google` 或 `bing`。返回 `status`、`records`、`keyword_stats`、`errors`。

每关键词仅第一页，最多保存3个结果。查询为 `site:mp.weixin.qq.com/s/ "关键词"`。只接纳真实结果标题链接中的直接微信文章地址，忽略广告、导航、非微信链接、Bing编码跳转链接。不从全文URL正则扫描推断结果，不伪造请求身份，不调用搜索API。

默认只保存发现证据，由主节点独立详情队列调用 `fetch_public_article(page,url)`。`wechat_mp_web_verify_inline=true` 仅用于小规模验收。仅从公开文章标题、公众号名称、明确发布时间区域和正文DOM取值；不从正文日期推断时间、不读取私有脚本变量。元数据不足时仍保存搜索证据，但保留待核验，不能计入有效文章。

每页 checkpoint 落盘后立即调用可选 `config["wechat_mp_on_page"](rows, progress)` 入库回调，不等待其余关键词；没有识别出结果卡片且没有明确“无结果”页面证据时记为 ERROR，不把反爬或DOM变化当作零结果。仅编码跳转卡片同样记录明确失败原因。

Google/Bing各有独立 `browser_profile_google` / `browser_profile_bing`。状态写入工作目录的 `in_progress/<source>_progress.json`，发现记录先落盘再取详情。验证码状态为 `VERIFY_REQUIRED`；默认保留浏览器无限等待人工，可配置 `wechat_mp_manual_verify_wait_seconds=0` 立即返回以供自动验收。等待仅观察页面，不刷新、不自动答题。主节点负责限制来源并发与持久化重试。

`fetch_public_article` 的 `verified_metadata` 仅表示公开页标题、帐号、时间已取得，不等于主题有效。`canonical_url` 只接受可访问正文页面中实际出现的稳定格式地址；临时签名不会被删改以伪造永久URL。`canonical_revisit_verified=false` 明确本接口不自动重复访问。正文可读但只有临时地址时仍返回正文，URL状态维持 `URL_UNRESOLVED`。

详情入口允许实际保存的 `weixin.sogou.com/link` 公开跳转地址，使用正常浏览器导航；最终页面必须确实位于微信文章域名，才允许 `verified_metadata=true`。

## 测试边界

单元测试 `tests/test_wechat_mp_web_discovery.py` 覆盖链接来源、临时签名、失效页、明确时间区、空指标、前三条限制、网络失败、验证码停止。它们使用合成夹具验证规则，不是正式采集数据。真实 Google/Bing 小样本验收由主节点统一执行，不能将单元测试成功算作网络来源可用。

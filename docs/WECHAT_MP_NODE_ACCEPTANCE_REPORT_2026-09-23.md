# 微信公众号持续监测节点：修复版离线验收报告

> 交付对象：2026-09-23 `wechatmp03`；数据样本来自已提供的 2026-09-21 `wechatmp02` 真实历史 JSONL；不把历史数据算作新采集。该报告在离线测试完成后填写，不代表生产机或搜索源的真实联网验收。

## 修改及修复范围

核心：`wechat/mp_node_store.py`（持久化、合并、历史导入、恢复队列、来源检查点），`wechat/mp_node.py`（独立采集/详情/定时发布及只读 HTTP 服务），`wechat/mp_frontend.py`（原始字段、来源停滞、隔离 POMS 冲突、原子快照），`wechat/mp_search.py`（分页新观察标记），`wechat/mp_web_discovery.py`（Google/Bing 断点恢复），`scripts/run_wechat_mp_node.py`（`--serve-only`），`config/monitoring.wechat.node.json`（关闭 Google 和默认详情补采、非阻塞验证码及独立发布周期），`data/wechat_mp/open_source_review/smoke_web.py`（仅显式命令行调用才能联网），`wechat/mp_export.py` 与 `scripts/export_wechat_mp_xlsx_fallback.py`（可选原 V3 工作簿后备）、`tests/test_wechat_mp_node.py` 与 `tests/test_wechat_mp_web_discovery.py`（故障与端到端验收）；原有测试及其它平台采集逻辑保留。

## 已知数据语义

原始批次含 16 条真实候选、15 条有效、1 条待核验。离线导入后的前端五表预期为 16、0、15、0、15 条；详情 URL 未完成不阻断基础文章供数。前端基础可读字段以原始记录和表1为准：内容 ID（稳定的本地回退标识，不冒称官方 ID）、标题、公众号名称、真实记录的发布时间与抓取时间、命中关键词与发现来源、可用公开搜索跳转/真实微信 URL（如有）、摘要或已有真实正文、核验状态及原因。互动指标、粉丝数、IP 属地、评论及回复未取得时保留 `null`/空数据或明确的传输占位，不构造记录或 0 观测。

POMS 仅使用本地文件和 `poms_tables` 生成传输视图，校验冲突逐记录隔离；任何未获取数字的零占位及审核待核验映射 `false` 都必须结合元数据解释，不能按真实观察使用。没有后端授权配置，因此没有自动/真实上传。

## 实际离线验收结果

- 在当前 Linux/Python 测试环境，运行 `tests/test_wechat_mp_node.py`、`tests/test_wechat_mp_frontend.py`、`tests/test_wechat_mp_web_discovery.py`、`tests/test_wechat_mp_v3.py`、`tests/test_wechat_mp_poms.py`、`tests/test_wechat_mp_display.py`、`tests/test_wechat_mp_daily_batch.py`：**72 passed, 1 skipped, 6 subtests passed**。未运行的单项是依赖 Windows PowerShell 的平台专用测试，须在用户本机验收。
- 另外使用**真实项目 CLI**在隔离工作目录连续执行两遍 `--prepare-history`，再启动真实独立 `--serve-only` 进程并通过本地回环 HTTP 逐一访问七个必需接口。确认原始历史文件与内置验收副本字节完全相同、未覆盖旧批次；节点 16 条记录、重复导入不增加、未启用浏览器/付费接口；全部五表可读取，POMS 表级校验无冲突（**0 条 schema 冲突**）。
- 当前历史中 16 条永久微信文章 URL 仍未取得。`NO_LIVE_EVIDENCE` 明确表示此轮仅离线历史种子，没有 9 月 23 日新搜索结果。Google 因配置未启用，不宣称已通过验证；搜狗和 Bing 尚待 Windows 真人浏览器实测。

## 运行边界

所有联网搜索、真实验证码、跨电脑访问、Windows 本机真实 Chrome 与学校 POMS 后端认证和上传**未在本离线环境实测**。如搜索全部暂停，`metadata.collection` 会展示 `NO_LIVE_EVIDENCE` 或最近确有观察的时间，不用快照导出时间代替新采集时间。独立 HTTP 服务仅监听本机 `127.0.0.1:8765`。请根据 `docs/WECHAT_MP_NODE_WINDOWS_OFFLINE_ACCEPTANCE.md` 在自己的 Windows 电脑完成真实浏览器、数据接口与任务重启验收。

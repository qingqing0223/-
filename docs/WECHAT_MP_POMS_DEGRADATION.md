# 微信公众号基础供数与 POMS 降级约定

本次仅检查项目内 `docs/批量输入输出接口指南.md`、`config/poms.wechat_mp.schema.json`（2026-09-22 缓存的公开 OpenAPI）和 `batch_test_samples/01` 至 `05` 的真实字段顺序。没有上传、试写或访问 POMS。

## 前端文件

`wechat.mp_frontend.export_frontend(cfg, state)` 输出到 `wechat_mp_frontend_root`，默认 `data_submissions/wechat_mp/2026-09-23_wechatmp03/frontend/`。

- `latest.json`：原子替换的完整快照，内含五表、原始记录、来源状态、隔离证据、schema 冲突及 POMS 副本；前端应优先读取这一个文件，避免跨文件读取过程中混合不同代快照。
- `table1.json` 至 `table5.json`：中文 TechDesign V3 字段，未知值保持 null。
- `table1_batch.json` 至 `table5_batch.json`：服务器英文 schema，顺序与样例一致。仅输出通过本地 schema 校验的行。表2/4无真实评论则为 []。
- `metadata.json`、`schema_conflicts.json`：来源/时间口径、缺失字段及提交占位说明、逐行字段冲突。

每个文件均临时写入后原子替换，`latest.json` 最后发布。导出仅读取传入记录的深拷贝，不修改历史批次文件、原始 null、原始发布时间或既有 Excel/POMS。

## 必填字段审计与最小处理

| 条件 | 当前 schema | 本地降级处理 | 后端最小改动建议 |
|---|---|---|---|
| 没有永久微信 URL，只有真实搜狗链接 | `original_content_url` 为 string，没有限定 mp.weixin 域名或 URI format | 保留真实搜狗链接；URL 类型、URL_UNRESOLVED/详情状态在旁路 records 中表达 | 无需改 schema 即可供基础内容 |
| 官方帐号 ID 未提供 | `publisher_account_id`、`account_id` 为 string | POMS 沿用已批准的 local_wxacct_* 内部关联键；原始字段仍 null | 如大屏需要区分官方/内部ID，应读取 metadata 或另加后端身份来源字段 |
| 互动统计未知 | 统计字段为非负 integer；指南要求未取得填0 | 仅 POMS 传输视图补0，metadata 列出每一项占位；原始表和可靠汇总保留 null | 后端统计/大屏需接收可用性旁路，或扩展 null/availability 字段，才能仅凭服务器数据区分缺失0与真实0 |
| 待核验 | `is_valid_monitoring_data` 仅 boolean | 已获用户许可：false + 具体待核验原因；本地仍保留待核验状态，单独统计 | 后端新增 review_status 才能精确表达三态；当前不擅自新增 POMS 字段 |
| 发布时间缺失/无时区 | `published_at` 必填 date-time | 不编造时间；留在 quarantine evidence，排除 POMS，明确记录 published_at 冲突 | 如必须展示这类线索，可新增线索表或允许 published_at=null，并明确不是有效监测文章 |
| 采集时间或其他单行字段非法 | date-time/各字段约束 | 只隔离冲突行的 POMS 提交，保留原始基础快照，不阻塞其他正常行 | 修复实际字段或扩充合法 schema，不以假的时间/链接补齐 |

旧批次为历史输入，绝不改写为当天新增。metadata 分别提供历史批次、累计、今日发布时间、本期发布时间、今日新发现（不含历史种子）、今日详情补全数量。只有 `review_status=是` 计入有效量，待核验单独统计；表3/5继续仅汇总确认有效文章。

`reliable_interactions` 分别列 known_sum、known_records、unknown_records、complete_sum。全部未知时已知合计也为 null；部分未知时完整合计为 null。POMS 0 占位不会参与这些汇总。**0表示当前公开数据源未取得对应统计指标，不等同于平台真实值为0。**

当前 POMS schema 能接纳“搜狗URL + 本地账号关联ID + 提交占位统计”的基础数据。仍存在两项表达能力冲突：POMS 单独的0无法携带缺失状态；boolean无法完整表达待核验。解决方案是前端优先读取本地完整快照，或经后端组批准扩展 availability/review_status。没有伪造缺失指标，没有擅自修改 POMS schema，也没有自动上传。

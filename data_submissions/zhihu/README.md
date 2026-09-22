# 知乎采集数据提交说明

本目录只接收知乎采集组负责的 **表1—表5基础数据**；不在采集端执行“支持性 / 中性 / 问题性”或任何二级舆情分类。

## 正式监测口径

- 正式起算时间：\`2026-09-21T09:00:00+08:00\`，早于该时间的数据不得进入正式提交表。
- 采用“搜索放宽、入库严格”：搜索包含核心词、简称/常见表达、误写补漏、组合查询和带限定词的关联词；入库必须通过核心词、组合词或“关联词+限定词”校验。
- “宣传片”“主题片”“主场活动”“民族团结”等宽泛词不单独作为入库条件；“民族团结进步促进法”“铸牢中华民族共同体意识”“石榴花开”必须同时命中宣传周/2026/主场活动/日期等限定证据。
- 同一内容被多个关键词搜到时按内容ID（缺失时使用稳定去重键）合并；评论按评论ID合并。
- 一级评论、二级回复/楼中楼尽量完整采集并保留 \`parent_comment_id\`、\`root_comment_id\`、\`comment_level\`。
- 平台未公开的字段保持空白；禁止估算，也禁止把“未知/未公开”写成0。平台明确返回0时可保留真实0。
- 发布时间与采集时间分开保存；内容ID、评论ID、账号ID始终按文本保存。

## 更新频率

- 表1 \`table1_content.jsonl\`、表2 \`table2_comments.jsonl\`：每15分钟增量更新，已采集记录持续保留，同ID新的非空字段回写更新。
- 表3 \`table3_content_engagement.jsonl\`、表4 \`table4_comment_engagement.jsonl\`：按小时保留历史快照；同一小时内再次采集到点赞/评论等新值时，更新当前小时快照，不覆盖早先小时的快照。
- 表5 \`table5_accounts.jsonl\`：每轮对公开可得的新值做增量合并。
- 新日期的提交包会从上一个日期的提交包继承表1—表5，保证跨日增量数据不丢失。

## 提交目录

\`zhihu01\` 的输出目录为：

\`\`\`text
data_submissions/zhihu/YYYY-MM-DD_zhihu01/
\`\`\`

目录中固定包含：

- \`table1_content.jsonl\`
- \`table2_comments.jsonl\`
- \`table3_content_engagement.jsonl\`
- \`table4_comment_engagement.jsonl\`
- \`table5_accounts.jsonl\`
- \`manifest.json\`

这符合统一的 \`YYYY-MM-DD_姓名或节点名/\` 提交规范，不再把新采集数据提交到旧 \`results/\` 目录。

## 运行方式

知乎使用独立的采集组 runner，避免进入数据分析组的分类链：

\`\`\`bash
cp config/monitoring.zhihu.linux.example.json config/monitoring.zhihu.linux.local.json
python run_zhihu_collection.py --config config/monitoring.zhihu.linux.local.json --node-id zhihu01 --once
\`\`\`

Windows 或其他环境可传入对应的本地配置：

\`\`\`powershell
python .\run_zhihu_collection.py --config .\config\monitoring.local.json --node-id zhihu01
\`\`\`

单轮模式：

\`\`\`powershell
python .\run_zhihu_collection.py --config .\config\monitoring.local.json --node-id zhihu01 --once
\`\`\`

出现知乎官方登录、验证码或安全验证时，只进行人工官方验证，不绕过平台风控。

## 重点监测账号

重点账号名单来自 \`config/key_accounts.v3.catalog.json\`。关键词搜索中若命中这些账号，会在表5中按账号名称标记 \`is_key_account=true\` 和对应账号类型。

如需主动跑 creator 模式监测重点账号，请复制：

\`\`\`text
config/zhihu_key_accounts.example.json
\`\`\`

为本机文件：

\`\`\`text
config/zhihu_key_accounts.local.json
\`\`\`

仅在已经核验真实知乎主页或 \`creator_id\` 后填写并设置 \`enabled=true\`。不得根据媒体名称猜测知乎ID。

# SocialDataX WeChat MCP 能力与单篇实测

测试日期：2026-09-22（北京时间）。状态：**1篇文章、1个公众号的最小验证完成，已停止数据调用，等待用户决定是否扩大范围。**

## 结论

MCP配置和协议连接成功，账户凭据经余额/数据工具调用验证。18个工具中，2个服务微信公众号文章，15个服务微信视频号，1个查询积分。公众号详情与互动统计实测成功：能够补正文、文章标识、真实文章URL、官方公众号原始ID、简介，以及阅读/点赞/分享/收藏/评论/在看指标。本次仅这一个样本得到证实，不能外推所有文章一定可获取。

**当前服务没有暴露公众号关键词搜索、公众号发布文章列表、独立公众号主页资料、公众号评论/楼中楼工具。** 视频号工具要求视频号链接或`v2_...@finder`，不接受公众号`gh_*`或本地`local_wxacct_*`作为同一种账号标识。

表1和表3有明显补齐价值，表5只能部分改善；粉丝、关注、地区、账号类型等仍有缺口。建议获得其余文章的真实微信原文URL后再制定有预算上限的补采计划；本轮没有执行批量补采。

## 配置与连接

- Codex此前没有`socialdatax-wechat`，已按本机`codex mcp add --help`确认的方式添加到用户级配置。
- Streamable HTTP端点：`https://mcp.socialdatax.com/wechat/mcp`。
- 配置使用`bearer_token_env_var = "SOCIALDATAX_API_KEY"`，`http_headers = null`。密钥只保存在本机用户环境变量并在请求进程中读取，没有写入仓库、MCP配置明文或报告。
- 实返服务器`wechat_mcp`，版本`0.1.3`，协商协议`2025-03-26`；initialize HTTP 200、initialized HTTP 202、tools/list HTTP 200。
- 本次连接测试通过本地最小JSON-RPC客户端调用该MCP端点完成。现有Codex任务的已加载工具集合不会因修改配置自动证明热加载成功；新启动/刷新MCP连接的客户端需继承该环境变量。尚未声称本任务原生工具列表已经热加载。
- 配置依据：[OpenAI MCP文档](https://learn.chatgpt.com/docs/extend/mcp?translationFallback=zh-Hans)；协议依据：[Streamable HTTP规范](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)。

添加命令（不含密钥）：

```powershell
codex mcp add socialdatax-wechat --url https://mcp.socialdatax.com/wechat/mcp --bearer-token-env-var SOCIALDATAX_API_KEY
```

## 样本与定位

- 文章：**广西将组织实施首个民族团结进步宣传周活动**；公众号：**广西人大**。
- 本地内容ID：`wxmp_5162cb813075d2768ecca2b6`；有效性：是。
- 现有CSV与v2工作簿中标题、公众号名称一致；本次MCP返回也精确匹配。
- 微信原文：[单篇测试文章](https://mp.weixin.qq.com/s/LrcdrcTabJpCEkRJFXH1OQ)，由用户补充提供。
- 原批次16条记录只有搜狗跳转链接。尝试了一次对该标题/公众号的精确普通网页搜索，无结果；没有再次搜索四个监测关键词，也没有访问搜狗补字段。
- 工具要求真实公众号文章URL。**本测试不能证明SocialDataX能凭标题搜索到文章，也不能证明能解析搜狗临时跳转URL。**
- 原发布时间：`2026-09-21T16:51:55+08:00`；MCP返回：`2026-09-21T16:50:26+08:00`，相差89秒；原值不改动。
- 统计结果本地接收落盘时间：`2026-09-22T22:49:48+08:00`。服务没有单独返回统计截止时间/缓存时间，因此不能把这些值当作2026-09-21 17:00的历史指标，也不能保证其为严格实时值。未来补入表3/5须保留新的数据采集时间和来源。

## 实際调用与成本

| 顺序 | 工具 | 范围 | 服务确认扣费 | 返回余额 |
|---|---|---|---:|---:|
| 1 | socialdatax_get_points_balance | 当前API Key余额，仅一次 | 未单独返回cost | 50 |
| 2 | wechat_get_mp_article_detail_by_url | 用户提供的1篇文章，含该公众号基本信息 | 10 | 40 |
| 3 | wechat_get_mp_article_stats_by_url | 同一篇文章 | 10 | 30 |

共3次`tools/call`，其中2次文章数据调用。连同初始化、通知、tools/list，共6次MCP HTTP请求。数据工具明确确认消耗**20积分**，观测余额50→30。初始化、工具列表和余额查询没有单独的cost字段，不伪称服务对它们逐项确认免费。

没有调用任何搜索、独立用户资料、用户作品列表、评论、回复或转写工具。没有评论翻页，也没有为不匹配公众号范围的工具试错。用于文章的2次调用均成功，无服务失败重试。一次本地文件保护预检遇到Excel临时锁文件后已排除该锁文件；那次预检尚未发送网络请求。

## 逐字段对照

“提供”表示schema声明；“实际值”才是本次调用证据。这里的“可以补入”均是后续经确认实施的建议，**本轮没有修改Excel、CSV或POMS文件**。

| 字段 | 现有搜狗方案 | SocialDataX是否提供 | 实际测试值是否存在 | 是否可以补入表1—表5 | MCP tool名称 | 是否需要额外积分 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A. 微信文章稳定标识 | wxmp_本地内容ID | 是：biz/mid/idx/sn | biz=MzI4NDI0MTE5MA==；mid=2247635793；idx=1；sn=f7469d19a6273c00a77669e614fbd58a | 可建立表1稳定官方标识映射 | wechat_get_mp_article_detail_by_url | 本次详情共10积分 | 不是单一全局article_id；本轮不改现有主键/关联 |
| A. canonical文章URL | 搜狗带临时参数的跳转链接 | 是：article_url | https://mp.weixin.qq.com/s/LrcdrcTabJpCEkRJFXH1OQ | 可补表1原始内容链接 | wechat_get_mp_article_detail_by_url | 已包含在详情调用 | 输入原文链接由用户提供，服务返回相同规范链接；不能证明能把搜狗URL转换为原文URL |
| A. 标题 | 广西将组织实施首个民族团结进步宣传周活动 | 是：title | 广西将组织实施首个民族团结进步宣传周活动 | 可核对表1 | wechat_get_mp_article_detail_by_url | 已包含 | 与现有标题一致 |
| A. 完整正文 | 搜狗搜索摘要 | 是：content_text/content_html | 纯文本1347字符；HTML 34677字符 | 可补表1正文 | wechat_get_mp_article_detail_by_url | 已包含 | 服务返回正文，未逐字向微信页面独立复核；报告不复制整篇正文 |
| A. 发布时间 | 2026-09-21T16:51:55+08:00 | 是：publish_time | 2026-09-21T16:50:26+08:00 | 可核对/修正表1 | wechat_get_mp_article_detail_by_url | 已包含 | 比搜狗卡片推算时间早89秒，仍在09:00—17:00范围 |
| A. 公众号名称 | 广西人大 | 是：account.name | 广西人大 | 可核对表1/5 | wechat_get_mp_article_detail_by_url | 已包含 | 名称及文章标题同时精确匹配 |
| A/B. 官方公众号原始ID | local_wxacct_ca20997dd2d60c5d2de757b6 | 是：account.account_id | gh_ca592ddc004d | 可替代表1/5本地关联ID | wechat_get_mp_article_detail_by_url | 已包含 | 服务返回gh_原始ID；自定义微信号没有独立字段；须维护旧键映射并同步所有关联 |
| A. 原创/转载 | 未知 | 当前公众号schema无字段 | 未取得 | 不能补 | 无 | 无对应字段 | 不能由正文、标题或公众号名称猜测 |
| A. 阅读量 | 0接口占位 | 是：read_count | 442 | 表3阅读量/表5已采集文章阅读汇总 | wechat_get_mp_article_stats_by_url | 本次统计共10积分 | 采集时点为9月22日，非9月21日历史互动快照 |
| A. 点赞量 | 0接口占位 | 是：like_count | 5 | 表3点赞/表5点赞汇总 | wechat_get_mp_article_stats_by_url | 本次统计共10积分 | 采集时点为9月22日，非9月21日历史互动快照 |
| A. 分享量 | 0接口占位 | 是：share_count | 28 | 表3分享量 | wechat_get_mp_article_stats_by_url | 本次统计共10积分 | 分享不能同时复制到转发列 |
| A. 收藏量 | 0接口占位 | 是：collect_count | 5 | 表3收藏/表5收藏汇总 | wechat_get_mp_article_stats_by_url | 本次统计共10积分 | 采集时点为9月22日，非9月21日历史互动快照 |
| A. 评论量 | 0接口占位 | 是：comment_count | 0 | 表3评论量/表5评论汇总 | wechat_get_mp_article_stats_by_url | 本次统计共10积分 | 服务实返值；0不再是本次测试的未知占位 |
| A. 在看/推荐量 | 未设置独立字段 | 是：wow_count | 7 | 可另存原始扩展证据，不能添加POMS未知字段 | wechat_get_mp_article_stats_by_url | 本次统计共10积分 | 在看不能并入点赞 |
| A. 单独转发量 | 0接口占位 | 无独立repost_count | 未取得 | 不能直接补 | 无 | 无对应字段 | 仅有share_count=28；不能重复计算转发/分享 |
| B. 公众号主页URL | 未获取 | 公众号详情无profile/homepage_url | 未取得 | 不能补 | 无 | 无公众号主页工具 | 头像URL、文章URL不等于主页 |
| B. 帐号类型 | 未识别 | 无结构化帐号类型 | 仅简介说明官方公众号 | 需分类规则/人工确认 | 无 | 简介包含在详情 | 不把视频号用户信息能力误用于公众号 |
| B. 粉丝量 | 0接口占位 | 公众号schema无字段 | 未取得 | 不能补 | 无 | 无对应字段 | 原始缺失状态保留 |
| B. 关注量 | 0接口占位 | 公众号schema无字段 | 未取得 | 不能补 | 无 | 无对应字段 | 不根据文章互动反推 |
| B. 所属地区 / A. 帐号IP属地 | 未获取 / 平台公开数据源暂不提供 | 公众号schema无字段 | 未取得 | 不能补 | 无 | 无对应字段 | 不得从名称中的广西推断资料地区或IP属地 |
| B. 所属机构 | 未获取 | 无organization字段；有明确简介证据 | 广西壮族自治区人民代表大会常务委员会官方公众号 | 可在人工核验简介后补表5机构 | wechat_get_mp_article_detail_by_url | 已包含 | 机构名称有直接简介证据，尚未自动拆分/写回 |
| B. 简介 | 现有表1—5无简介列 | 是：account.signature | 广西壮族自治区人民代表大会常务委员会官方公众号 | 可保留证据；POMS不得添加schema外字段 | wechat_get_mp_article_detail_by_url | 已包含 | 不能当作公众号粉丝或关注信息 |
| C. comment_id | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 评论正文 | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 评论时间 | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 用户昵称 | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 用户ID | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 评论IP属地 | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 评论点赞量 | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 评论回复量 | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. parent_comment_id | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. root_comment_id | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |
| C. 楼中楼回复 | 无真实评论记录 | 未暴露公众号评论/回复工具 | 未调用/未取得 | 不能补表2/4 | 无（相似工具仅支持视频号） | 未调用，未消耗评论积分 | 评论量0不等于具备读取评论正文的能力 |

## 18个工具及schema审阅

所有工具的完整`inputSchema`、`outputSchema`、必填项、枚举和说明见同目录的 [SOCIALDATAX_WECHAT_TOOLS_SCHEMA.json](SOCIALDATAX_WECHAT_TOOLS_SCHEMA.json)。这是本次`tools/list`实返快照，未含API Key或MCP会话标识。下表为逐工具摘要。

| tool名称 | 平台范围 | 输入参数 | 顶层输出字段 |
|---|---|---|---|
| wechat_get_hot_search_list | 视频号，非公众号 | 无参数 | items, points |
| wechat_get_user_info_by_user_id | 视频号，非公众号 | user_id（必填） | user_id, name, avatar_url, bio, gender, ip_location, location, original_content_count, points |
| wechat_get_user_info_by_url | 视频号，非公众号 | url（必填） | user_id, name, avatar_url, bio, gender, ip_location, location, original_content_count, points |
| wechat_get_user_posted_videos_by_user_id | 视频号，非公众号 | user_id（必填）；page_token（可选） | items, next_page_token, points |
| wechat_get_user_posted_videos_by_url | 视频号，非公众号 | url（必填）；page_token（可选） | items, next_page_token, points |
| wechat_get_video_comment_replies_by_comment_id | 视频号，非公众号 | object_id（必填）；object_nonce_id（必填）；comment_id（必填）；page_token（可选） | items, next_page_token, points |
| wechat_get_video_comments_by_object_id | 视频号，非公众号 | object_id（必填）；object_nonce_id（必填）；page_token（可选） | items, next_page_token, comment_count, points |
| wechat_get_video_comments_by_url | 视频号，非公众号 | url（必填）；page_token（可选） | items, next_page_token, comment_count, points |
| wechat_get_video_detail_by_encrypted_object_id | 视频号，非公众号 | encrypted_object_id（必填） | object_id, object_nonce_id, content_type, description, topic_tags, cover_image_url, video, images, like_count, collect_count, comment_count, share_count, publish_time, ip_location, author, points |
| wechat_get_video_share_url_by_object_id | 视频号，非公众号 | object_id（必填） | share_url, points |
| wechat_get_mp_article_detail_by_url | 公众号 | url（必填） | biz, mid, idx, sn, title, account, publish_time, cover_image_url, description, article_url, content_text, content_html, image_urls, linked_articles, finder_video_cards, points |
| wechat_get_mp_article_stats_by_url | 公众号 | url（必填） | article_url, read_count, like_count, share_count, collect_count, comment_count, wow_count, points |
| wechat_get_video_detail_by_url | 视频号，非公众号 | url（必填） | object_id, object_nonce_id, content_type, description, topic_tags, cover_image_url, video, images, like_count, collect_count, comment_count, share_count, publish_time, ip_location, author, points |
| wechat_submit_video_speech_text_by_video_url | 视频号，非公众号 | video_url（必填） | job_id, status, is_terminal, platform, content_id, source_id, content_type, content_meta, transcript, error, next_poll_after_seconds, next_action, message |
| wechat_submit_video_speech_text_by_encrypted_object_id | 视频号，非公众号 | encrypted_object_id（必填） | job_id, status, is_terminal, platform, content_id, source_id, content_type, content_meta, transcript, error, next_poll_after_seconds, next_action, message |
| wechat_get_video_speech_text_job | 视频号，非公众号 | job_id（必填） | job_id, status, is_terminal, platform, content_id, source_id, content_type, content_meta, transcript, error, next_poll_after_seconds, next_action, message |
| wechat_search_videos | 视频号，非公众号 | keyword（必填）；page_token（可选）；sort_type（可选）；duration_range（可选） | items, next_page_token, points |
| socialdatax_get_points_balance | 账户积分 | 无参数 | 整数值对象（实返balance） |

公众号详情工具的`account`子对象包含`name/account_id/avatar_url/signature`，满足本次1个公众号的基本信息验证；没有独立公众号资料工具可继续取得粉丝/关注等字段。公众号统计工具的6个统计值schema均允许null，本次样本碰巧全部有值，并不保证其他文章同样完整。

视频号评论工具输出`comment_id/content/publish_time/like_count/reply_count/ip_location/author`，回复工具输出`reply_to_comment_id/reply_to_user_id`等，未直接定义`parent_comment_id/root_comment_id`。这些都是**视频号schema能力，未实测，也不属于微信公众号留言能力**。本轮不因此花积分或制造评论记录。

## 对现有表1/3/5的实际价值及补采条件

1. 表1：详情工具可补正文、官方账号原始ID、规范文章URL，提供文章标识并校正发布时间；原创/转载和账号IP仍未取得。
2. 表3：本样本可将阅读/点赞/分享/收藏的占位0分别替换为442/5/28/5；评论返回0是服务实际返回的统计值，不再是缺失占位。转发没有独立字段，在看7不能并入点赞5。
3. 表5：`gh_ca592ddc004d`可替代该公众号本地关联键，但迁移必须同步表1/5及所有关联引用。简介对所属机构提供明确证据，需人工/规则核验后写入；粉丝、关注、主页、地区、结构化类型依然缺失。文章级统计只能按本节点已采集文章范围汇总，不能称为账号全量统计。
4. 表2/4：未暴露公众号评论读取或楼中楼工具，当前仍无法补齐，评论数量0不代表取得评论正文的能力。
5. 费用：本次详情10积分、统计10积分。如果未来同价、每篇各调用一次且不重试，16篇共约320积分；已验证1篇，再补剩余15篇约300积分。仅更新其余15篇统计也约150积分。当前余额30不足以按此估算完成剩余全部文章；这是基于本次样本的条件估算，不是服务方锁定报价。
6. 建议：**值得考虑有真实原文URL、有预算限制的定向补采；不建议直接把它当作公众号搜索/评论/粉丝资料的完整替代。** 当前只有1篇实测，尚未证明可以普遍解决全部占位。需要用户确认范围与预算后才实施。

## 证据和不变性

- `data/wechat_mp/socialdatax_smoke/tools.json`：原始工具目录。
- `call_1.json`：余额；`call_2.json`：单篇详情（含原始正文）；`call_3.json`：单篇统计。
- `selected_sample.json`：CSV与实际v2工作簿对应记录的只读对照。
- `ledger.json`：6次MCP请求的方法、结果和时间，不记录认证头。
- 已对原交付目录的正常文件计算前后SHA-256：**19个文件全部不变**，排除了Excel临时锁文件。原JSONL、v2工作簿、五份CSV及五份POMS JSON均未修改。
- 未请求POMS服务器、未commit、未push，未扫描其他账号或补采其余15篇。

本次凭据及会话文件不列入报告附件，不将视频号数据混入微信公众号表。

知乎数据放这里。每位同学请在本目录下建立自己的日期/节点子目录。

`zhihu01` 的正式运行输出写入 `zhihu01/YYYY-MM-DD/`，其中：

- `table1_content.jsonl`：发布内容基础信息；
- `table2_comments.jsonl`：一级评论和楼中楼，保留 `parent_comment_id`、`root_comment_id` 与 `comment_level`；
- `table3_content_engagement.jsonl`：内容互动快照；
- `table4_comment_engagement.jsonl`：评论互动快照；
- `table5_accounts.jsonl`：公开可取得的账号信息；
- `manifest.json`：本轮关键词、接收/排除数量及采集状态。

本目录只接收通过正式主题和监测起点校验的数据；未公开字段必须为空。知乎重点媒体账号只有在提供可核验的知乎主页或帐号 ID 后才能启用，不能用媒体名称猜测帐号。

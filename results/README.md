# 自动监测结果目录

本目录只用于保存**脱敏聚合结果**，供团队协作和 GPT/GitHub 直接读取。

自动同步脚本只允许写入/提交 `results/`，不会提交：

- 原始评论/帖子正文
- 账号 Cookie、登录态、browser_data
- API Key / `.env`
- 本地 SQLite 数据库
- 原始用户 ID

运行：

```powershell
cd E:\realtime-opinion-monitor
.\scripts\start_results_sync_windows.ps1 -Push
```

默认每 15 分钟生成并同步一次：

- `results/latest_summary.json`：当前聚合状态
- `results/daily/YYYY-MM-DD.json`：当天最新快照

汇总内容包括平台量、地区覆盖、语言分布、少数民族语言分布、v2 分类、内容来源类型、互动量和最近一轮运行状态，不含原始文本。

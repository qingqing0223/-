# 学生分平台部署与 GitHub 汇总

适用于当前项目接入的 7 个平台：

- `xhs` 小红书
- `dy` 抖音
- `ks` 快手
- `bili` B站
- `wb` 微博
- `toutiao` 今日头条
- `zhihu` 知乎

## 1. 本次正式监测口径

本轮任务为：

- 事件：`2026年民族团结进步宣传周预热阶段舆情监测`
- 正式统计起点：`2026-09-16 00:00:00 +08:00`
- 今日结果日期：`2026-09-16`
- 目标轮询周期：300 秒（约 5 分钟）

平台搜索结果中可能返回 9 月 16 日 00:00 以前的旧内容。程序可以看到这些结果，但正式分类与今日聚合统计会按配置中的 `monitoring_start_time` 过滤明确早于统计起点的内容，避免旧数据混入今日预热统计。

学生机本地数据也单独放入当天目录：

```text
<工作盘>\MediaCrawlerData\2026-09-16_promotion_week_<platform>\
```

GitHub 今日汇总统一放入：

```text
results/2026-09-16/
```

不要与历史测试结果、民族团结进步促进法历史数据或其他热点事件数据混用。

## 2. 设计目标

每台学生电脑只负责一个平台：

```text
平台公开内容
→ MediaCrawler
→ 增量去重
→ 9月16日00:00正式统计起点过滤
→ 志鹏 v2 分类
→ 本机脱敏聚合
→ results/2026-09-16/nodes/<platform>/<node>.json
→ GitHub
```

学生机默认不需要部署苏琦大屏，因此比完整三方联调环境更轻量。GitHub 只接收聚合统计，不上传原始正文、账号名、URL、Cookie、数据库或 API Key。

## 3. GitHub 权限

如果需要学生电脑自动 push 到同一个仓库，每位同学应使用自己的 GitHub 账号，并由仓库管理员授予写权限。不要共享仓库管理员的个人访问令牌，也不要把任何 token/API Key 写入仓库或微信群。

不同电脑写入不同的 node 文件，脚本在 push 前会自动执行 `git pull --rebase --autostash`，并对并发 push 做有限重试，以降低多机同时上传产生的冲突。

## 4. 第一次安装

学生操作手册会自动选择本机工作盘：优先 E 盘，没有 E 盘则 D 盘，再没有则 C 盘。项目目录、MediaCrawler 目录和数据目录必须使用同一工作盘。

本项目：

```text
https://github.com/qingqing0223/-
```

学生首次部署完成后，本机配置文件为：

```text
config/monitoring.local.json
```

它由 `config/monitoring.student.windows.json` 复制生成，并保留本次正式监测的：

```text
event_id
event_name
monitoring_start_time = 2026-09-16T00:00:00+08:00
results_date = 2026-09-16
```

同时根据学生电脑实际工作盘修改 `media_crawler_root` 和 `data_root`。该本地配置不提交 GitHub。

之后在本机 PowerShell 中设置经授权的 DashScope API Key。Key 只保存在当前 PowerShell 会话中，不要提交到 GitHub。

部署自检：

```powershell
python .\scripts\preflight.py --config .\config\monitoring.local.json
```

## 5. 启动一个平台并自动向 GitHub 汇总

例如 B站：

```powershell
.\scripts\start_student_platform_windows.ps1 `
  -Platform bili `
  -NodeId bili01 `
  -Config .\config\monitoring.local.json `
  -PushGithub
```

其他平台只替换平台代码和 NodeId。

该命令会：

1. 启动本平台 5 分钟目标周期监测；
2. 对明确早于 2026-09-16 00:00 的内容从正式今日统计中排除；
3. 普通网络/进程错误由安全 watchdog 处理；
4. 遇到平台官方验证码/登录要求时停止自动重试，等待人工处理；
5. 另开一个结果同步窗口，每 5 分钟生成一次本机本平台脱敏聚合结果并尝试 push 到 GitHub。

今日结果路径示例：

```text
results/2026-09-16/nodes/bili/bili01.json
results/2026-09-16/nodes/zhihu/zhihu01.json
results/2026-09-16/nodes/xhs/xhs01.json
```

## 6. 17:00 汇总

只要各节点文件已经成功 push，集中汇总端无需拿学生电脑上的原始文件。直接读取 GitHub：

```text
results/2026-09-16/nodes/
```

即可按平台查看：

- 9 月 16 日 00:00 以后纳入正式统计的唯一记录数
- 过滤掉的明确早于统计起点的记录数
- 地区覆盖
- 语言/少数民族语言分布
- v2 `status/type`
- 来源类型
- 内容类型
- 点赞/评论/分享
- B站附加的播放/收藏/弹幕/投币字段（平台有数据时）
- 最近一轮 crawler 状态、耗时、分类数量等

## 7. 注意事项

- GitHub 是准实时汇总通道，不是原始数据仓库。
- 默认同步周期 300 秒。
- 学生电脑必须有稳定网络，并完成各自平台的正常登录。
- 小红书/微博等平台可能要求人工验证码或重新登录；不要用脚本绕过平台验证。
- 如果 `git push` 返回权限错误，先检查该同学自己的 GitHub 账号是否已被授予仓库写权限。
- 如果同一个平台安排多台电脑，给每台电脑不同 `NodeId`，例如 `xhs01`、`xhs02`。
- 学生不要自行修改 `monitoring_start_time`、`results_date`、关键词、轮询周期或结果目录。
- 电脑重启后需要重新在新的 PowerShell 会话中输入 DashScope API Key，再重新执行本平台启动命令。

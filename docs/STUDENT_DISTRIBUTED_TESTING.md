# 学生分平台部署与 GitHub 汇总

适用于 7 个 MediaCrawler 支持的平台：

- `xhs` 小红书
- `dy` 抖音
- `ks` 快手
- `bili` B站
- `wb` 微博
- `tieba` 百度贴吧
- `zhihu` 知乎

## 1. 设计目标

每台学生电脑只负责一个平台：

```text
平台公开内容
→ MediaCrawler
→ 增量去重
→ 志鹏 v2 分类
→ 本机脱敏聚合
→ results/nodes/<platform>/<node>.json
→ GitHub
```

学生机默认不需要部署苏琦大屏，因此比完整三方联调环境更轻量。GitHub 只接收聚合统计，不上传原始正文、账号名、URL、Cookie、数据库或 API Key。

## 2. GitHub 权限

如果需要学生电脑自动 push 到同一个仓库，每位同学应使用自己的 GitHub 账号，并由仓库管理员授予写权限。不要共享仓库管理员的个人访问令牌，也不要把任何 token/API Key 写入仓库或微信群。

不同电脑写入不同的 node 文件，脚本在 push 前会自动执行 `git pull --rebase --autostash`，并对并发 push 做有限重试，以降低多机同时上传产生的冲突。

## 3. 第一次安装

同学先 clone 本仓库，然后进入仓库目录：

```powershell
cd E:\realtime-opinion-monitor
```

执行：

```powershell
.\scripts\student_setup_windows.ps1
```

该脚本会检查 Git/Python/uv，并在 `E:\MediaCrawler_clean` 不存在时自动 clone MediaCrawler，然后同步其依赖并安装本项目分类包。

之后在本机 PowerShell 中设置经授权的 DashScope API Key。Key 只保存在本机环境变量中，不要提交到 GitHub。

最后执行：

```powershell
python .\scripts\preflight.py
```

## 4. 启动一个平台并自动向 GitHub 汇总

例如 B站：

```powershell
.\scripts\start_student_platform_windows.ps1 -Platform bili -NodeId bili01 -PushGithub
```

其他平台只替换平台代码即可。

该命令会：

1. 启动本平台 5 分钟目标周期监测；
2. 普通网络/进程错误由安全 watchdog 处理；
3. 遇到平台官方验证码/登录要求时停止自动重试，等待人工处理；
4. 另开一个结果同步窗口，每 5 分钟生成一次本机本平台脱敏聚合结果并尝试 push 到 GitHub。

结果路径示例：

```text
results/nodes/bili/bili01.json
results/nodes/zhihu/zhihu01.json
results/nodes/xhs/xhs01.json
```

## 5. 5 点汇总

只要各节点文件已经成功 push，集中汇总端无需拿学生电脑上的原始文件。直接读取 GitHub `results/nodes/` 即可按平台查看：

- 唯一记录数
- 地区覆盖
- 语言/少数民族语言分布
- v2 `status/type`
- 来源类型
- 内容类型
- 点赞/评论/分享
- B站附加的播放/收藏/弹幕/投币字段（平台有数据时）
- 最近一轮 crawler 状态、耗时、分类数量等

## 6. 注意事项

- GitHub 是准实时汇总通道，不是原始数据仓库。
- 默认同步周期 300 秒。
- 学生电脑必须有稳定网络，并完成各自平台的正常登录。
- 小红书/微博等平台可能要求人工验证码或重新登录；不要用脚本绕过平台验证。
- 如果 `git push` 返回权限错误，先检查该同学自己的 GitHub 账号是否已被授予仓库写权限。
- 如果同一个平台安排多台电脑，给每台电脑不同 `NodeId`，例如 `xhs01`、`xhs02`。

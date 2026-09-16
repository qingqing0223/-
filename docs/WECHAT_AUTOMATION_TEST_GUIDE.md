# 微信公众号 / 视频号自动化监测实验链

本实验用于 **2026年民族团结进步宣传周预热阶段舆情监测**。正式统计起点为 `2026-09-16T00:00:00+08:00`。

## 1. 当前方案

微信生态不修改 MediaCrawler 核心，而作为两条独立采集适配器接入已有分析链：

```text
微信公众号（wechat_mp）
  → 搜狗微信搜索公开结果 + Chrome 可见浏览器
  → JSONL
  → 增量去重
  → 志鹏 v2
  → GitHub 脱敏汇总

微信视频号（wechat_channels）
  → Windows 官方微信客户端 + UI Automation
  → 视频号关键词搜索公开可见结果
  → JSONL
  → 增量去重
  → 志鹏 v2
  → GitHub 脱敏汇总
```

安全边界：不逆向微信私有协议，不注入微信进程，不解密网络流量，不绕过验证码或安全验证。遇到平台官方登录、验证码或安全验证时由人工正常完成。

## 2. 第一次安装

先确保本机已安装并能正常使用：

- Git
- Python 3.10+
- Google Chrome（公众号公开搜索链）
- 官方 Windows 微信客户端 4.1.6+（视频号链）

更新本项目：

```powershell
cd E:\realtime-opinion-monitor
git pull --ff-only
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\setup_wechat_windows.ps1
```

如果项目位于 D 盘或 C 盘，脚本会沿用项目所在盘，不要求必须是 E 盘。

安装完成后会生成本机配置：

```text
config/monitoring.wechat.local.json
```

该文件已加入 `.gitignore`，不会提交到 GitHub。

## 3. 设置志鹏 v2 所需 API Key

不要把 API Key 写进脚本、微信群或 GitHub。每次新开 PowerShell 后，在当前窗口执行：

```powershell
$secureKey = Read-Host "请输入DASHSCOPE_API_KEY" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$env:DASHSCOPE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
```

## 4. 微信公众号：先跑单轮验收

```powershell
cd E:\realtime-opinion-monitor
.\scripts\start_wechat_platform_windows.ps1 `
  -Platform wechat_mp `
  -NodeId wechatmp01 `
  -Config .\config\monitoring.wechat.local.json `
  -Once
```

程序会使用可见 Chrome 依次搜索配置中的 6 个宣传周关键词。若出现搜狗官方验证码/安全验证，程序会等待人工处理，不会绕过验证。

成功时重点看：

```text
state = SUCCESS
records_collected > 0（有公开搜索结果时）
classified_records >= 0
filtered_before_start >= 0
```

本地结果目录：

```text
<项目所在盘>\MediaCrawlerData\2026-09-16_promotion_week_wechat_mp\
```

## 5. 微信视频号：先跑单轮验收

先启动官方 Windows 微信客户端并完成正常登录，确认手工能打开“视频号”和搜索框。

然后执行：

```powershell
cd E:\realtime-opinion-monitor
.\scripts\start_wechat_platform_windows.ps1 `
  -Platform wechat_channels `
  -NodeId channels01 `
  -Config .\config\monitoring.wechat.local.json `
  -Once
```

程序会通过 Windows UI Automation 打开视频号、输入关键词并读取当前界面公开可见的搜索结果文字。不同微信客户端版本的 UI 树可能存在差异，因此第一次必须做真机验收。

可能状态：

```text
SUCCESS                已完成本轮
LOGIN_REQUIRED         微信需要重新登录
LOGIN_OR_UI_REQUIRED   未检测到可用的视频号搜索界面
UI_NOT_READY            当前微信 UI 结构与适配器不一致，需要根据截图/日志调整选择器
COLLECTOR_ERROR         其他采集错误
```

本地结果目录：

```text
<项目所在盘>\MediaCrawlerData\2026-09-16_promotion_week_wechat_channels\
```

## 6. 单轮通过后再开启持续运行 + GitHub 汇总

公众号：

```powershell
.\scripts\start_wechat_platform_windows.ps1 `
  -Platform wechat_mp `
  -NodeId wechatmp01 `
  -Config .\config\monitoring.wechat.local.json `
  -PushGithub
```

视频号：

```powershell
.\scripts\start_wechat_platform_windows.ps1 `
  -Platform wechat_channels `
  -NodeId channels01 `
  -Config .\config\monitoring.wechat.local.json `
  -PushGithub
```

初始轮询频率采用保守值：

- 微信公众号：30 分钟一轮
- 微信视频号：15 分钟一轮

先验证稳定性，不建议一开始提高请求频率。

GitHub 脱敏汇总位置：

```text
results/2026-09-16/nodes/wechat_mp/wechatmp01.json
results/2026-09-16/nodes/wechat_channels/channels01.json
```

GitHub 只保存聚合统计，不上传原始正文、账号名、原始链接、Cookie、微信登录信息或 API Key。

## 7. 第一次真机测试需要回传什么

如果失败，只需要提供：

1. PowerShell 最后一屏完整截图；
2. 程序打开的微信/Chrome 当前界面截图（注意自行遮挡个人聊天、头像等无关个人信息）；
3. `state` / `error` 字段；
4. 微信客户端版本（视频号测试时）。

不要发送 Cookie、API Key、二维码登录凭据或个人聊天内容。

# 宣传周舆情监测：私有原始 JSONL 归档设置

## 目的

代码仓库 `qingqing0223/-` 当前是公开仓库，只用于代码、聚合结果和脱敏诊断。完整帖子/评论 JSONL、评论原文和平台公开粗粒度 IP 属地不应直接提交到公开仓库。

为便于后续排障和复核，7个平台学生节点可以把完整 MediaCrawler JSONL 自动同步到一个**单独的、访问受控的 PRIVATE GitHub 仓库**。

## 归档频率

- 监测新内容发现：300 秒（5分钟）目标周期。
- 公开节点摘要同步：固定 300 秒。
- 私有原始 JSONL 归档同步：固定 300 秒。
- 原始归档同步不改变采集节奏；它在独立 PowerShell 窗口运行。

## 私有仓库要求

1. 由负责人在 GitHub 新建一个 Private repository，例如 `promotion-week-raw-private`。
2. 只给项目负责人和7位平台监测同学访问权限。
3. 不要把该仓库改成 Public。
4. 每位学生在自己的 Windows 电脑上克隆一次，例如：

```powershell
git clone <PRIVATE_REPO_URL> E:\PromotionWeekRawArchive
```

5. 首次 clone/push 时按 GitHub 正常认证流程登录。不要把 PAT、Cookie、浏览器登录态或任何密钥写进本项目配置文件。

## 启动方式

在代码仓库根目录运行：

```powershell
$env:PROMOTION_RAW_ARCHIVE_REPO="E:\PromotionWeekRawArchive"
.\scripts\start_student_platform_windows.ps1 -Platform <平台代码> -NodeId <节点ID> -Config .\config\monitoring.local.json -PushGithub -ArchiveRaw -RawArchiveRepo "E:\PromotionWeekRawArchive" -PrivateRepoConfirmed
```

平台代码：`xhs`、`dy`、`ks`、`bili`、`wb`、`toutiao`、`zhihu`。

## 私有仓库中保存什么

归档程序 `scripts/archive_raw_runs_to_git.py` 只从每个平台数据根目录的 `raw_runs/**/*.jsonl` 读取原始 JSONL，并额外复制 `status/latest_status.json`。

归档结构示例：

```text
nodes/
  <NodeId>/
    <platform>/
      manifest.json
      latest_status.json
      20260917/
        <cycle>/
          <platform_timestamp>/
            search_contents_*.jsonl.gz
            search_comments_*.jsonl.gz
```

每个文件记录：

- 未压缩原文件 SHA-256；
- JSONL 行数；
- 未压缩字节数；
- 原始相对路径；
- 归档时间。

## 明确不归档的内容

以下内容禁止上传到原始数据 Git 仓库：

- Cookie；
- browser_data 浏览器目录；
- 登录二维码/登录态；
- 密钥、Token、DASHSCOPE_API_KEY；
- 本机浏览器 Profile；
- 真实 IP 地址或精确定位数据；
- 截图和个人本地文件。

系统只保留平台页面公开展示的粗粒度 `IP属地`（如“北京”“山东”），且只在平台实际返回时保存。

## 排障时怎么取数据

负责人可以直接从私有仓库按：

`NodeId -> platform -> date -> cycle`

找到对应 `.jsonl.gz`，并用同目录 `manifest.json` 校验行数和 SHA-256。这样可以判断问题发生在：

1. 平台/MediaCrawler 根本没有返回；
2. 原始 JSONL 已返回但字段结构变化；
3. 标准化阶段丢失；
4. 去重或时间过滤；
5. 分类器；
6. 大屏推送。

## 5分钟实时性说明

“5分钟”首先约束**新内容发现与节点状态同步**。历史全量回填必须与实时监测分开，只运行一次；评论深采采用持久队列逐轮处理，避免为了某个超大评论区反复扫描全部历史内容。若平台出现官方验证码、登录失效、网络异常或单轮处理超过目标时长，状态文件会记录 SLA 异常，系统不会通过并发叠加或绕过平台验证来强行维持频率。

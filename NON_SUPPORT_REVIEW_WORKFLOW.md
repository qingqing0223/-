# 宣传周舆情三分类与非支持人工复核流程

## 一、自动三分类

学生节点完成采集和标准化后，会自动调用志鹏 v2.2 分类服务。系统保留原始二层分类：

- `status=normal`：正常/支持信息
- `status=attention`：中性信息
- `status=problematic`：问题信息

同时新增统一三分类字段 `tri_class`，用于学生复核和专报统计：

| v2 status | tri_class | 中文 |
| --- | --- | --- |
| normal | support | 支持 |
| attention | neutral | 中性 |
| problematic | non_support | 非支持 |

二级 `type` 不丢失，仍用于区分 consultation、criticism、fairness_dispute 等细分类。

## 二、公开代码仓库自动回传什么

每个学生节点保持 `-PushGithub` 后，每 300 秒自动回传：

```text
results/YYYY-MM-DD/nodes/<platform>/<node_id>.json
```

其中包括：

- 三分类统计 `tri_class`
- 评论三分类统计 `comment_tri_class`
- 原始 v2 `status/type`
- 脱敏记录指纹中的 `tri_class`
- 平台/地区/语言/来源类型/评论层级等聚合字段

公开代码仓库继续禁止上传评论/帖子原文、原始用户 ID、Cookie、真实 IP 和完整原始 URL。

## 三、非支持内容为什么必须走 PRIVATE GitHub 仓库

人工复核需要看到公开原文和公开来源链接。代码仓库是 Public，因此这些内容不直接写入公开仓库。

请单独建立访问受控的 Private GitHub 仓库，例如：

```text
promotion-week-review-private
```

只给项目负责人和参与复核的学生访问权限。

每台学生电脑克隆一次，例如：

```powershell
git clone <PRIVATE_REPO_URL> E:\PromotionWeekReview
```

第一次 push 按 GitHub 正常认证流程登录，不要把 PAT、Cookie 或 API Key 写入仓库。

## 四、学生一条命令启动“采集 + 分类 + 公开汇总 + 私有复核队列”

关闭旧监测和旧同步窗口，拉最新代码后执行：

```powershell
.\scripts\final_student_update_windows.ps1 `
    -Platform <平台代码> `
    -NodeId <节点ID> `
    -Config .\config\monitoring.local.json `
    -Start `
    -ReviewSync `
    -ReviewRepo "E:\PromotionWeekReview" `
    -PrivateReviewRepoConfirmed
```

平台代码：`xhs`、`dy`、`ks`、`bili`、`wb`、`toutiao`、`zhihu`。

启动后会有三个核心后台流程：

1. 平台实时采集与志鹏 v2 分类；
2. 公开 GitHub 节点摘要每 300 秒自动同步；
3. PRIVATE 非支持人工复核队列每 300 秒自动同步。

## 五、私有复核仓库文件

每个学生节点会自动生成：

```text
nodes/<node_id>/<platform>/
  latest_non_support_review_queue.json
  non_support_manual_review.csv
  confirmed_non_support.json
```

### latest_non_support_review_queue.json

模型自动判定为 `non_support` 的待复核记录。包含人工复核所需的公开文本、上下文、公开来源 URL、发布时间、粗粒度 IP 属地、模型 status/type 等。

### non_support_manual_review.csv

学生用 Excel 打开此文件，人工复核后填写：

- `manual_label`：`support` / `neutral` / `non_support`
- `manual_note`：简短说明
- `reviewer`：复核人
- `reviewed_at`：复核时间

不要修改 `review_id`。

同步程序每 300 秒刷新新记录时，会按 `review_id` 保留已经填写的人工复核结果。

### confirmed_non_support.json

系统根据 CSV 自动生成，只收录：

```text
manual_label = non_support
```

的人工确认记录。负责人写专报时优先读取这个文件，而不是直接把模型初判结果当最终结论。

## 六、数据流

```text
平台采集
  ↓
标准化
  ↓
志鹏 v2.2
  ↓
normal / attention / problematic
  ↓
support / neutral / non_support
  ├─→ Public GitHub：聚合统计 + 脱敏指纹
  └─→ Private GitHub：non_support 待复核原文
                       ↓
                   学生人工复核
                       ↓
                confirmed_non_support.json
                       ↓
                    专报素材
```

## 七、隐私边界

Private review repo 只用于项目组内部人工复核。允许保存平台公开文本和公开来源 URL，但仍不保存：

- Cookie / Token / API Key
- 浏览器 Profile / 登录态
- 原始平台用户 ID
- 真实网络 IP
- 精确经纬度或精确定位

IP 属地只保留平台公开展示的粗粒度地区标签。

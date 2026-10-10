# 学生端正式监测最终操作手册（冻结版）

适用平台：小红书（xhs）、抖音（dy）、快手（ks）、B站（bili）、微博（wb）、今日头条（toutiao）、知乎（zhihu）。

> 本版作为 2026-09-16 起宣传周预热监测的学生端冻结版本。学生端后续不自行改代码、不自行安装未知包、不修改关键词和采集参数。平台官方登录、验证码、滑块或安全验证仍需人工完成，不绕过平台验证。

## 一、最终监测口径

正式起算时间：`2026-09-16T00:00:00+08:00`。

统一核心关键词：

1. 民族团结进步宣传周
2. 2026年民族团结进步宣传周
3. 首个民族团结进步宣传周
4. 民族团结进步宣传周启动
5. 民族团结进步宣传周活动
6. 民族团结进步宣传周主场活动
7. 2026年民族团结进步宣传周主场活动
8. 民族团结进步宣传周主题宣传片
9. 民族团结进步倡议
10. 民族团结进步倡议书
11. 促进民族团结进步，奋进伟大复兴征程

程序会在此基础上自动增加简称、常见误写、组合检索和关联词补漏；学生不需要手工改配置。统一执行“搜索放宽、入库严格”：宽泛检索词只用于召回候选，正式数据必须由内容本身通过主题相关性过滤。关联词如“民族团结进步促进法”“铸牢中华民族共同体意识”“石榴花开”不得单独作为正式入库依据。


## 二、本版已统一打开的能力

- 关键词搜索与持续分页（平台自然结束优先，有限安全上限兜底）
- 跨轮次去重与每5分钟增量轮询
- 帖子/视频公开详情与互动量字段
- 一级评论抓取
- 楼中楼/二级回复抓取
- 评论父评论、根评论关系标准化
- 平台公开展示的 IP 属地/地区字段读取（不获取真实IP）
- 帖子、视频、评论统一进入志鹏 v2 分类
- v2.2 L1 为 `normal / attention / problematic`，其中 `attention`的中文名称是“中性信息”，L2 为 `neutral / information_gap / consultation`
- 报告层仍保留 `support / neutral / attention / non_support` 四个汇总桶：`attention/neutral` 进入 neutral 桶，其他两个 attention 子类进入 attention 桶
- 中文及少数民族语言识别
- 视频/帖子来源类型识别
- 视频 ASR/OCR 字段若存在则纳入分析，并在汇总中显示多模态完整度；学生端本版不要求自行安装额外 ASR/OCR 软件
- 公开发布账号的聚合统计（不上传原始正文和URL）
- GitHub 节点结果自动同步
- 普通网络/进程异常 watchdog 恢复；登录/验证状态停止并等待人工处理

## 三、升级前必须做

关闭旧的“主监测 PowerShell”和旧的“GitHub同步 PowerShell”。不要让旧进程与新版同时运行。

进入项目目录（按自己电脑实际盘符）：

```powershell
cd E:\realtime-opinion-monitor
```

把代码强制对齐到 GitHub 最新 main；本机 `monitoring.local.json` 是忽略文件，不会被此操作删除：

```powershell
git rebase --abort 2>$null
git stash push -u -m "before-final-update"
git fetch origin
git switch -C main origin/main
```

如果当前 PowerShell 还没有 `DASHSCOPE_API_KEY`，先按组内统一方式设置；不要把 API Key 截图、提交到 GitHub 或写入公开文件。

## 四、每个平台只执行一条最终升级+启动命令

小红书：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform xhs -NodeId xhs01 -Config .\config\monitoring.local.json -Start
```

抖音：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform dy -NodeId dy01 -Config .\config\monitoring.local.json -Start
```

快手：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform ks -NodeId ks01 -Config .\config\monitoring.local.json -Start
```

B站第一台：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform bili -NodeId bili01 -Config .\config\monitoring.local.json -Start
```

B站第二台：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform bili -NodeId bili02 -Config .\config\monitoring.local.json -Start
```

微博：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform wb -NodeId wb01 -Config .\config\monitoring.local.json -Start
```

今日头条：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform toutiao -NodeId toutiao01 -Config .\config\monitoring.local.json -Start
```

知乎：

```powershell
.\scripts\final_student_update_windows.ps1 -Platform zhihu -NodeId zhihu01 -Config .\config\monitoring.local.json -Start
```

同一平台多台电脑必须使用不同 NodeId，禁止共用同一个 NodeId。

## 五、正常运行时不要做什么

- 不要重复执行启动命令。
- 不要同时开两套同平台监测。
- 不要自行 `pip install` 不明包。
- 不要自行修改 `monitoring.local.json` 中的关键词、评论开关或分页上限。
- 不要关闭主采集窗口、GitHub同步窗口或已登录的浏览器。
- 不要绕过验证码、滑块、安全验证；出现后人工完成官方验证。

## 六、完成一轮后验收

另开一个 PowerShell，在项目目录运行（把平台代码换成自己负责的平台）：

```powershell
python .\scripts\verify_full_monitoring_cycle.py --platform ks --config .\config\monitoring.local.json
```

重点看：

- `summary_schema_version` 应为 6
- `last_cycle.crawler_state` 最好为 `SUCCESS`
- `last_cycle.ingest_comments` 应为 `true`
- `last_cycle.comment_input_file_count`：大于0说明上游已生成评论JSONL
- `comments.comment_records`：大于0说明评论已进入标准化和分类链
- `comments.root_comment_records`：一级评论数
- `comments.reply_comment_records`：楼中楼/回复数
- `comments.parent_linked_comment_records`：成功建立父子关系的回复数
- `comments.comment_regions`：评论公开IP属地汇总（平台有返回时才会出现）
- `comments.comment_attitude`：评论支持/中性/关注/非支持分类汇总
- `records.regions`：作品/评论公开地区汇总
- `records.attitude`：全部记录态度汇总
- `public_accounts`：公开发布账号的聚合统计
- `video_analysis`：视频ASR/OCR字段完整度

如果 `comment_input_file_count=0`，说明评论采集开关已经打开，但平台/MediaCrawler这一轮没有生成评论文件；这与“后处理漏掉评论”是不同问题，应把验收 JSON 和主窗口最后日志发给负责人，不自行修改代码。

## 七、GitHub最终结果位置

每台学生机每5分钟更新自己的独立节点文件：

```text
results/2026-09-16/nodes/<platform>/<node_id>.json
```

节点汇总包括：作品/视频数、一级评论、楼中楼、评论父子关联、公开地区、互动量、语言、来源类型、v2态度、评论态度、公开发布账号统计和视频多模态完整度。GitHub 不上传原始帖子/评论正文和URL。

## 八、学生只需反馈的异常

真正需要人工反馈的情况：`VERIFY_REQUIRED`、`LOGIN_REQUIRED`、连续 `NETWORK_ERROR`、`preflight required_failures > 0`、`comment_input_file_count=0` 且已确认平台页面存在大量可见评论、或者 GitHub `git.ok=false`。其他情况下保持程序运行即可。

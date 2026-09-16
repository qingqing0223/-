# 微信公众号最终监测运行手册（冻结版）

## 目标

从 2026-09-16 00:00（北京时间）起，对“2026年民族团结进步宣传周”预热相关公开微信公众号文章进行持续监测，并自动完成：

1. 6个正式关键词搜索；
2. 搜索结果持续分页至自然终点（1000页/每词100000条为安全上限）；
3. 跨轮次去重与时间过滤；
4. 每5分钟增量轮询；
5. 文章标题、公开摘要/搜索页文本、公众号公开名称、发布时间、公开链接采集；
6. 志鹏 v2 态度分类及细分类；
7. 支持 / 中性 / 关注 / 非支持报告桶；
8. 来源类型分类、语言/少数民族语言识别；
9. 公开公众号账号聚合统计；
10. GitHub聚合结果自动同步；
11. 大屏 `/api/ingest` 自动推送，失败进入 outbox 后待恢复补发；
12. 官方验证码/安全验证出现时由人工完成，不绕过平台验证。

## 数据源限制（必须在报告中如实标注）

当前微信公众号链使用公开的搜狗微信文章搜索结果。该公开入口不稳定/不完整提供以下信息，因此系统不会把“未获取到”误写成“真实为0”：

- 文章精选留言/完整评论正文；
- 评论楼中楼/父子关系；
- 评论或文章作者公开IP属地；
- 完整、可靠、可比的阅读量/点赞量/在看量等全部互动指标。

这些字段如后续有授权的官方接口或合规数据源，可另行接入；当前冻结版不通过绕过验证或非公开接口获取。

## 正式关键词

- 2026年民族团结进步宣传周
- 首个民族团结进步宣传周
- 促进民族团结进步，奋进伟大复兴征程
- 民族团结进步倡议
- 民族团结进步宣传周主场活动
- 石榴花开——铸牢中华民族共同体意识

## 最终升级与启动

先关闭旧的公众号采集窗口和旧GitHub同步窗口。

进入项目目录：

```powershell
cd E:\realtime-opinion-monitor
```

确保当前 PowerShell 已设置 `DASHSCOPE_API_KEY`，不要把 Key 发群或截图。

运行最终冻结版升级并直接启动：

```powershell
.\scripts\final_wechat_mp_update_windows.ps1 `
  -NodeId wechatmp01 `
  -Config .\config\monitoring.wechat.local.json `
  -Start
```

脚本会自动：备份当前Git状态、对齐GitHub `main`、升级本地公众号配置、检查依赖、检查6个关键词、检查分类器，并启动公众号实时监测与GitHub同步。

## 正常运行状态

运行后保持：

- 主采集 PowerShell；
- GitHub同步 PowerShell；
- 自动打开的Chrome；
- 电脑不休眠。

出现搜狗/微信官方验证码时，在浏览器中人工完成。程序不会绕过验证码。

## 最终验收

至少完成一轮后，新开 PowerShell：

```powershell
cd E:\realtime-opinion-monitor
python .\scripts\verify_wechat_mp_final.py --config .\config\monitoring.wechat.local.json
```

重点查看：

- `schema_version: 6`
- `unique_records`
- `keywords`
- `attitude`
- `v2_status` / `v2_type`
- `source_types`
- `languages` / `minority_languages`
- `public_publisher_accounts`
- `public_account_stats`
- `runtime`

`comments_and_nested_replies`、`public_ip_region`、`complete_engagement_metrics` 显示 unavailable 是当前公开数据源能力边界，不属于运行失败。

## 后续原则

完成本次冻结版升级后，不再让采集端自行修改代码或参数。日常只处理：

- 官方登录/验证码；
- 网络异常；
- GitHub push失败；
- 大屏后端恢复；
- 数据结果核验与专报分析。

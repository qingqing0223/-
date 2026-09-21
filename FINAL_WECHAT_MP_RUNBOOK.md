# 微信公众号 TechDesign V3 运行手册

当前优先任务为2026-09-21 09:00—17:00、4关键词、wechatmp02独立批次。请使用 [今日运行与POMS上传说明](docs/WECHAT_MP_2026-09-21.md)。以下命令是旧通用配置，不用于今日批次。

当前业务仅负责采集和表1—表5。旧版态度分类、DashScope、大屏推送、自动 GitHub 同步流程不再适用于公众号。

完整运行、配置、数据口径、来源限制及验收步骤见 [公众号 V3 手册](docs/WECHAT_MP_V3.md)。

```powershell
.\.venv\Scripts\python.exe run_wechat_platform.py --platform wechat_mp --config config/monitoring.wechat.windows.json --once
.\.venv\Scripts\python.exe scripts/verify_wechat_mp_final.py --config config/monitoring.wechat.windows.json
```

移除 `--once` 后持续运行。搜索默认每300秒，表1/2默认900秒，表3/4/5默认3600秒，各自可配置。
输出位于 `data_submissions/wechat_mp/YYYY-MM-DD_wechatmp01`。
遇到官方验证码只能人工完成。不要提交凭据、Cookie、浏览器状态，不自动 commit 或 push。

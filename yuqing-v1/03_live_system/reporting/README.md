# 每日态势报告模块

该模块与大屏原有统计数据完全解耦，只读取仓库根目录下的：

```text
results/YYYY-MM-DD/nodes/<platform>/<node>.json
```

它不会启动爬虫，不会调用 v2 分类流程，也不会读取或修改大屏 SQLite 中的舆情数据。报告生成时才调用 Qwen3.8 Max，统计数字和图表均由本地代码计算。

生成文件默认保存到：

```text
03_live_system/data/generated_reports/YYYY-MM-DD/
```

缓存以源节点文件、Prompt、分类口径、模板和生成器代码的 SHA-256 指纹为准：指纹未变化时直接下载已有 DOCX/PDF；数据变化后旧缓存不会作为最新报告返回。

环境变量：

- `DASHSCOPE_API_KEY`：必填，调用 Qwen3.8 Max。
- `REPORT_MODEL`：默认 `qwen3.8-max`。
- `REPORT_RESULTS_ROOT`：可覆盖结果目录。
- `REPORT_OUTPUT_ROOT`：可覆盖报告存储目录。
- `REPORT_TIMEZONE`：默认 `Asia/Shanghai`。
- `REPORT_ALLOW_CURRENT_DAY=1`：允许当天数据仍在统计时生成快照；默认关闭。

接口：

- `GET /api/reports`：列出可选日期及缓存状态。
- `GET /api/reports/status?date=YYYY-MM-DD`：查询指定日期。
- `POST /api/reports/generate`：后台生成，JSON 为 `{"date":"YYYY-MM-DD"}`。
- `GET /api/reports/download?date=YYYY-MM-DD&format=docx|pdf`：下载缓存文件。

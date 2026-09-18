# 自动监测结果目录

本目录保存**脱敏聚合结果**，供团队协作、专报统计、GPT/GitHub 直接读取。

## 目录约定

### 1. 节点原始聚合快照

`results/YYYY-MM-DD/nodes/<platform>/<node-id>.json`

这是每台监测电脑自己的节点结果。一个平台可以同时存在多个节点，例如：

- `nodes/ks/ks01.json`
- `nodes/ks/ks-main.json`
- `nodes/dy/dy01.json`
- `nodes/dy/dy-coordinator.json`

**报表和“当前最新”统计不要再直接挑某一个 node 文件。**

### 2. 平台统一汇总（正式读取路径）

`results/YYYY-MM-DD/platforms/<platform>.json`

例如：

- `platforms/ks.json`
- `platforms/dy.json`
- `platforms/bili.json`
- `platforms/wb.json`
- `platforms/xhs.json`
- `platforms/tieba.json`
- `platforms/zhihu.json`

所有节点回传后，GitHub Actions 会自动重建这些平台统一汇总。

`results/YYYY-MM-DD/platforms/overview.json` 是当天所有平台的轻量总览，适合做“00:38 / 07:38 / 当前最新”比较。

### 3. 多节点去重规则

新版节点同步会额外发布**隐私安全的记录指纹**，不包含原始正文、原始用户 ID、URL、真实 IP 或精确位置。

当同一平台所有计数节点都具备记录指纹时，平台汇总按记录指纹做**跨节点精确去重**。

若仍有旧节点尚未升级，平台汇总不会把多个节点数字直接相加，而采用保守的完整节点快照，并在 `aggregation_mode` 中明确标记，避免重复统计。

## 隐私边界

公开仓库不会提交：

- 原始评论/帖子正文
- 账号 Cookie、登录态、browser_data
- API Key / `.env`
- 本地 SQLite 数据库
- 原始用户 ID
- 真实网络 IP 或精确定位

允许同步的是统计量、平台公开展示的粗粒度地区标签，以及不可逆的稳定记录指纹。

## 五分钟同步

各学生节点继续使用正式启动脚本。节点结果默认每 300 秒同步到 GitHub；节点文件更新后，平台统一汇总由 GitHub Actions 自动刷新。

正式统计程序、专报脚本和人工核对时，优先读取：

`results/YYYY-MM-DD/platforms/overview.json`

需要某个平台明细时读取：

`results/YYYY-MM-DD/platforms/<platform>.json`

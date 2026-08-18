# 日本进口月度自动化部署与运维

本文说明如何把当前代码作为每月自动运行的日本进口量价流程部署。2025 文件只用于回测；正式月度入口直接访问日本海关网页。

## 1. 部署前提

### Python

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Node.js 与 Excel 依赖

`src/excel_writer.mjs` 需要 Node.js 和 `@oai/artifact-tool`。

本交付包为了避免携带本机缓存，没有包含：

- `.venv`；
- `node_modules`；
- 原项目中指向 Codex 缓存的 `node_modules` junction。

因此，在另一台机器运行前，必须让 Node.js 能解析 `@oai/artifact-tool`。如果运行机器使用 Codex 提供的依赖环境，可在项目根目录建立指向该环境 `node_modules` 的 junction；如果使用独立 Node 环境，则应由部署人员按所在环境提供该包。

`scripts/run_monthly.ps1` 在 PATH 中找不到 `node` 时，会尝试当前开发机的固定路径：

```text
C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe
```

这是机器相关的备用路径。迁移部署时，建议显式传入 `-Node "<node.exe完整路径>"`，不要依赖该备用路径。

## 2. 上线前只读验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\tests\unit -v
.\.venv\Scripts\python.exe .\src\pipeline.py --help
```

当前版本应通过 8 个单元测试。

首次联网运行前，可先用一个 HS Code 测试网站连接：

```powershell
.\.venv\Scripts\python.exe .\src\fetcher.py `
  --direction import `
  --start-month 2026-06 `
  --hs-code 840140000 `
  --output .\data\raw\smoke_840140000.csv
```

该命令会生成 CSV 和同名 manifest；它不会更新正式历史表。

## 3. 手工运行一次正式流程

推荐先手工运行月度封装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_monthly.ps1 `
  -Python ".\.venv\Scripts\python.exe" `
  -Node "C:\path\to\node.exe" `
  -RefreshMonths 2
```

脚本会调用：

```powershell
.\src\pipeline.py --auto --refresh-months 2 --excel-scope all
```

自动模式的实际逻辑：

1. 从上一个日历月开始向前检查，默认最多 4 个月；
2. 找到第一个至少返回一个目标 HS Code 的月份，视为最新已发布月份；
3. 默认抓取该月及前一个月；
4. 保存 raw CSV 和 manifest；
5. 规范化并更新正式历史表；
6. 计算全部历史指标；
7. 生成汇总工作簿和 955 个逐 HS Code 工作簿；
8. 写入 run summary 和带时间戳的日志。

如果已知月份，也可以直接运行：

```powershell
.\.venv\Scripts\python.exe .\src\pipeline.py `
  --start-month 2026-07 `
  --end-month 2026-07 `
  --excel-scope all `
  --node "C:\path\to\node.exe"
```

若该月尚未发布，normalizer 会停止流程，正式历史表不会被写入整月零值。

## 4. 更新结果

运行时使用或创建：

```text
data/raw/import_<月份或月份范围>.csv
data/raw/import_<月份或月份范围>.manifest.json
data/raw/discovery/                    自动发现月份时的探测文件
data/history/import_monthly.csv        正式长期历史表
data/interim/import_metrics.json       Excel 输入及指标审计文件
outputs/logs/monthly_<时间戳>.log       月度运行日志
outputs/monthly/<最新历史月份>/
├── all_hs_import.xlsx
├── by_hs_code/
│   ├── <9位HS Code>.xlsx
│   └── ... 共955个
└── run_summary.json
```

输出目录名取历史表中的最新月份。每次 Excel 生成会用完整历史重新构建工作簿，因此新月份会成为每个 HS Code 工作簿中的新行，而不是在旧 Excel 文件末尾盲目追加。

## 5. 幂等和修订规则

历史唯一键为：

```text
direction + month + hs_code
```

- 新月份：新增记录；
- 已有月份且内容相同：保持一条记录；
- 已有月份但海关数据已修订：用新记录替换旧记录；
- 同一批输入中存在重复键：停止；
- 重新生成 Excel：按更新后的完整历史覆盖同名输出工作簿。

默认 `RefreshMonths = 2` 是为了同时刷新最新月和前一个月。若业务认为海关修订窗口更长，可运行时提高该值。

## 6. 安装 Windows 每月任务

安装脚本默认创建：

- 任务名：`conductordata-japan-import-monthly`；
- 频率：每月；
- 日期：每月 1 日；
- 时间：10:00；
- 时间基准：运行机器的本地时间。

安装命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1
```

自定义：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 `
  -TaskName "conductordata-japan-import-monthly" `
  -RunAt "10:00"
```

脚本使用 `schtasks.exe /Create /F`，因此会覆盖同名任务。需要使用有权创建计划任务的账户执行。安装脚本不会测试 Python、Node 或网站连通性，必须先完成第 2、3 节验证。

计划任务调用 `scripts/run_monthly.ps1`。该 runner 没有向计划任务安装器暴露 `-Python` 和 `-Node` 参数，因此正式部署前应确保项目 `.venv` 存在，并确保 PATH 或脚本备用路径能够找到 Node.js。

## 7. 每月检查清单

运行后检查：

1. 最新日志中没有 `Monthly pipeline failed`；
2. `run_summary.json` 的 `status` 为 `complete`；
3. `latest_month` 是预期月份；
4. `hs_count` 为 955；
5. `data/history/import_monthly.csv` 没有重复的 `direction + month + hs_code`；
6. `by_hs_code/` 中有 955 个 `.xlsx`；
7. 抽查一个工作簿的最后一行月份、Volume 和 Value；
8. 如果最新月尚未发布，确认历史表没有新增该月的 955 行零值。

当前 `pipeline.py` 新生成的 run summary 包含路径、HS 数量、历史行数、新增/替换行数、最新月份和 Excel scope。交付包内已有的 2026-06 summary 来自之前的成功运行，可能含有额外的输出计数字段。

## 8. 常见失败

| 现象 | 含义和处理 |
|---|---|
| 找不到 Python | 创建 `.venv`，或向 `run_monthly.ps1` 传入 `-Python` |
| 找不到 Node | 安装/提供 Node.js，并传入 `-Node` |
| 无法解析 `@oai/artifact-tool` | 建立正确的 `node_modules` 环境或 junction |
| 最近 4 个月都未发现发布数据 | 检查网站、请求参数及网络；必要时提高 `--max-lookback` |
| 某月返回 0 行 | 该月可能未发布；流程会停止，不应手工补 955 行零值 |
| manifest 与 CSV 数量不一致 | 抓取不完整或文件不配套；重新抓取，不要跳过校验 |
| 工作簿被 Excel 占用 | 关闭对应 Excel 文件后重新运行 |
| 计划任务成功启动但没有 Excel | 检查日志中的 Node 和 `@oai/artifact-tool` 错误 |

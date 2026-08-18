# 台湾第 84/85 章进出口月度量价自动化

本文件夹是一套可直接交付的台湾海关贸易数据 workflow。它每月从台湾官方数据源获取最新月份，覆盖现行第 84、85 章全部 CCC 11 位税号，分别维护进口与出口历史，并同时生成总表和每个 CCC 税号的小表。

## 为什么不拆成两个 parser

进口和出口使用相同的官方接口、CCC 参考表、批次拆分、异常处理、历史合并、指标计算与 Excel 模板，因此共用一套代码最稳妥。两种流向仍然在以下层面严格隔离：

- 请求参数：进口使用 `I`，出口使用 `E`；
- 原始数据：`data/raw/import` 与 `data/raw/export`；
- 历史数据：`data/history/import_monthly.csv` 与 `export_monthly.csv`；
- 输出目录：`outputs/monthly/YYYY-MM/import` 与 `export`；
- 价值定义：进口为 CIF，出口为 FOB，不能直接混算。

## 最终输出

每个流向都会生成：

- `all_ccc_import.xlsx` / `all_ccc_export.xlsx`：全部 CCC 的总表；
- `by_ccc_code/<CCC>.xlsx`：每个 CCC 一个小表；
- `run_summary.json`：本次运行月份、覆盖数量、原始文件和接口校验摘要。

小表包含 Monthly Data、Raw Data、CCC Mapping 三个工作表。量价指标包括申报数量、公斤重量、美元金额、每申报单位价值、美元/公斤、环比、同比及连续月份足够时的 3 月移动平均。

当官方发布新月份后，月度任务会重新抓取最近 3 个月以吸收初值修订，并把新月份按 `(flow, month, ccc_code)` 合并进历史。正常情况下，每个现行 CCC 对应的小表都会新增一行该月份数据；即使当月无贸易，也会记录为 0。若官方批次返回保密汇总行，无法安全归属的税号会保留为空并标记原因，不会伪造为 0。

## 一键运行

环境要求：Windows、Python 3.11+、Node.js 20+。Python 端只使用标准库；Excel 引擎已随交付文件夹放在 `node_modules` 中，无需在线安装 npm 包。

在 PowerShell 中执行：

```powershell
Set-Location "本文件夹路径"
powershell -ExecutionPolicy Bypass -File .\scripts\run_monthly.ps1
```

手动指定月份的示例：

```powershell
python .\src\pipeline.py --months 2026-07 --flow both --reuse-raw --concurrency 4 --excel-concurrency 6
```

首次回补连续历史月份：

```powershell
python .\src\pipeline.py --start-month 2025-01 --end-month 2026-07 --flow both --concurrency 4 --excel-concurrency 6
```

`--reuse-raw` 只适合已完成月份的断点续跑。正式月度任务不会使用它，因为最近月份可能被官方修订。

## 定时任务

以管理员身份运行以下脚本，可创建每月 15 日 14:00 的 Windows 计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1
```

安装脚本只负责创建任务，不会立即抓取数据。任务执行日志写入 `logs`。

## 数据口径与限制

- 范围：官方现行关税资料中第 84、85 章的全部 CCC 税号；当前参考表为 1,548 个。
- CCC：台湾 11 位货品分类号列；前 6 位为 HS6，前 8 位为台湾税则号列，末位包含校验位。
- 默认范围：官方 `All`，包含复进口/复出口。
- 金额：美元；进口 CIF、出口 FOB。
- Quantity：官方统计数量单位，部分税号没有申报数量单位。
- Weight：公斤。没有可比 Quantity 时，优先看 USD/kg。
- Unit Value 是平均报关单位价值，不是具体型号的市场报价。
- 最近月份可能是初步值，后续运行会覆盖同键旧值而不是重复追加。

更详细的架构、字段和验证证据见 [WORKFLOW_DESIGN.md](WORKFLOW_DESIGN.md)、[DATA_DICTIONARY.md](DATA_DICTIONARY.md) 与 [VALIDATION_REPORT.md](VALIDATION_REPORT.md)。


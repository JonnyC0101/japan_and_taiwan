# 脚本位置与运行说明

本文只描述当前交付目录中真实存在的脚本和参数。所有命令均应在项目根目录执行。

## 1. 环境准备

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Python 依赖见 `requirements.txt`。生成 Excel 还需要 Node.js 和 `@oai/artifact-tool`；部署说明见 `AUTOMATION.md`。

查看命令参数：

```powershell
.\.venv\Scripts\python.exe .\src\fetcher.py --help
.\.venv\Scripts\python.exe .\src\pipeline.py --help
.\.venv\Scripts\python.exe .\tests\validation\validate_2025.py --help
.\.venv\Scripts\python.exe .\tests\validation\aggregate_2025_import_by_hs_code.py --help
```

## 2. 当前脚本总览

| 文件 | 作用 | 正式月度流程 |
|---|---|---:|
| `src/data_model.py` | 规范记录的数据结构、CSV 读写和 HS Code 校验 | 是 |
| `src/fetcher.py` | 抓取日本海关月度 Values by Commodity 数据 | 是 |
| `src/normalizer.py` | 校验 raw/manifest、补全零值和统一字段 | 是 |
| `src/history_store.py` | 按唯一键幂等更新历史 | 是 |
| `src/metrics.py` | 计算 ASP、3MMA、MoM、YoY 和季度指标 | 是 |
| `src/excel_writer.mjs` | 生成汇总及逐 HS Code Excel | 是 |
| `src/pipeline.py` | 完整进口流程的统一 Python 入口 | 是 |
| `scripts/run_monthly.ps1` | 自动发现最新月份、运行全流程并保存日志 | 是 |
| `scripts/install_windows_task.ps1` | 安装 Windows 每月计划任务 | 部署一次 |
| `tests/validation/aggregate_2025_import_by_hs_code.py` | 将官方国家明细按 HS Code 汇总 | 否 |
| `tests/validation/validate_2025.py` | 对比抓取数据与 2025 官方参考 | 否 |
| `tests/unit/test_production_pipeline.py` | 生产流程边界条件测试 | 否 |
| `tests/unit/test_2025_production_regression.py` | 955 编码的 2025 回归测试 | 否 |

## 3. 推荐的月度入口

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_monthly.ps1
```

可选参数：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_monthly.ps1 `
  -Python "C:\path\to\python.exe" `
  -Node "C:\path\to\node.exe" `
  -RefreshMonths 2
```

脚本调用 `src/pipeline.py --auto --excel-scope all`，日志写入 `outputs/logs/monthly_<时间戳>.log`。如果项目根目录存在 `.venv\Scripts\python.exe`，脚本优先使用它，否则调用 PATH 中的 `python`。

## 4. pipeline.py

### 自动发现最新已发布月份

```powershell
.\.venv\Scripts\python.exe .\src\pipeline.py `
  --auto `
  --refresh-months 2 `
  --max-lookback 4 `
  --excel-scope all
```

`--auto`、`--start-month`、`--from-raw` 三者必须且只能选择一个。

### 指定月份抓取

```powershell
.\.venv\Scripts\python.exe .\src\pipeline.py `
  --start-month 2026-06 `
  --end-month 2026-07 `
  --excel-scope all
```

未提供 `--end-month` 时只抓取 `--start-month`。

### 使用已有 raw 文件离线运行

```powershell
.\.venv\Scripts\python.exe .\src\pipeline.py `
  --from-raw .\data\import_2025.csv `
  --manifest .\data\import_2025.manifest.json `
  --history .\data\interim\regression_history.csv `
  --metrics .\data\interim\regression_metrics.json `
  --output-root .\outputs\regression_2025 `
  --excel-scope all
```

不要在回归测试中省略独立的 `--history`，否则会改写正式历史表。

### 主要选项

| 选项 | 含义 | 默认值 |
|---|---|---|
| `--refresh-months` | 自动模式下重新抓取的连续月份数 | 2 |
| `--max-lookback` | 自动寻找已发布月份时最多向前检查的月数 | 4 |
| `--hs-file` | 目标 HS Code 清单 | `data/reference/2025/import_hs_codes_2025.csv` |
| `--reference` | 编码及 Unit1/Unit2 参考表 | `data/reference/2025/import_totals_by_hs_code.csv` |
| `--history` | 正式规范历史表 | `data/history/import_monthly.csv` |
| `--metrics` | Excel 生成前的指标 JSON | `data/interim/import_metrics.json` |
| `--output-root` | 月度结果根目录 | `outputs/monthly` |
| `--delay` | 相邻网站请求之间的最短秒数 | 1.0 |
| `--skip-excel` | 只更新历史和指标，不生成 Excel | 关闭 |
| `--excel-scope` | `all`、`consolidated` 或 `per-hs` | `all` |
| `--limit-hs` | 仅用于开发测试的逐 HS 输出数量限制 | 不限制 |
| `--node` | Node.js 命令或完整路径 | `node` |

## 5. fetcher.py

`fetcher.py` 只负责原始抓取，不计算指标、不更新历史、不生成 Excel。它将 CSV 与同名 `.manifest.json` 原子写入磁盘。

### 单个 HS Code

```powershell
.\.venv\Scripts\python.exe .\src\fetcher.py `
  --direction import `
  --start-month 2026-06 `
  --hs-code 840140000 `
  --output .\data\raw\test_840140000.csv
```

### 全部 955 个编码

```powershell
.\.venv\Scripts\python.exe .\src\fetcher.py `
  --direction import `
  --start-month 2026-01 `
  --end-month 2026-06 `
  --hs-file .\data\reference\2025\import_hs_codes_2025.csv `
  --output .\data\raw\import_2026-01_to_2026-06.csv
```

默认 manifest 与输出 CSV 同目录、同文件名主体，例如 `test_840140000.manifest.json`。

底层抓取器接受 `--direction export`，但当前 `normalizer.py` 和生产 `pipeline.py` 只接受进口。出口 raw 文件不能送入现有生产流程。

## 6. 2025 回测与验证

本交付包中的回测输入位于项目根目录下的 `data/`，不是 `data/raw/`：

- `data/import_2025.csv`；
- `data/import_2025.manifest.json`；
- `data/import_2025_01.csv`；
- `data/import_2025_01.manifest.json`。

### 重新生成官方聚合参考表

```powershell
.\.venv\Scripts\python.exe .\tests\validation\aggregate_2025_import_by_hs_code.py `
  --input .\data\reference\2025\official_import_2025.csv `
  --output .\data\reference\2025\import_totals_by_hs_code.csv
```

此脚本的当前默认路径会解析到 `tests\data\...`，与本交付目录不一致，因此必须像上面一样显式传入 `--input` 和 `--output`。

### 全年对比

```powershell
.\.venv\Scripts\python.exe .\tests\validation\validate_2025.py `
  --fetched .\data\import_2025.csv `
  --manifest .\data\import_2025.manifest.json `
  --reference .\data\reference\2025\import_totals_by_hs_code.csv `
  --output .\tests\validation_2025.csv `
  --summary .\tests\validation_2025.summary.json
```

### 2025 年 1 月对比

```powershell
.\.venv\Scripts\python.exe .\tests\validation\validate_2025.py `
  --fetched .\data\import_2025_01.csv `
  --manifest .\data\import_2025_01.manifest.json `
  --reference .\data\reference\2025\import_totals_by_hs_code.csv `
  --output .\tests\validation_2025_01.csv `
  --summary .\tests\validation_2025_01.summary.json
```

明细行的 `status = PASS` 或 `PASS_ZERO_NOT_RETURNED` 表示方向、月份、单位、Quantity1、Quantity2 和金额均与官方参考相符；summary 顶层的成功状态为 `PASS`。

## 7. 单元测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\tests\unit -v
```

当前应发现 8 个测试。测试覆盖：

- 未发布月份不会被误写成零值；
- 已发布月份中网页省略的零值编码会被补全；
- 历史合并幂等且修订会覆盖；
- ASP、变化率和季度指标；
- 955 编码 × 12 个月的 2025 完整网格；
- HS 840140000 与参考附件的数量、金额及 ASP。

## 8. excel_writer.mjs

通常由 `pipeline.py` 调用，不建议手工运行。其必要输入是 `metrics.py` 生成的 JSON：

```powershell
node .\src\excel_writer.mjs `
  --metrics .\data\interim\import_metrics.json `
  --output-dir .\outputs\monthly\2026-06 `
  --scope all
```

支持的 scope：

- `all`：汇总工作簿和逐 HS Code 工作簿；
- `consolidated`：仅 `all_hs_import.xlsx`；
- `per-hs`：仅 `by_hs_code/*.xlsx`。

生成器会检查汇总工作簿和首个逐 HS Code 工作簿的公式错误。只有显式提供 `--preview-dir` 时才生成 PNG 预览；生产 pipeline 不传该参数。

## 9. Windows 计划任务

默认在每月 1 日 10:00（运行机器本地时间）执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1
```

自定义任务名和时间：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 `
  -TaskName "conductordata-japan-import-monthly" `
  -RunAt "10:00"
```

安装脚本会创建或覆盖同名 Windows 计划任务，但项目测试本身不会安装任务。

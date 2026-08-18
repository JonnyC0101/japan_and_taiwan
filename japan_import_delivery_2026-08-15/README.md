# conductordata：日本进口月度量价自动化项目

本项目从日本财务省海关的 `Values by Commodity` 网页取得月度贸易数据，以 9 位 HS Code 为主键维护历史记录，计算数量、金额、ASP 及变化指标，并生成汇总 Excel 和逐 HS Code Excel。

当前正式生产流程只处理日本进口。`src/fetcher.py` 的底层命令虽然保留 `--direction export`，但 `src/normalizer.py` 和 `src/pipeline.py` 明确只接受进口数据，因此出口不能直接接入本流程，也不能与进口共用历史表。

## 1. 当前交付状态

本交付包中的最新已完成结果截至 `2026-06`：

- HS Code 数量：955；
- 历史月份：2025-01 至 2026-06，共 18 个月；
- 规范历史记录：17,190 行；
- 逐 HS Code 工作簿：955 个；
- 汇总工作簿：`outputs/monthly/2026-06/all_hs_import.xlsx`；
- 逐编码工作簿目录：`outputs/monthly/2026-06/by_hs_code/`；
- 2025 全年回测：11,460 个 `HS Code × Month` 组合全部通过对比。

`outputs/monthly/2026-06/run_summary.json` 是已有运行的历史记录，其中的绝对路径指向生成该结果时的原项目目录。它不是配置文件；以后从本目录运行时会在新输出目录中生成新的摘要。

`tests/validation_2025*.summary.json` 同样保留了回测生成时的原始绝对路径。这些路径用于说明历史来源，不是本交付目录的运行参数；实际回测命令应使用 `SCRIPTS.md` 中列出的当前相对路径。

## 2. 数据源和数据边界

正式数据源：

`https://www.customs.go.jp/JCWSV04/servlet/JCWSV04`

抓取器通过日本海关查询表单取得按月、按商品编码汇总的全球进口数据。原始字段包括：

- `direction`：进口或出口；生产流程要求为 `import`；
- `month`：`YYYY-MM`；
- `hs_code`：9 位日本统计品目编号；
- `unit1`、`quantity1`：第一数量单位及数量；
- `unit2`、`quantity2`：第二数量单位及数量；
- `value_thousand_yen`：金额，单位为千日元；
- 年初至今数量和金额；
- UTC 抓取时间。

本项目使用 `data/reference/2025/import_hs_codes_2025.csv` 中的 955 个编码作为抓取范围，使用 `data/reference/2025/import_totals_by_hs_code.csv` 提供各编码的参考单位。项目不会从文件名推断商品，也不会把不同 Unit2 的数量直接相加。

## 3. 正式工作流

```text
日本海关网页
  → fetcher.py：抓取 CSV 和 manifest
  → normalizer.py：校验月份、方向、单位、记录数并补全显式零值
  → history_store.py：按 direction + month + HS Code 幂等更新历史
  → metrics.py：计算 ASP、3MMA、MoM、YoY 和季度指标
  → excel_writer.mjs：生成汇总和逐 HS Code 工作簿
  → pipeline.py：写入 run_summary.json
```

关键安全规则：

- 整个月没有返回任何 HS Code 时，视为未发布或请求异常，停止更新，不能将该月写成 955 行零值；
- 某月已经返回大量编码、但个别目标编码没有返回时，按海关零值不显示的规则补成零值，状态记为 `zero_not_returned`；
- 同一月份重新运行时覆盖对应旧记录，不产生重复行；
- 原始 CSV 与 manifest 必须配套，manifest 用来证明抓取范围和完整性；
- 重复编码、错误月份、错误方向、缺失 Unit2 或记录数不一致都会中止流程。

## 4. 每月自动更新会发生什么

推荐入口是：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_monthly.ps1
```

默认行为：

1. 从上一个日历月开始，最多向前检查 4 个月，找到最新已发布月份；
2. 抓取最新月份和它前一个月份，即 `RefreshMonths = 2`，以覆盖海关后续修订；
3. 更新 `data/history/import_monthly.csv`；
4. 重新计算全部历史指标；
5. 在 `outputs/monthly/<最新历史月份>/` 重新生成汇总工作簿和每个 HS Code 的工作簿；
6. 将运行日志写入 `outputs/logs/`。

例如 2026-07 数据发布后，流程成功抓取并确认该月已发布，则历史表会为每个目标 HS Code 新增或替换一条 `2026-07` 记录，并重新生成 955 个工作簿。每个工作簿会包含新的 `2026-07` 行；旧月份不会重复追加。

## 5. 指标定义

主分析口径使用 Unit2：

- `Volume = Quantity2`；
- `Value (thsd) = value_thousand_yen`；
- `Value (mn) = Value (thsd) / 1000`；
- `ASP = Value (thsd) / Quantity2`，单位为千日元/Unit2；
- `ASP (3MMA)`：当前月及前两个月 ASP 的简单平均，三个月都可计算时才显示；
- `MoM = 当前月 / 上月 - 1`；
- `YoY = 当前月 / 去年同月 - 1`；
- `Value (Q)`：仅在 3、6、9、12 月显示当季三个月金额合计；
- `Q Value (QoQ)` 和 `Q Value (YoY)`：季度金额的环比和同比。

当数量为空或为零、比较基期为空或为零、历史月份不足时，相应比率留空。Unit1/Quantity1 仍保留在历史表和 Raw Data 工作表中，便于审计。

## 6. Excel 输出结构

`all_hs_import.xlsx` 包含：

- `Index`：955 个 HS Code 的月份数、最新月份、单位、最新数量、最新金额、最新 ASP 和对应文件名；
- `All HS Monthly`：所有编码、所有月份的长表及公式指标。

每个 `by_hs_code/<HS Code>.xlsx` 包含：

- `Monthly Data`：该编码的月度量价、ASP、环比、同比和季度指标；
- `Raw Data`：Unit1/Quantity1、Unit2/Quantity2、金额、记录状态、抓取时间和来源网址。

文件名必须与工作簿标题中的 9 位 HS Code 相同。

## 7. 目录说明

```text
project 4_delivery_2026-08-15/
├── src/                       正式 Python 和 Node.js 代码
├── scripts/                   月度运行和计划任务脚本
├── data/
│   ├── history/               正式规范历史表
│   ├── raw/                   2026-01 至 2026-06 原始抓取及 manifest
│   ├── reference/2025/        HS 清单、官方参考数据和聚合参考表
│   └── import_2025*.csv/json  2025 回测输入
├── templates/                 用户提供的格式参考工作簿
├── tests/                     单元测试、验证程序和既有验证结果
├── outputs/monthly/2026-06/   当前最终 Excel 与运行摘要
├── README.md                  项目说明
├── SCRIPTS.md                 各脚本参数和命令
├── AUTOMATION.md              部署及每月运维说明
├── requirements.txt           Python 依赖
└── DELIVERY_MANIFEST.csv      交付文件清单和 SHA-256
```

运行时会创建 `data/interim/`、`outputs/logs/` 和新的 `outputs/monthly/YYYY-MM/`；它们不是本次交付缺失文件。

## 8. 环境和快速验证

Python 环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Excel 生成器需要 Node.js 和 `@oai/artifact-tool`。本交付包没有包含原机器的 `.venv`、`node_modules` junction 或 Codex 缓存；迁移到另一台机器时，必须先让 Node.js 能解析 `@oai/artifact-tool`。详细要求见 `AUTOMATION.md`。

只运行不访问网站的单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\tests\unit -v
```

2025 离线回归和验证命令见 `SCRIPTS.md`。

## 9. 文件职责

| 文件 | 职责 | 正式月度流程使用 |
|---|---|---:|
| `src/fetcher.py` | 从日本海关抓取原始数据并写 CSV/manifest | 是 |
| `src/normalizer.py` | 校验和补全月度数据 | 是 |
| `src/history_store.py` | 幂等更新历史记录 | 是 |
| `src/metrics.py` | 计算量价和变化指标 | 是 |
| `src/excel_writer.mjs` | 生成汇总及逐 HS 工作簿 | 是 |
| `src/pipeline.py` | 串联完整进口流程 | 是 |
| `scripts/run_monthly.ps1` | 无人值守月度入口和日志 | 是 |
| `scripts/install_windows_task.ps1` | 创建 Windows 每月计划任务 | 部署时使用一次 |
| `tests/validation/aggregate_2025_import_by_hs_code.py` | 汇总官方 2025 国家明细 | 仅验证 |
| `tests/validation/validate_2025.py` | 对比网页抓取和官方参考 | 仅验证 |
| `tests/unit/test_production_pipeline.py` | 生产逻辑单元测试 | 仅验证 |
| `tests/unit/test_2025_production_regression.py` | 955 编码 2025 回归测试 | 仅验证 |

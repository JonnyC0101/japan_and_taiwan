# 日本出口量价自动化流程

本项目按日本财务省/海关的 **Values by Commodity** 口径，每月抓取指定日本出口 9 位 HS Code 的数量与金额，维护历史序列，并生成一份总表和每个 HS Code 一份明细 Excel。

## 当前交付结果

- 原始重点业务映射：76 条（`data/reference/export_hs_product_mapping.csv`，原文件保留不改）
- 可查询的日本官方出口末级码：1,029 个（`data/reference/export_hs_reference.csv`）
- 范围构成：第84章648个、第85章353个、其他章节重点码28个
- 回测区间：2025-01 至 2025-12
- 当前历史区间：2025-01 至 2026-06
- 历史数据行数：1,029 × 18 = 18,522
- Excel：`outputs/monthly/2026-06/all_hs_export.xlsx`，以及 `by_hs_code/` 下 1,029 个小表
- 2025 的11,965条网页记录和2026-01至2026-06的5,809条网页记录均逐行与 e-Stat 官方 CSV 对账，数量、金额和单位错误数为0

截至 2026-08-16，日本官方详细出口数据的最新月份为 2026-06。程序的 `--auto` 模式会自动回看尚未发布的月份，所以未来 2026-07 发布后，无需改代码；下一次运行会把它合并到历史，并在总表和全部 1,029 个 HS 工作簿中新增 2026-07 行。

## 一键执行

环境要求：Windows、Python 3.11+、Node.js 20+。Excel 引擎已随交付文件夹放在 `node_modules` 中，不依赖本机 Codex 缓存路径。

首次运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

配置完成后直接执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_monthly.ps1
```

也可指定月份运行：

```powershell
.\.venv\Scripts\python.exe .\src\pipeline.py `
  --start-month 2026-07 `
  --excel-scope all `
  --node node
```

程序仅在该月份已发布并返回可信结果时更新历史。未发布页、空页、方向不符、月份不符、结果数不完整、重复 HS 或缺少 Unit2 都会导致失败，不会把错误数据写进历史。

## 输出说明

总表 `all_hs_export.xlsx` 包含：

- `Index`：1,029 个官方出口 HS Code、产品关系、源编码、最新数量、最新金额、最新 ASP 和对应小表路径。
- `All HS Monthly`：全部 HS 的月度 Volume、FOB Value、ASP、3MMA、MoM、YoY、季度值及环比/同比。

每个 `by_hs_code/<HS>.xlsx` 包含：

- `Monthly Data`：与参考交付一致的量价变化指标。
- `Raw Data`：该 HS 的官方原始数量、金额、抓取时间和来源 URL。
- `HS Mapping`：原始业务编码到日本官方出口码的映射审计信息。

ASP 的定义为：`Value (thousand JPY) ÷ Quantity2`。它是海关平均出口单位价值，不等同于具体型号的市场成交价；出口金额口径为 FOB。

## 官方数据源

- 日本海关在线 Values by Commodity：https://www.customs.go.jp/JCWSV04/servlet/JCWSV04
- 日本 9 位统计品目编号说明：https://www.customs.go.jp/toukei/sankou/code/code_e.htm
- 日本出口统计品目表：https://www.customs.go.jp/yusyutu/2025_01_01/index.htm
- e-Stat 贸易统计 Values by Commodity：https://www.e-stat.go.jp/en/stat-search/files?cycle=1&data=1&layout=datalist&metadata=1&page=1&tclass1=000001013183&tclass2=000001013184&tclass3val=0&toukei=00350300&tstat=000001013141

更详细的设计、定时任务、数据字典和验证记录分别见 `WORKFLOW_DESIGN.md`、`AUTOMATION.md`、`DATA_DICTIONARY.md` 和 `VALIDATION_REPORT.md`。

## 年度税则维护

月度抓取会自动发现新月份，但日本 9 位统计品目表可能在年度切换时增删或换码。当前参考清单由随附的 2025 和 2026 官方表构建；进入新的税则年度前，应下载该年度官方 Values by Commodity CSV，重新运行 `build_export_reference.py` 并完成一次回归验证。程序不会把旧年度代码擅自映射成新代码。

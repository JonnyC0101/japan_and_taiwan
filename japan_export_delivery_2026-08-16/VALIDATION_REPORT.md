# 验证报告

验证日期：2026-08-16。

## 官方对账

- 2025-01 至 2025-12：11,965个网页返回行与 e-Stat 2025 revised Values by Commodity CSV 对账；检查11,965行，缺失0，数量/金额/单位不一致0。补齐官方未返回的零贸易月份后为12,348行。
- 2026-01 至 2026-06：5,809个网页返回行与 e-Stat 2026-06 detailed CSV 对账；检查5,809行，缺失0，数量/金额/单位不一致0。补齐零贸易月份后为6,174行。
- 当前历史总计：18,522行，1,029个HS Code，每个18个月。

机器可读结果：`tests/validation/export_2025_reconciliation.json` 和 `tests/validation/export_2026_reconciliation.json`。

## 自动化与代码测试

`python -m unittest discover -s tests/unit -v` 共 9 项通过，包括：网页未发布页处理、方向校验、零贸易补齐、历史幂等合并、修订覆盖、指标公式，以及 2025 全量官方回归。

## Excel 验证

- 已生成1个总表和1,029个逐HS工作簿。
- 总表含 `Index` 和 `All HS Monthly`；逐 HS 表含 `Monthly Data`、`Raw Data`、`HS Mapping`。
- 已检查关键数值和公式，无 `#REF!`、`#DIV/0!`、`#VALUE!`、`#NAME?` 或 `#N/A`。
- 已分别渲染检查总表两张工作表和代表性逐 HS 工作簿的三张工作表；标题、列宽、日期、数字、百分比和中文映射可读。

## 已知口径限制

海关 ASP 是某 HS 分类下的平均出口单位价值，出口金额为 FOB。产品组合、规格、封装和单位变化都会影响它，因此适合作为趋势指标，不应直接解释为单一型号市场价格。

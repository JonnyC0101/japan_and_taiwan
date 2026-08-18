# 数据字典

## 历史表 `data/history/export_monthly.csv`

| 字段 | 含义 |
|---|---|
| direction | 固定为 `export` |
| month | 月份，`YYYY-MM` |
| hs_code | 日本出口 9 位统计品目编号 |
| unit1 / quantity1 | 官方第一数量单位及数量；部分品目为空 |
| unit2 / quantity2 | 官方第二数量单位及主要数量 |
| value_thousand_yen | 出口 FOB 金额，单位千日元 |
| ytd_* | 网页返回的年初至今数量/金额 |
| fetched_at_utc | 抓取时间 |
| record_status | `reported` 或经完整 manifest 证明的 `zero_not_returned` |

## Excel 指标

| 指标 | 公式/说明 |
|---|---|
| Volume | Quantity2 |
| Value (thsd) | value_thousand_yen |
| Value (mn) | Value (thsd) ÷ 1,000 |
| ASP | Value (thsd) ÷ Volume |
| ASP (3MMA) | 最近连续三个月 ASP 的简单平均 |
| MoM | 本月 ÷ 上月 - 1 |
| YoY | 本月 ÷ 去年同月 - 1 |
| Value (Q) | 仅在 3/6/9/12 月显示该季度三个月金额合计 |
| Q Value (QoQ) | 本季度金额 ÷ 上季度金额 - 1 |
| Q Value (YoY) | 本季度金额 ÷ 去年同期季度金额 - 1 |

ASP 使用 Unit2。若 Quantity2 为 0 或缺失，ASP 留空，不做除零。不同 HS 的 Unit2 可能是 KG、NO、TH、SM 等，不能跨单位直接比较 ASP 绝对水平。

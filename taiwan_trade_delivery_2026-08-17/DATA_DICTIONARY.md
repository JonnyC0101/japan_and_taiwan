# 数据字典

## 历史与原始 CSV 核心字段

| 字段 | 含义 |
|---|---|
| `reporter` | 报告方，固定为 Taiwan |
| `flow` | `import` 或 `export` |
| `month` | 统计月份，`YYYY-MM` |
| `ccc_code` | 台湾 11 位 CCC 货品分类号列，按文本保存 |
| `hs6` | CCC 前 6 位，国际 HS 层级 |
| `hs8` | CCC 前 8 位，台湾税则细分 |
| `commodity_name_zh/en` | 官方中英文货名 |
| `quantity_unit` | 官方统计数量单位；可能为空 |
| `quantity` | 该单位下的申报数量；不可归属时为空 |
| `weight_kg` | 官方重量，公斤；不可归属时为空 |
| `value_usd` | 美元金额；进口 CIF、出口 FOB |
| `record_status` | `reported`（官方返回明细）、`zero_no_return`（该税号无返回且批次无保密汇总，可安全记 0）或 `not_returned_batch_has_protected_row`（批次含保密汇总，无法安全归属，数值留空） |
| `fetched_at_utc` | 抓取时间 |
| `source_url` | 官方来源 |

## 派生指标

| 指标 | 公式 / 说明 |
|---|---|
| Value (mn USD) | `value_usd / 1,000,000` |
| Unit Value | `value_usd / quantity`，数量为空或 0 时为空 |
| USD/kg | `value_usd / weight_kg`，重量为空或 0 时为空 |
| MoM | `本月 / 上月 - 1`；必须存在同税号连续上月 |
| YoY | `本月 / 去年同月 - 1` |
| Unit Value (3MMA) | 连续 3 个月 Unit Value 的简单平均 |

单位价值只描述某一 CCC 分类内全部申报货品的平均值。产品组合、规格、原产地、运费和保险变化都会影响该指标。

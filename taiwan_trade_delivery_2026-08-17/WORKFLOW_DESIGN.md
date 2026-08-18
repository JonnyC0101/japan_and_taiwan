# Workflow 设计说明

## 数据源

1. 官方 CCC 参考资料：台湾海关开放资料 `https://opendata.customs.gov.tw/data/80871/csv.csv`。
2. 官方月度量价：经贸统计查询页 `https://publicinfo.trade.gov.tw/cuswebo/FSCE3000C?table=FSCE3020F` 的结构化查询接口。
3. 独立对账：单一 CCC 表格查询 `https://publicinfo.trade.gov.tw/cuswebo/FSCE3010F/FSC3010P`。

## 处理链

```text
官方 CCC CSV
  -> 过滤现行第 84/85 章
  -> 11 位 CCC 参考表
  -> 每 20 个连续税号组成一个批次

每个 flow + month + 批次
  -> Quantity 请求（金额 + 统计数量）
  -> Weight 请求（金额 + kg）
  -> 两次金额交叉校验
  -> 区分正常、零贸易、保密/无法归属
  -> 原始 CSV + manifest
  -> 按 flow/month/CCC 幂等合并历史
  -> 计算单位价值、环比、同比、3MMA
  -> 总表 + 逐 CCC Excel
```

## 关键设计决定

- 一个 parser、两个 flow：共享规则但隔离存储和输出，避免复制代码与口径串线。
- 批次上限 20：与官方页面查询能力一致；连续排序使省略项的判断可复现。
- 两次请求：官方数量和重量位于不同展示模式，金额是两者的共同校验键。
- 幂等更新：历史主键为 `(flow, month, ccc_code)`；重跑会替换，不会产生重复行。
- 修订吸收：自动模式默认刷新最近 3 个月。
- 保密优先：批次存在受保护汇总时，缺失项不强行填 0。
- 公式输出：Excel 中单位价值、环比、同比保持公式，便于审阅者追溯。
- 可恢复：历史回补可使用 `--reuse-raw` 跳过完整原始月份。

## 自动模式

`pipeline.py --auto` 先读取官方页面当前可选的最新年月，再生成最近 N 个月列表。每月任务使用 N=3，重新获取数据、合并历史并重建最新输出。CCC 参考表也会在月度脚本中刷新，以处理税则新增或失效。

如果官方新增/删除 CCC，历史 CSV 不会被删除；它继续保留退役代码作为审计记录，但最新 Excel 只发布当前官方参考表中的代码，避免“现行 CCC”标题和内容不一致。对长期研究，建议按年份归档 reference manifest，以便解释分类变更。

## 失败与恢复

- HTTP 连接、SSL 断开或临时限流：指数退避并重试；并发失败项随后串行重试。
- 不完整原始文件：manifest 的 CCC 数量不匹配时不会被 `--reuse-raw` 接受。
- 数量/重量金额不一致：记录在 manifest 的 `amount_mismatch_count`，不得静默忽略。
- Excel 生成失败：原始 CSV 与历史数据已经落盘，可只重跑 Excel 阶段。

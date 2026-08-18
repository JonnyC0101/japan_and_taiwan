# 每月自动运行

## 手动运行最新版

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_monthly.ps1
```

脚本会：自动识别最新已公布月份、重新抓取最近两个月、更新历史、重算全部指标、生成一个总表和1,029个逐HS小表，并将控制台日志写入 `outputs/logs/`。

## 安装 Windows 定时任务

请在项目根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1
```

默认创建 `conductordata-japan-export-monthly`，每月 1 日 10:00 执行。要改时间：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -RunAt "14:00"
```

日本详细月度数据通常不是月初立即发布，因此程序允许回看 4 个月；如果 1 日尚未发布新月份，这次运行只会刷新最近已发布月份，下一月会自动补入。若需要更及时，可在 Windows 任务计划程序中把频率改为每周，工作流本身保持幂等。

## 运行环境

- Python 3.11 或更高；Python 依赖见 `requirements.txt`，可运行 `scripts/setup.ps1` 自动创建本地虚拟环境。
- Node.js 20 或更高；`@oai/artifact-tool` 已作为交付依赖放在项目的 `node_modules` 中。
- `run_monthly.ps1` 只使用系统可发现的 Node，不再依赖任何用户专属或 Codex 缓存路径。
- 年度税则变更不属于月度抓取：进入新税则年度前需要更新官方参考 CSV 并重建 `export_hs_reference.csv`。

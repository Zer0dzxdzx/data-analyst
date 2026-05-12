# AI 数据分析助手

基于 Python、Pandas 与 OpenAI-compatible LLM API 的自动化 CSV 数据分析原型。它可以自动读取 CSV、识别字段类型、生成 EDA 摘要和图表，并输出 Markdown/HTML 报告。

## 功能

- CSV 自动加载：支持 `utf-8-sig`、`utf-8`、`gb18030`、`latin1` 编码回退。
- 字段识别：数值、类别、日期、布尔、文本、ID-like 字段。
- EDA：数据规模、缺失率、描述统计、类别 Top N、日期范围、相关性。
- 可视化：缺失值、数值分布、类别 Top N、相关性热力图、时间趋势。
- LLM 洞察：通过 OpenAI-compatible Chat Completions 输出中文分析结论。
- 隐私保护：启用 LLM 时只发送 schema 与脱敏聚合统计，不发送原始数据行。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 快速开始

默认离线运行，系统会使用本地模板生成结论，不会发起网络请求：

```bash
ai-data-analyst analyze examples/sales_sample.csv --out reports/sales_demo --target revenue
```

或直接用模块方式运行：

```bash
PYTHONPATH=src python3 -m ai_data_analyst analyze examples/sales_sample.csv --out reports/sales_demo --target revenue
```

输出文件：

- `reports/sales_demo/report.md`
- `reports/sales_demo/report.html`
- `reports/sales_demo/summary.json`
- `reports/sales_demo/figures/*.png`

## LLM 配置

支持 OpenAI-compatible API：

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o-mini"
ai-data-analyst analyze examples/sales_sample.csv --out reports/sales_demo --target revenue --llm
```

`LLM_BASE_URL` 可以是 API 根路径，也可以直接是 `/chat/completions` 端点。
CLI 只有显式传入 `--llm` 时才会调用外部 API。

## Python API

```python
from pathlib import Path

from ai_data_analyst import AnalysisConfig, analyze_csv

result = analyze_csv(
    "examples/sales_sample.csv",
    AnalysisConfig(output_dir=Path("reports/sales_demo"), target_column="revenue"),
)

print(result.summary_path)
print(result.report_paths)
```

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

如果安装了开发依赖，也可以使用：

```bash
pytest
```

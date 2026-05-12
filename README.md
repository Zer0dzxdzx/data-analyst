# AI 数据分析助手

基于 Python、Pandas 与 OpenAI-compatible LLM API 的自动化 CSV 数据分析原型。它可以自动读取 CSV、识别字段类型、生成 EDA 摘要和图表，并输出 Markdown/HTML 报告。

## 功能

- CSV 自动加载：支持 `utf-8-sig`、`utf-8`、`gb18030`、`latin1` 编码回退。
- 字段识别：数值、类别、日期、布尔、文本、ID-like 字段。
- EDA：数据规模、缺失率、描述统计、类别 Top N、日期范围、相关性。
- 可视化：缺失值、数值分布、类别 Top N、相关性热力图、时间趋势。
- LLM 洞察：通过 OpenAI-compatible Chat Completions 输出中文分析结论。
- 隐私保护：启用 LLM 时只发送 schema 与脱敏聚合统计，不发送原始数据行。

## 首次使用

先安装一次依赖：

```bash
python3 -m pip install -e .
```

## 最简单用法

默认离线运行，系统会使用本地模板生成结论，不会发起网络请求：

```bash
python3 analyze.py
```

分析自己的 CSV：

```bash
python3 analyze.py /path/to/your.csv
```

如果有目标列，例如 `revenue`：

```bash
python3 analyze.py /path/to/your.csv --target revenue
```

## 网页版

网页入口需要先安装依赖：

```bash
python3 -m pip install -e .
ai-data-analyst-web
```

打开浏览器访问 `http://127.0.0.1:8000`，上传 CSV 就能分析。
网页会在本地会话里保存一个简单的 CSRF token，并默认只接受本机来源请求。

输出文件：

- `reports/sales_sample-<hash>/report.md`
- `reports/sales_sample-<hash>/report.html`
- `reports/sales_sample-<hash>/summary.json`
- `reports/sales_sample-<hash>/figures/*.png`

## 可选：使用虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

安装后也可以使用完整 CLI：

```bash
ai-data-analyst analyze examples/sales_sample.csv --out reports/sales_demo --target revenue
```

## LLM 配置

支持 OpenAI-compatible API：

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o-mini"
python3 analyze.py /path/to/your.csv --target revenue --llm
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
python3 -m pip install -e ".[dev]"
pytest
python3 -m ruff check .
```

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
python3 -m pip install -r requirements.txt
python3 -m pip install -e . --no-deps
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

## 部署到 Render

仓库内已包含 `render.yaml`，可以在 Render 创建 Web Service 并连接 GitHub 仓库后自动部署。公网版本默认使用离线分析：

- 上传上限：10MB
- 行数上限：100000 行
- 列数上限：100 列
- 相关性矩阵：最多 30 个数值列
- 限流：每 IP 每小时 20 次分析请求
- 报告目录：`/tmp/ai-data-analyst-reports`
- 临时保留：24 小时
- LLM：默认关闭，不配置 `LLM_API_KEY`
- 访问码：公网必须设置 `AI_ANALYST_ACCESS_CODE`；缺失时服务会 fail closed

Render 启动命令：

```bash
gunicorn 'ai_data_analyst.web:create_app()' --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120
```

如果不使用 `render.yaml` 自动创建服务，请手动配置这些环境变量，保证公网行为一致：

```bash
AI_ANALYST_SECRET_KEY=<生成一个长随机字符串>
AI_ANALYST_REQUIRE_ACCESS_CODE=1
AI_ANALYST_ACCESS_CODE=<发给试用者的共享访问码>
AI_ANALYST_WEB_REPORTS_DIR=/tmp/ai-data-analyst-reports
AI_ANALYST_MAX_UPLOAD_MB=10
AI_ANALYST_RATE_LIMIT_PER_HOUR=20
AI_ANALYST_ACCESS_ATTEMPT_LIMIT_PER_HOUR=10
AI_ANALYST_MAX_ROWS=100000
AI_ANALYST_MAX_COLUMNS=100
AI_ANALYST_MAX_CORRELATION_COLUMNS=30
AI_ANALYST_RETENTION_HOURS=24
AI_ANALYST_WEB_ALLOW_LLM=0
AI_ANALYST_TRUST_PROXY=1
AI_ANALYST_SESSION_COOKIE_SECURE=1
MPLBACKEND=Agg
```

`AI_ANALYST_TRUST_PROXY=1` 只应在 Render 这类可信反向代理后开启，用于正确识别公网 HTTPS Origin。
启用 `AI_ANALYST_TRUST_PROXY=1` 时，如果没有配置 `AI_ANALYST_ACCESS_CODE`，应用会默认 fail closed。
当前限流是单实例内存限流，适合 Render 免费实例的小范围试用；多实例或长期公开服务应升级到 Redis/托管限流。

部署后可用 `examples/dashboard_test_sales.csv` 在线验收，目标列填写 `revenue`。报告下载链接包含临时 token，并带有 `no-store` 缓存头，仍然只建议发给可信试用者；原始 CSV 保存在 `_inputs/` 目录，不通过网页下载路由暴露。

输出文件：

- `reports/sales_sample-<hash>/report.md`
- `reports/sales_sample-<hash>/report.html`
- `reports/sales_sample-<hash>/summary.json`
- `reports/sales_sample-<hash>/figures/*.png`

## 可选：使用虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
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
python3 -m compileall -q src tests analyze.py
python3 -m ruff check .
```

如果安装了开发依赖，也可以使用：

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pip install -e . --no-deps
pytest
```

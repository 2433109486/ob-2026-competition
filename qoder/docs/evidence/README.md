# 证据索引

| 文件 | 内容 | 生成方式 |
| --- | --- | --- |
| `health.json` | seekdb / PowerContext / embedding 健康状态 | `GET /api/health` |
| `bootstrap.json` | 资料数、画像、统计、推荐 | `GET /api/bootstrap` |
| `search_trace.json` | 一次混合检索的完整结果、候选数、两条 SQL | `POST /api/search` |
| `seekdb_schema.txt` | 建表语句、行数、样例片段、最近检索日志 | `SHOW CREATE TABLE` + `SELECT` |
| `powercontext_entries.json` | 当前 Scope 的 Atomic Memory | `POST /v1/memory/entries/list` |
| `powercontext_calls.jsonl` | 每次 PowerContext HTTP 调用（path/status/kind/scope） | 应用运行时追加 |
| `acceptance.json` | 23 项自动验收结果 | `scripts/acceptance.py` |
| `pytest.txt` | 12 项 pytest 结果 | `pytest -q` |
| `bibtex-sample.bib` | 从精读抽屉实际下载的 BibTeX 样例 | `GET /api/papers/{id}/bibtex` |
| `usage.md` | Qoder Sites 公开 URL、访问统计与效果边界 | Qoder Sites 控制台 |

> 这些文件由本机真实运行生成。UUID、时间戳、耗时每次重跑会变化。

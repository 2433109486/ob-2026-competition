# 指定技术的实际作用与核对记录

本项目同时使用 **seekdb** 与 **PowerContext**。两者分工明确：

- **seekdb = 事实与证据层**：资料、片段、向量/全文索引、检索日志。没有它，检索和矩阵没有内容。
- **PowerContext = 跨会话状态层**：研究画像、阅读进度、综述选择。没有它，系统仍能检索，但不会“越用越懂你”。

## 一、seekdb

### 1.1 实际用了哪些能力

| 能力 | 实现 | 项目中的位置 |
| --- | --- | --- |
| 结构化存储 | `papers` / `notes` / `search_log` / `activity` | `app/db.py` |
| 向量列 | `chunks.embedding VECTOR(768)` | `SCHEMA_STATEMENTS` |
| 向量索引 | `VECTOR INDEX ... DISTANCE=cosine TYPE=hnsw LIB=vsag` | 同上 |
| 中文全文索引 | `FULLTEXT INDEX ... WITH PARSER ngram2` | 同上 |
| 向量检索 | `cosine_distance(embedding, %s)` + `ORDER BY` | `app/retrieval.py` |
| 全文检索 | `MATCH(search_text) AGAINST(%s)` | 同上 |
| 条件过滤 | 状态、年份、类型、标签 `LIKE '%,tag,%'` | `_filters()` |
| 查询审计 | 每次检索记录 SQL、参数摘要、候选数、耗时 | `QueryTrace` / `search_trace.json` |
| 使用统计 | `search_log` + `DATE_SUB(NOW(), INTERVAL 7 DAY)` | `db.usage_stats()` |

### 1.2 关键 DDL（实际执行）

```sql
CREATE TABLE chunks (
  chunk_id VARCHAR(96) NOT NULL PRIMARY KEY,
  paper_id VARCHAR(64) NOT NULL,
  section VARCHAR(64) NOT NULL,
  page VARCHAR(32) NOT NULL DEFAULT '',
  content MEDIUMTEXT NOT NULL,
  search_text MEDIUMTEXT NOT NULL,
  embedding VECTOR(768),
  FULLTEXT INDEX ft_chunks (search_text) WITH PARSER ngram2,
  VECTOR INDEX vidx_chunks (embedding)
    WITH (DISTANCE=cosine, TYPE=hnsw, LIB=vsag),
  INDEX idx_chunks_paper (paper_id)
) ORGANIZATION = HEAP;
```

实际执行结果：`10 papers / 34 chunks / 5 notes`，`SELECT VERSION()` 返回
`5.7.25-OceanBase seekdb-v1.4.0.0`。

### 1.3 一次真实检索

输入：

```text
AI 编程助手对初学者学习迁移的影响
```

`POST /api/search` 的响应（节选，完整见 `docs/evidence/search_trace.json`）：

```json
{
  "total": 8,
  "latency_ms": 236,
  "mode": "hybrid-vector-fulltext",
  "counts": {
    "vector_candidates": 34,
    "text_candidates": 30,
    "fused_chunks": 34,
    "papers": 8
  },
  "trace": [
    {
      "label": "seekdb 向量召回（cosine_distance + HNSW）",
      "rows": 34,
      "elapsed_ms": 79
    },
    {
      "label": "seekdb 全文召回（ngram2 MATCH AGAINST）",
      "rows": 30,
      "elapsed_ms": 96
    }
  ]
}
```

结果中的每条 `paper` 都带：

```json
{
  "paper": {"paper_id": "kazemitabaar2023", "title": "...", "doi": "..."},
  "score": 0.5775,
  "reasons": ["语义相似度 0.55", "全文相关度 0.48", "记忆主题命中：初学者、学习迁移"],
  "best_chunk": {
    "section": "局限",
    "page": "p.13",
    "snippet": "研究只持续约一周，样本为 10–17 岁初学者……",
    "vector_similarity": 0.55,
    "text_score": 2.33
  }
}
```

可直接核对：

```sql
USE yanmai;
SELECT COUNT(*) FROM chunks;                     -- 34
SELECT paper_id, section, page FROM chunks LIMIT 5;
SELECT query, result_count, latency_ms, memory_used
FROM search_log ORDER BY created_at DESC LIMIT 5;
```

### 1.4 检索是否真的由 seekdb 决定

- 结果列表不是前端硬编码：`web/app.js` 只消费 `/api/search` 返回的 `results`。
- `total`、`counts`、`trace` 都来自实际 SQL 行数/耗时。
- 删除 `yanmai.chunks` 后检索会报错/为空，页面无法伪造结果；`scripts/acceptance.py`
  也会因 `vector_candidates > 0` 失败。
- 质检方式：打开「查看 SQL 轨迹」，或读 `docs/evidence/search_trace.json`。

## 二、PowerContext

### 2.1 实际用了哪些能力

| API | 用途 | 频次/证据 |
| --- | --- | --- |
| `POST /v1/scopes` | 创建「研脉 · 研究上下文」Scope | `scope_id=scp_...` |
| `POST /v1/memory/remember` | 写画像、阅读进度、综述决策、研究判断 | 每次保存一条 Atomic Memory |
| `POST /v1/memory/entries/list` | 读取当前 Scope 的记忆 | 首页、记忆页、检索前 |
| `POST /v1/memory/search` | 记忆召回测试 | `mode=fts` |
| `GET /v1/scopes/{id}` | Scope 存活检查 | 启动/健康检查 |
| `GET /health/live` | 服务健康 | 顶部状态与 `/api/health` |

### 2.2 实际写入的 Atomic Memory

`docs/evidence/powercontext_entries.json` 中可以看到真实记录。一个 `review_board` 例子：

```json
{
  "artifact": {
    "family": "atomic-memory",
    "artifact_id": "art_67d1cdcf79ac42fd93662a98aeb10141",
    "revision": 1
  },
  "kind": "review_board",
  "text": "{\"paper_ids\":[\"kazemitabaar2023\",\"bastani2025\",\"prather2023\",\"denny2024\"],\"question\":\"生成式 AI 编程助手如何影响初学者的编程学习与迁移？\",\"saved_at\":\"...\"}",
  "state": "active",
  "state_version": 0
}
```

一个 `reading_progress` 例子：

```json
{
  "paper_id": "kazemitabaar2023",
  "title": "AI 代码生成器如何支持编程入门学习者",
  "status": "read",
  "takeaway": "延迟后测必须保留；先前经验可能是调节变量。",
  "saved_at": "..."
}
```

### 2.3 记忆如何被复用（不是只写入）

| 记忆 | 复用位置 | 可观察结果 |
| --- | --- | --- |
| `research_profile.focus_tags` | `/api/search` 的 `tag_overlap` 加权 | 结果理由出现“记忆主题命中”；右侧显示画像 |
| `research_profile.field/stage` | 今日页问候与推荐 | “教育技术学 · 文献综述” |
| `reading_progress.status=reading` | 检索的 `status_boost`；今日页继续阅读 | 结果理由“正在精读，优先呈现” |
| `reading_progress.takeaway` | 精读抽屉“来自研究记忆” | 显示上次写的一句话结论 |
| `review_board.paper_ids` | 打开综述矩阵 | 4 篇文献自动勾选 |
| `review_board.question` | 矩阵/草稿标题 | 恢复上次研究问题 |
| `research_note` | 记忆时间线 + 召回测试 | 输入“学习迁移”可召回刚写的判断 |

### 2.4 核对方法

1. 打开 <http://127.0.0.1:8765> 的 PowerContext Dashboard（若启用），选择 Scope
   `研脉 · 研究上下文`。
2. 或调用：

```bash
curl -s -X POST http://127.0.0.1:8765/v1/memory/entries/list \
  -H 'Content-Type: application/json' \
  -d '{"scope_id":"<YOUR_SCOPE_ID>","limit":100}'
```

3. 或看本仓库 `docs/evidence/powercontext_entries.json` 与
   `docs/evidence/powercontext_calls.jsonl`（每次调用一行，含 path/status/kind/scope）。

### 2.5 降级行为

- `POWERCONTEXT_ENABLED=false` 或服务未启动：`/api/health` 显示 `ok=false`，
  前端顶部变为“记忆降级”，画像回退到 `seed/profile.json`。
- 检索仍可用，`memory.available=false`，但不会写入任何进度/矩阵选择。
- 写入接口返回 503 和具体错误，不静默失败。

## 三、两者如何分工（答辩口径）

> seekdb 决定“有哪些证据、哪段最相关”；PowerContext 决定“这个研究者是谁、读到哪里、上次为什么这样选”。
> 前者是可回查的事实，后者是可复用的上下文；两者不互相替代，也不会把记忆当成证据。

## 四、复现顺序

```powershell
# 1) seekdb 与 PowerContext 已启动
.\.venv\Scripts\python.exe scripts\check_env.py

# 2) 导入并写入初始记忆
.\.venv\Scripts\python.exe scripts\init_db.py --reset

# 3) 自动验收
.\.venv\Scripts\python.exe scripts\acceptance.py

# 4) 采集证据（健康、schema、trace、memory entries）
.\.venv\Scripts\python.exe scripts\collect_evidence.py
```

## 五、真实使用数据（开发自测，非外部用户）

| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 演示资料 | 10 份 | `SELECT COUNT(*) FROM papers` |
| 证据片段 | 34 个 | `SELECT COUNT(*) FROM chunks` |
| 自动验收 | 21/21 通过 | `docs/evidence/acceptance.json` |
| 检索端到端耗时 | 约 170–240 ms | `search_log` / acceptance |
| 浏览器交互 | 5 条主路径，无 console error | `scripts/e2e_ui.py` |
| 真实外部用户 | 暂无 | 不伪造 |

> 赛题鼓励真实用户使用。本仓库没有把开发自测包装成外部用户数据；
> 若后续邀请同学试用，可用 `/api/stats`、`search_log`、`activity` 和 Qoder Sites 访问统计补充。

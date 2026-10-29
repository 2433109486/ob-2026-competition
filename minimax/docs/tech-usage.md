# 技术使用记录

本文件记录三项指定技术在本次任务中的**实际调用**，对应文件均可直接打开核对。
本次运行时间：2026-10-29（UTC+8），运行标识 `20261029-164105`。

## 1. MiniMax：代码生成

### 1.1 调用参数

| 项 | 值 |
| --- | --- |
| 接口 | OpenAI 兼容 `POST https://api.minimaxi.com/v1/chat/completions` |
| 模型 | `MiniMax-M3.1-Flash` |
| 调用次数 | 1 次（第一次生成即通过测试，没有重试） |
| 输入 | 任务 BOOK-001 + 4 条规格/决策 + 3 个代码符号 + 20 个测试 + 修改前文件 |
| 输出 | `booknest/service.py`、`booknest/api.py` 两个完整文件 |
| 响应 ID | `073239b65f1a939342cff397feebdd79` |
| 时延 | 25,036 ms |
| Token | prompt 6,768；completion 3,387（其中 reasoning 1,259）；total 10,155 |
| 结果 | 应用后 `pytest` 20 passed |

### 1.2 记录文件

- `demo/minimax_records/call-01-request.json`：完整 system/user 消息。user 消息
  中包含 `01/02` 上下文（规格、代码、测试、PowerContext 状态）和当前文件。
- `demo/minimax_records/call-01-response.json`：MiniMax 原始响应、`usage`、
  `reasoning_content`、两个文件内容。
- `demo/minimax_records/call-01-patch.json`：解析、校验后的白名单补丁。
- `demo/minimax_records/calls.jsonl`：每次调用的摘要（模型、response id、时延、
  token、请求/响应字节数）。
- `demo/03_minimax_attempts.json`：应用结果与对应测试退出码。
- `artifacts/changes.diff`：把该响应应用到基线后的统一 diff。

### 1.3 约束与校验

`MiniMaxClient` 只允许修改：

```text
booknest/service.py
booknest/api.py
```

解析后逐条校验路径、非空内容、无 Markdown fence；应用前再次检查路径不能
逃逸仓库根目录。测试、规格、种子数据一律拒绝写入。本次响应正好只包含这两个
文件，没有越权路径。

## 2. MiniMax：嵌入

| 用途 | 模型 | 次数 | 文本数 | 维度 | 输入 token |
| --- | --- | --- | --- | --- | --- |
| v1 资料入库 | `embo-01` | 4 批 | 31 | 1536 | 7,208 |
| 任务查询（构建上下文） | `embo-01` | 1 批/次 | 1 | 1536 | 296/次 |
| v2 重新入库 | `embo-01` | 4 批 | 31 | 1536 | 7,832 |

记录：`demo/minimax_records/embeddings.jsonl`。接口为
`POST https://api.minimaxi.com/v1/embeddings`，请求体使用 MiniMax 原生
`{"model","texts","type"}`，响应为 `{"vectors":[...]}`。

## 3. seekdb：工程资料与检索

### 3.1 实际存储

| 表 | 行数（最终） | 作用 |
| --- | --- | --- |
| `documents` | 31（4 规格/决策 + 7 代码 + 20 测试） | 当前 head，含 `VECTOR(1536)` 与 ngram2 全文索引 |
| `document_versions` | 34 | 每次内容变化的不可变历史；v1 标为 `superseded` |
| `links` | 78 | `applies_to`、`verified_by`、`covered_by`、`governs` 图链接 |
| `context_runs` | 4 | 每次上下文构建的 JSON/Markdown |
| `query_log` | 24 | 4 次构建 × 6 条 SQL，含参数、行数、耗时 |
| `ingest_runs` | 2 | v1、v2 两次导入 |

数据库：`127.0.0.1:2881/sdd_context`，用户 `root`，空密码（本地演示）。
建表语句在 `sdd_context/db.py`，使用 `ORGANIZATION = HEAP`、
`FULLTEXT INDEX ... WITH PARSER ngram2`、
`VECTOR INDEX ... WITH (DISTANCE=cosine, TYPE=hnsw, LIB=vsag)`。

### 3.2 一条实际检索 SQL

```sql
SELECT doc_key, doc_type, source_path, title, version, status, tags,
       metadata_json, content,
       cosine_distance(embedding, %s) AS vector_distance,
       MATCH(search_text) AGAINST(%s) AS text_score
FROM documents
WHERE status='active' AND doc_type IN ('spec', 'decision')
ORDER BY vector_distance ASC
LIMIT %s
```

一次任务查询共 6 条 SQL：

1. 规格/决策：向量 + 全文排序，返回 4 条；
2. `links.applies_to`：返回 7 个代码符号；
3. 代码：向量 + 全文，返回 7 条；
4. `links.verified_by`：返回 25 条测试链接（去重后 20 个测试）；
5. `links.covered_by`：返回 14 条覆盖关系；
6. 测试：向量 + 全文，返回 20 条。

完整 SQL、参数、行数、耗时见
`demo/context/ctx-prompt-20261029-164105/queries.json` 与
`demo/context/06_after_restart/queries.json`。

### 3.3 查询结果如何进入上下文

- `specs[]`：4 条（001/002/003/DEC-001），每条带 requirements 与得分原因；
- `code[]`：3 个符号，带真实文件、行号、签名；
- `tests[]`：20 个测试，带 target/regression 类型和 spec 关联；
- `retrieval.queries[]`：把上面的 SQL 审计原样放进上下文 JSON。

## 4. PowerContext：任务状态

### 4.1 Scope 与检查点

| 项 | 值 |
| --- | --- |
| Server | `http://127.0.0.1:8765`，PowerContext 1.4.1 |
| Scope | `scp_3hdqn9aw6s4q80a1eq60g2jwv7` |
| 状态 kind | `sdd_task_state` |
| checkpoint 1 | `art_2b0d64d99cd74fc9872ab2b076811f2c`，revision 1，seq 1 |
| checkpoint 2 | `art_841f0772462644b886d42a0b9185113c`，revision 1，seq 2 |
| checkpoint 3 | `art_95eea80d85e4419bbb706164b51f5d8e`，revision 1，seq 3 |
| Source 证据 | 修改前测试日志、修改后测试日志各 1 条 |

写入路径：

```text
POST /v1/scopes                      -> 创建/复用 Scope
POST /v1/memory/remember             -> 写 sdd_task_state
POST /v1/memory/entries/list          -> 读全部检查点
POST /v1/sources/content              -> 保存 pytest 日志证据
```

读取时按 `task_id` + `seq` 取最新记录，返回：

```json
{
  "source": "powercontext",
  "status": "loaded",
  "seq": 3,
  "completed": ["...5 项..."],
  "todos": [],
  "verifications": ["修改前 11 failed", "修改后 20 passed", "规格 v2 生效"],
  "powercontext": {"artifact_id": "art_95ee...", "revision": 1, "state_version": 0}
}
```

### 4.2 重启复用证据

`scripts/run_demo.py` 在第 7 步：

1. 杀掉监听 8765 的 PowerContext 进程；
2. 确认 `/health/live` 不可达；
3. 重新启动同一 SQLite 数据库的 Server；
4. 用**新的 Python 进程**执行
   `python -m sdd_context.cli context --task tasks/BOOK-001.md`；
5. 从新生成的 `demo/context/06_after_restart/context.json` 读到
   `status=loaded, seq=3`，且 `completed` 含“updated BOOK-SPEC-001 to v2”。

记录：`demo/07_state_after_restart.json`、`demo/powercontext_records.jsonl`。

## 5. 如何复核

```powershell
# MiniMax 开发记录
Get-Content demo\minimax_records\calls.jsonl -Encoding UTF8
Get-Content demo\minimax_records\call-01-request.json -Encoding UTF8 | Select-Object -First 40

# seekdb 查询记录
Get-Content demo\context\ctx-prompt-20261029-164105\queries.json -Encoding UTF8

# PowerContext 状态
Get-Content demo\07_state_after_restart.json -Encoding UTF8
Get-Content demo\powercontext_records.jsonl -Encoding UTF8

# 一键复核
.\.venv\Scripts\python.exe scripts\verify_acceptance.py
```

> 仓库不包含 MiniMax key、PowerContext token 或任何真实凭据。`.env` 为本地
> 文件，已加入 `.gitignore`。

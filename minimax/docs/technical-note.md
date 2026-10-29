# 一页技术说明

## 模块结构

```text
specs/*.md ─┐
booknest/*.py ├─ ingest.py ──> seekdb: documents / document_versions / links
tests/*.py ──┘                     │
                                   ├─ cosine_distance(VECTOR(1536))  ← MiniMax embo-01
                                   ├─ MATCH(search_text) AGAINST(...) ← ngram2 全文
                                   └─ links 图扩展（applies_to / verified_by / covered_by）
tasks/BOOK-001.md ──> task 解析 ──> retrieval.py ──> context.py
                                                   │
                                                   ├─ 规格 + 代码 + 测试 + PowerContext 状态
                                                   └─ context.json / context.md
                                                              │
                                                              ▼
                                            MiniMax M3.1-Flash（受限 JSON 补丁）
                                                              │
                                                              ▼
                                            pytest（功能 + 回归）→ PowerContext checkpoint
```

## 上下文选择方式

1. **任务解析**：读取 Markdown frontmatter 的 `keywords`、`target_symbols`、
   `must_preserve`，正文作为查询文本。
2. **规格候选**：一条 SQL 同时取 `cosine_distance` 与 `MATCH ... AGAINST`，
   按 `status='active'` 过滤；得分：
   `0.50*向量 + 0.22*全文 + 0.18*标签重合 + 0.10*applies_to 命中`。
3. **代码候选**：`applies_to` 图链接给出必须修改的符号，向量/全文再补足；
   代码符号来自 `ast`，行号真实。
4. **测试候选**：`verified_by` 图链接给出规格对应的测试，`covered_by` 给出
   代码覆盖的测试；按 `target` 优先、再 `regression` 排序。
5. **状态合并**：从 PowerContext 读最新 `sdd_task_state`，把已完成、待办、
   验证结果放进同一份上下文。
6. **来源校验**：输出前逐条 `Path.exists()`；不存在的来源丢弃并告警，绝不
   返回固定答案。

规格更新时，`documents` 的 head 被 v2 覆盖，`document_versions` 保留 v1 并把
它标为 `superseded`；下一次检索只返回 v2，因此 `REQ-005` 会出现在上下文里。

## 三项技术的分工

| 技术 | 具体承担 | 证据 |
| --- | --- | --- |
| MiniMax `MiniMax-M3.1-Flash` | 读取上下文，生成 `booknest/service.py` 与 `booknest/api.py` 的完整实现；失败时带 pytest 输出重试（本次一次通过） | `demo/minimax_records/call-01-*`、`demo/03_minimax_attempts.json` |
| MiniMax `embo-01` | 为 31 条资料和每次任务查询生成 1536 维向量，写入 seekdb `VECTOR(1536)` | `demo/minimax_records/embeddings.jsonl` |
| seekdb 1.4.0.0 | 保存资料、版本、图链接、上下文运行和 SQL 审计；一条 SQL 完成向量 + 全文 + 标量过滤 | `demo/context/*/queries.json`、`demo/08_verify.txt` |
| PowerContext 1.4.1 | 保存 3 个任务检查点和 2 份测试日志 Source；重启 Server 后由新进程读回 seq=3 | `demo/state/checkpoint-*.json`、`demo/07_state_after_restart.json` |

## 关键取舍

- **不把聊天记录当上下文**：只索引仓库中的规格、代码符号和测试，来源可核对。
- **不把模型输出直接写盘**：MiniMax 只能返回两个白名单路径的完整文件；测试、
  规格、其他文件一律拒绝。
- **不把“检索结果”当“状态”**：任务进展单独写 PowerContext，重启后由新进程
  读取，而不是从上下文 JSON 里猜。
- **成本可控**：资料规模小，向量精确排序；只在任务查询时调用一次 embedding。
  已知未做增量 embedding，v2 重新导入会重算全部 31 条。

## 失败与边界

- 没有 MiniMax key：入库退回哈希向量，上下文/数据库/状态仍可验证，但不能
  执行新的模型生成。
- PowerContext 未启动：`build_context` 返回 `state.status="unavailable"` 并
  记录告警，不伪造状态。
- 规格缺 `## REQ-*`：入库告警，不阻断其他资料。
- 代码/测试路径不存在：从上下文丢弃并写入 `retrieval.warnings`。

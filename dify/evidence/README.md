# 运行证据说明

本目录是 **Dify 1.17.1 实际执行**的原始记录，采集时间 **2026-11-04**。

## 采集环境

| 项 | 值 |
| --- | --- |
| OS | Windows 11 + Docker Desktop（Linux 容器） |
| Dify | 1.17.1（官方 Docker Compose，`http://localhost:8080`） |
| 应用入口 | Dify 官方应用 API `POST /v1/chat-messages` |
| seekdb | 1.4.0.0（`5.7.25-OceanBase seekdb-v1.4.0.0`，容器，`127.0.0.1:2881`） |
| PowerContext | 1.4.1（SQLite，`127.0.0.1:8000`） |
| 庭审后端 | `uvicorn app.main:app --port 8088` |
| 模型 | MiniMax-M2.5（由后端 `/api/v1/llm/chat` 代理） |
| 玩家 | `p-dify-1001`（A/B）、`p-dify-2002`（C） |
| Dify app_id | `949f939c-26a8-49b6-a1a7-64b84281da86` |

## 文件

| 文件 | 内容 |
| --- | --- |
| `dify_run/dify_transcript.md` | A/B/C 三幕可读对话：每轮输入、Dify 返回、耗时、会话 ID |
| `dify_run/dify_transcript.json` | 每轮完整响应（answer、metadata、message_id、conversation_id） |
| `dify_run/{A,B,C}-turn-{1,2,3}.json` | 9 次 Dify API 调用的原始 JSON |
| `dify_run/dify_node_executions.json` | Dify Postgres 中的 `workflow_runs` + `workflow_node_executions`，每个成功 run 11 个节点 |
| `dify_run/dify_api.log` | Dify API 容器日志（chat-messages、错误） |
| `seekdb_records.json` | 72 条法典、3 条判例、2 个玩家、案卷、混合检索实测 |
| `powercontext_records.json` | `p-dify-1001` / `p-dify-2002` 的 Scope 与记忆命中 |
| `service_health.json` | 后端 / seekdb / PowerContext 健康快照 |

## 怎么读

1. 先看 `dify_run/dify_transcript.md` 的场景 B：三轮都出现「🧠 记忆回响」，引用的是场景 A 的猫案。
2. 再看 `dify_run/dify_node_executions.json`：成功的 run 都包含 `start → code_intake_payload → http_intake → code_intake → code_prompt → llm_judge → code_verdict → code_commit_payload → http_commit → code_render → answer`，11 个节点全部 `succeeded`。
3. 对照 `seekdb_records.json`：三条判例的 `case_no`、`cited`、`sentence_days` 与 Dify 返回的判决书一致。
4. 看 `powercontext_records.json`：`p-dify-1001` 有 2 条跨案记忆；`p-dify-2002` 只有它自己那条。

## 说明

- 本次证据**经过 Dify 工作流**：调用的是 Dify 应用 API，Dify 的 `workflow_runs` 与 `workflow_node_executions` 有完整节点记录，而不是脚本直接调后端。
- 出现了 1 个失败 run（`2026-11-04T13:24:12`）：调试时模型名 `MiniMax-Text-01` 已下线，后端返回 502；换成 `MiniMax-M2.5` 后全部成功。保留该记录以便核对排错过程。
- 模型 Key 从环境变量注入，未写入任何文件。

## 重新生成

```bash
export DIFY_BASE_URL=http://localhost
export DIFY_APP_TOKEN=app-REPLACE_ME
python scripts/run_dify_demo.py --out evidence/dify_run
python scripts/collect_evidence.py --out evidence
```

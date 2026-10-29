# 运行证据说明

本目录是一次真实运行的原始记录，采集时间 **2026-10-29**。

## 采集环境

| 项 | 值 |
| --- | --- |
| OS | Windows 11 |
| Python | 3.12.13 |
| seekdb | 1.4.0.0（`5.7.25-OceanBase seekdb-v1.4.0.0`，`127.0.0.1:2881`） |
| PowerContext | 1.4.1（SQLite，`127.0.0.1:8000`） |
| 庭审后端 | `uvicorn app.main:app --port 8088` |
| 模型 | MiniMax-Text-01（`https://api.minimax.chat/v1`） |
| 玩家 | `p-1001`（A/B）、`p-2002`（C） |

## 文件

| 文件 | 内容 |
| --- | --- |
| `transcript.md` | 三幕对话的人类可读版：每轮原告输入、法官输出、法条召回、记忆召回数、阶段变化 |
| `demo_run.json` | 机器可读版：每轮 intake 响应、提示词输入、模型原始文本 `llm_raw`、解析后的 `judge`、commit 响应、最终 `answer` |
| `seekdb_records.json` | seekdb 版本、72 条法典样例、3 条判例、2 个玩家档案、3 个案卷、逐轮记录、一次混合检索实测 |
| `powercontext_records.json` | Scope 列表、`p-1001` / `p-2002` 的记忆命中（含 Scope ID 与记忆原文） |
| `service_health.json` | 后端 `/api/v1/health` 快照（seekdb / PowerContext 状态、Embedding 配置） |

## 怎么读

1. **先看 `transcript.md` 的场景 B**：第 2、3 轮出现「🧠 记忆回响」，引用的是场景 A 的猫案。
2. **再看 `demo_run.json` 的 `scenarios[1].turns[0].memories_recalled`**：这里就是 PowerContext 返回给提示词的原始记忆。
3. **对照 `seekdb_records.json`**：`precedents` 里三条判例的 `case_no`、`cited`、`sentence_days` 与对话中的判决书一致。
4. **看 `powercontext_records.json`**：`p-1001` 有 2 条记忆，`p-2002` 只有它自己那 1 条（跑完 C 之后才写入）。

## 已知差异

- 本机没有安装 Dify 控制台，因此证据来自「按 Dify 节点顺序执行」的回放脚本（`scripts/run_demo.py`），而不是 Dify 内部日志。
  回放脚本使用的是与 DSL 相同的后端端点、相同的系统提示词、相同的 Code 节点解析逻辑，因此链路等价；Dify 内实测时模型措辞可能不同，但规则与数据结构一致。
- `evidence/demo_run.json` 中 `service_health.json` 的 `top_cited` 可能包含历史测试数据；以 `seekdb_records.json` 的 `precedents` 为准。
- 采集时模型 Key 从环境变量注入，未写入任何文件。

## 重新生成

```bash
python scripts/run_demo.py --reset --out evidence
python scripts/collect_evidence.py --out evidence
```

需要先按 `docs/02-运行说明.md` 启动 seekdb、PowerContext 与后端，并设置 `LLM_API_KEY`。

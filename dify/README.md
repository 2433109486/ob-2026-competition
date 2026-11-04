# ⚖️ 宇宙离谱法庭

> **一个会记仇的 AI 法官，一部 72 条的《宇宙离谱法典》，一间会把你的前科写进判决书的法庭。**
>
> Dify Chatflow 编排 · OceanBase seekdb 存法条/判例/案卷 · PowerContext 存跨会话记忆 · MiniMax 出演法官

---

## 1. 这是什么

公元 3026 年，人类把「情绪价值」写进宪法，最高法院下设**宇宙离谱法庭**，专门审理鸡毛蒜皮到宇宙级的民事纠纷。主审法官是 **包大仁**（编号 JDG-3026）：半文半白、冷幽默、认真对待每一件离谱小事。

你只需要说一句话：

> 「我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻了我的水杯。」

接下来三轮，法官会：

1. **立案**：从 seekdb 的 72 条法典里检索最贴切的条文，要求你补充证据；
2. **质证**：传唤被告、代述一句被告的辩解，继续援引法条；
3. **宣判**：给出刑期、赔偿、执行方式，并把本案写入判例库与你的「庭审档案」。

真正的钩子在第三次开庭：**同一个玩家 ID 再来，法官会翻旧账**。

> 「本官记得你。上次你起诉那只猫，判了 10 天；这次告周一，看来是惯犯了。」

这不是模型随口编的「记得」，而是 PowerContext 里真实写入、真实召回的记忆；法条也不是模型编的，而是 seekdb 混合检索出来的真实条文，编号与量刑区间都能在数据库里核对。

---

## 2. 3 分钟体验

### 2.1 启动依赖栈（seekdb + PowerContext + 庭审后端）

在 `dify/` 目录下：

```bash
export LLM_API_KEY=sk-REPLACE_ME      # 对话模型 Key，只给后端用
docker compose -f deploy/docker-compose.yml up -d --build
```

首次启动会：拉起 `oceanbase/seekdb:latest`、安装 `powercontext==1.4.1`、构建庭审后端；后端会自动建库、写入 72 条法典（约 10 秒）。

检查：

```bash
curl http://127.0.0.1:8088/api/v1/health
# {"ok":true,"seekdb":{"ok":true,...},"powercontext":{"ok":true,...}}
```

### 2.2 启动 Dify

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker compose up -d
```

Dify 默认在 `http://localhost:80`。首次进入需设置管理员账号。

> **网络要点**：DSL 里的 HTTP 节点默认写 `http://host.docker.internal:8088`，这是 Dify 容器访问宿主机的地址。
> - macOS / Windows Docker Desktop：开箱可用；
> - Linux：在 Dify 的 `docker-compose.yaml` 里给 `api` 与 `worker` 服务加
>   `extra_hosts: ["host.docker.internal:host-gateway"]`，或把 DSL 里的地址改成宿主机局域网 IP。
>
> **还要放行 Dify 的 SSRF 代理**：默认 Squid 会拒绝私网目标，HTTP 节点会 403。
> 在 Dify 的 `.env` 里设 `SSRF_PROXY_HTTP_URL=` / `SSRF_PROXY_HTTPS_URL=`（置空）并重建 api/worker，
> 或按 `docs/02-运行说明.md` 4.2.1 放行私网。

### 2.3 导入 DSL

Dify 控制台 → **创建应用 → 导入 DSL 文件** → 选择 `dsl/absurd-court.chatflow.yml`。

导入后只需要确认一件事：

- `① 立案检索`、`④ 法官包大仁`、`⑤ 落库与量刑` 三个 HTTP 节点都指向 `http://host.docker.internal:8088`（或你的实际地址）。

**不需要在 Dify 里绑定模型，也不需要安装模型供应商插件**：法官模型由庭审后端的 `/api/v1/llm/chat` 代理调用，Key 只在后端环境变量里。

保存 → 发布 → 打开聊天窗口。

### 2.4 开玩

直接输入：

```
我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻了我的水杯。
```

然后按法官提示补充证据，第三轮说「请判决」。

**体验跨会话记忆**：新建一个对话（同一个 Dify 用户 / 同一个玩家 ID），输入：

```
又是我。这次我要告周一，它每周都恶意到访，还带来早高峰。
```

法官应当提起上一场猫的案子。

---

## 3. 玩法与规则

| 环节 | 玩家做什么 | 系统做什么 |
| --- | --- | --- |
| 立案（第 1 轮） | 说出起诉对象与事由 | seekdb 按「向量 + 全文 + 案由标签」召回 3 条法条；PowerContext 召回历史记忆；法官归纳案由、要求举证 |
| 质证（第 2 轮） | 补充证据 / 狡辩 / 卖惨 | 法官传唤被告、继续援引法条；后端把被告与案由写回案卷 |
| 宣判（第 3 轮或说「请判决」） | 请求判决 | 后端校验引用、按「法定区间 × 离谱指数 × 态度 × 累犯」计算刑期，写判例库、写 PowerContext 记忆 |
| 再次开庭 | 新建会话，继续起诉 | 法官召回上次判决，在台词里翻旧账；量刑上限随前科提高 |

**几条暗规则**：

- 模型只能引用检索结果里的法条，编造的编号会被后端丢弃；
- 刑期最终由后端计算并夹在法定区间内（累犯上限每次 +3 天），模型只能给建议值；
- 案号是真实的序列号：`（3026）离民初字第0001号`、`0002`……
- 玩家称号随前科升级：法庭新鲜人 → 初犯旁听生 → 法庭常客 → 诉讼惯犯 → 法外狂徒；
- 如果 PowerContext 挂了，庭审照常进行，只是法官会失忆（响应里 `powercontext.status = degraded`）。

---

## 4. 技术分工

```text
                         ┌──────────────────────────────────────────────┐
   玩家输入 ───────────▶ │  Dify Chatflow（11 个节点，Dify 1.17.1 实跑）  │
                         │  start → Code 组装请求 → HTTP 立案            │
                         │        → Code 解析 → Code 组装提示词          │
                         │        → HTTP 法官模型 → Code 解析 JSON       │
                         │        → Code 组装请求 → HTTP 落库            │
                         │        → Code 渲染 → answer                   │
                         └───────┬──────────────────────────┬───────────┘
                                 │ HTTP                     │ HTTP
                    ┌────────────▼───────────┐   ┌─────────▼────────────┐
                    │ 庭审后端 FastAPI :8088  │   │ 模型代理 /llm/chat    │
                    │ 检索 / 量刑 / 校验 / 渲染│   │ Key 只在后端环境变量   │
                    └───────┬────────────────┘   └─────────┬────────────┘
                            │ SQL                          │ memory search/remember
                    ┌───────▼──────────────────────────────┴─────────┐
                    │ OceanBase seekdb :2881                          │
                    │ statutes · precedents · players / cases / turns │
                    └─────────────────────────────────────────────────┘
                            ▲
                            │ HTTP :8000
                    ┌───────┴────────────┐
                    │ PowerContext 1.4.1 │  跨会话记忆（独立服务）
                    └────────────────────┘
```

| 技术 | 在本作品里具体做什么 | 可核对的证据 |
| --- | --- | --- |
| **Dify** | Chatflow 编排：输入 → HTTP 检索 → 提示词组装 → HTTP 模型调用 → JSON 解析 → HTTP 落库 → 渲染输出 | `dsl/absurd-court.chatflow.yml`（11 节点 / 10 边）；`evidence/dify_run/dify_node_executions.json` 显示每个 run 的 11 个节点全部 succeeded；`evidence/dify_run/dify_transcript.md` 是 Dify `/v1/chat-messages` 的真实回复 |
| **seekdb** | ① 72 条法典 + 向量索引 + ngram2 全文索引，做混合检索；② 判例库；③ 玩家档案、案卷、庭审记录、案号序列 | `evidence/seekdb_records.json`：3 条判例、2 个玩家、72 条法典、一次混合检索实测 |
| **PowerContext** | 保存法官对玩家的主观记忆，新会话按相关度召回；把每轮庭审写入 Source journal | `evidence/powercontext_records.json`：`p-dify-1001` 的跨案记忆；`evidence/dify_run/dify_transcript.md` 场景 B 的「🧠 记忆回响」 |
| **模型代理** | `/api/v1/llm/chat` 用后端环境变量里的 Key 调 MiniMax，Dify 不接触凭据 | `evidence/dify_run/dify_transcript.md` 每轮 5~15 秒的模型回复 |

**为什么不是「为了用而用」**：

- 法条不能靠模型编——法典有 72 条，编号、量刑区间、赔偿都必须是数据库里的真值，所以需要 seekdb 的检索与结构化过滤；
- 「记得你」不能靠把历史对话塞回上下文——Dify 会话上下文只覆盖当前会话，换一个会话就断了；跨会话的「前科」必须落到 PowerContext；
- 判例库让世界有连续性：新玩家也能看到「本院曾判……」。

更细的分工与接口见 [`docs/04-技术结合与分工.md`](docs/04-技术结合与分工.md)。

---

## 5. 验证样例（Dify 实跑）

完整记录：[`evidence/dify_run/dify_transcript.md`](evidence/dify_run/dify_transcript.md)
原始响应：[`evidence/dify_run/dify_transcript.json`](evidence/dify_run/dify_transcript.json)
节点执行：[`evidence/dify_run/dify_node_executions.json`](evidence/dify_run/dify_node_executions.json)

运行方式：Dify 1.17.1（Docker Compose）+ 官方应用 API `POST /v1/chat-messages`，A/B/C 各 3 轮，共 9 次 `workflow_run`，每次 11 个节点全部成功。

| 场景 | 玩家 | 输入 | 实际结果 |
| --- | --- | --- | --- |
| A 首案 | `p-dify-1001` | 起诉猫凌晨蹦迪 + 打翻水杯，3 轮 | 引用 `AB-001`/`AB-002`，判 **10 天**，赔偿小鱼干三条 |
| B 跨会话 | `p-dify-1001` | **新会话**，起诉周一，3 轮 | 三轮均出现「🧠 记忆回响」，引用 `AB-010`，判 **7 天**（累犯上限 10 天） |
| C 对照 | `p-dify-2002` | 与 A 相同的猫案，3 轮 | 无记忆回响，引用 `AB-001`/`AB-002`，判 **5 天** |

- B 的每次回复都主动提到 A 案的判决/评语，说明 PowerContext 的记忆按玩家隔离、跨会话复用；
- C 是全新玩家，没有任何「本官记得你」；A 与 C 同案不同判，是因为模型给出的离谱指数/态度不同，**两者都落在 AB-001 的 3–15 天区间内**，刑期由后端夹取；
- 9 次运行的 `workflow_node_executions` 都包含完整 11 个节点（`start → code_intake_payload → http_intake → code_intake → code_prompt → llm_judge → code_verdict → code_commit_payload → http_commit → code_render → answer`）。

数据库落库核对（`evidence/seekdb_records.json`）：

```json
{
  "seekdb_version": "5.7.25-OceanBase seekdb-v1.4.0.0",
  "statutes": { "count": 72 },
  "precedents": [
    { "case_no": "（3026）离民初字第0001号", "defendant": "原告的猫", "cited": "AB-001", "sentence_days": 10 },
    { "case_no": "（3026）离民初字第0002号", "defendant": "周一", "cited": "AB-010", "sentence_days": 7 },
    { "case_no": "（3026）离民初字第0003号", "defendant": "涉事猫（姓名待定）", "cited": "AB-001,AB-002", "sentence_days": 5 }
  ]
}
```

---

## 6. 目录结构

```text
dify/
├── README.md                     # 本文件
├── dsl/
│   ├── absurd-court.chatflow.yml # Dify Chatflow DSL（11 节点）
│   └── README.md                 # 导入步骤、地址/后端配置
├── backend/                      # 庭审后端（FastAPI）
│   ├── app/
│   │   ├── statutes.py           # 72 条《宇宙离谱法典》
│   │   ├── db.py                 # seekdb：建表、混合检索、判例、档案
│   │   ├── powercontext.py       # PowerContext HTTP 客户端
│   │   ├── court.py              # 立案/量刑/落库
│   │   ├── prompt.py             # 法官提示词（与 DSL 内一致）
│   │   ├── render.py             # 判决书渲染
│   │   ├── main.py               # API（含 /llm/chat 模型代理）
│   │   └── cli.py                # 初始化 / 自检
│   ├── tests/                    # 纯函数单元测试
│   └── requirements.txt
├── deploy/
│   ├── docker-compose.yml        # seekdb + PowerContext + 后端
│   ├── court.Dockerfile
│   ├── powercontext.Dockerfile
│   └── .env.example
├── scripts/
│   ├── run_dify_demo.py          # 通过 Dify 应用 API 跑 A/B/C（正式证据）
│   ├── run_demo.py               # 可选：不经 Dify 的后端回放
│   ├── collect_evidence.py       # 抓取 seekdb / PowerContext 证据
│   └── validate_dsl.py           # DSL 静态校验
├── evidence/
│   ├── dify_run/                 # Dify 实跑：9 次回复 + 节点执行 + API 日志
│   ├── seekdb_records.json
│   ├── powercontext_records.json
│   └── service_health.json
└── docs/
    ├── 01-创意与玩法.md
    ├── 02-运行说明.md
    ├── 03-验证样例.md
    └── 04-技术结合与分工.md
```

---

## 7. 版本与兼容性

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Dify | **1.17.1**（实际运行） | DSL `version: 0.1.5`，导入 1.17.1 自动迁移为 0.7.0（`completed-with-warnings`），11 节点全部运行 |
| OceanBase seekdb | 1.4.0.0 | `VECTOR(n)`、`VECTOR INDEX ... hnsw`、`FULLTEXT ... ngram2`、`ORGANIZATION = HEAP` |
| PowerContext | 1.4.1 | `/v1/scopes`、`/v1/memory/search`、`/v1/memory/remember`、`/v1/sources/content` |
| 庭审后端 | Python 3.12 / FastAPI | `backend/requirements.txt` |
| 模型 | MiniMax-M2.5（录制证据时） | 后端 `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` 可换成任意 OpenAI 兼容对话模型 |

---

## 8. 已知限制

- **不依赖 Embedding 服务**：默认使用零依赖的确定性哈希向量（128 维），配合 72 条法典的丰富关键词与全文索引，离线可跑。可切换真实 Embedding（见 `docs/02-运行说明.md`），但需按新维度重建索引。
- **模型输出不是 100% 稳定**：法官措辞、离谱指数、建议刑期会变；后端会把刑期夹回法定区间。A/C 同案不同判即为例证，但都在法定区间内。
- **Dify 侧证据形态**：本次运行通过 Dify 官方应用 API `/v1/chat-messages` 驱动，并保留 `workflow_node_executions` 与 Dify API 日志；未额外录制浏览器操作视频，但每个 run 的节点级状态可核对。
- **单机/单实例**：案号序列用 seekdb 的 `counters` 表自增，适合演示；高并发下需要改成号段或分布式 ID。
- **PowerContext 记忆检索是文本召回**：未配置其 embedding 模型时使用关键词召回；代码里做了「相关查询为空 → 退回庭审关键词」的兜底。

---

## 9. 提交清单

| 产物 | 位置 | 说明 |
| --- | --- | --- |
| Dify DSL | `dsl/absurd-court.chatflow.yml` | 11 节点 Chatflow，导入即用（只改后端地址） |
| 运行说明 | `docs/02-运行说明.md` | Docker / 本机两种起法，Dify 部署与网络 |
| 验证样例 | `docs/03-验证样例.md` + `evidence/dify_run/` | A/B/C 三幕、Dify 原始响应、节点执行记录 |
| 配套源码 | `backend/` | FastAPI 后端、法典、检索、量刑、模型代理 |
| 部署配置 | `deploy/` | seekdb + PowerContext + 后端的 compose 与 Dockerfile |
| 数据初始化 | `backend/app/cli.py` | `python -m app.cli init --recreate` |
| 复现脚本 | `scripts/` | Dify 回放、证据抓取、DSL 校验 |

**没有提交任何真实密钥**：模型 Key 只从环境变量 `LLM_API_KEY` / `EMBEDDING_API_KEY` 读取；`evidence/` 里也不含凭据。

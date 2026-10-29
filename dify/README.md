# ⚖️ 宇宙离谱法庭

> **一个会记仇的 AI 法官，一部 72 条的《宇宙离谱法典》，一间会把你的前科写进判决书的法庭。**
>
> Dify Chatflow 编排 · OceanBase seekdb 存法条/判例/案卷 · PowerContext 存跨会话记忆 · MiniMax 出演法官

---

## 1. 这是什么

公元 3026 年，人类把「情绪价值」写进宪法，最高法院下设**宇宙离谱法庭**，专门审理鸡毛蒜皮到宇宙级的民事纠纷。主审法官是 **包大仁**（编号 JDG-3026）：半文半白、冷幽默、认真对待每一件离谱小事。

你只需要说一句话：

> 「我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻我的水杯。」

接下来三轮，法官会：

1. **立案**：从 seekdb 的 72 条法典里检索最贴切的条文，要求你补充证据；
2. **质证**：传唤被告、代述一句被告的辩解，继续援引法条；
3. **宣判**：给出刑期、赔偿、执行方式，并把本案写入判例库与你的「庭审档案」。

真正的钩子在第三次开庭：**同一个玩家 ID 再来，法官会翻旧账**。

> 「本官记得你。上次你起诉那只猫，判了 7 天；这次告周一，看来是惯犯了。」

这不是模型随口编的「记得」，而是 PowerContext 里真实写入、真实召回的记忆；法条也不是模型编的，而是 seekdb 混合检索出来的真实条文，编号与量刑区间都能在数据库里核对。

---

## 2. 3 分钟体验

### 2.1 启动依赖栈（seekdb + PowerContext + 庭审后端）

在 `dify/` 目录下：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

首次启动会：拉起 `oceanbase/seekdb:latest`、安装 `powercontext==1.4.1`、构建庭审后端；后端会自动建库、写入 72 条法典（约 10 秒）。

检查：

```bash
curl http://127.0.0.1:8088/api/v1/health
# {"ok":true,"seekdb":{"ok":true,...},"powercontext":{"ok":true,...}}
```

### 2.2 启动 Dify

使用官方 Docker Compose（推荐 Dify 1.x，开发时对齐 1.17.1 的 DSL 语义）：

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker compose up -d
```

Dify 默认在 `http://localhost:80`。首次进入需设置管理员账号。

> **网络要点**：DSL 里的两个 HTTP 节点默认写的是 `http://host.docker.internal:8088`，这是 Dify 容器访问宿主机的地址。
> - macOS / Windows Docker Desktop：开箱可用；
> - Linux：在 Dify 的 `docker-compose.yaml` 里给 `api` 与 `worker` 服务加
>   `extra_hosts: ["host.docker.internal:host-gateway"]`，或把 DSL 里的地址改成宿主机局域网 IP。

### 2.3 导入 DSL

Dify 控制台 → **创建应用 → 导入 DSL 文件** → 选择 `dsl/absurd-court.chatflow.yml`。

导入后做两件事：

1. **绑定模型**：打开 `③ 法官包大仁` 节点，把模型换成你工作区里可用的对话模型（DSL 预设为 `minimax / MiniMax-Text-01`；换别的模型不需要改提示词）。
2. **确认地址**：`① 立案检索` 与 `⑤ 落库与量刑` 两个 HTTP 节点应指向 `http://host.docker.internal:8088`（或你的实际地址）。

保存 → 发布 → 打开聊天窗口。

### 2.4 开玩

直接输入：

```
我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻我的水杯。
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
                         ┌──────────────────────────────────────────┐
   玩家输入 ───────────▶ │  Dify Chatflow（8 个节点）                │
                         │  start → HTTP intake → Code 解析          │
                         │        → LLM 法官 → Code 解析 JSON        │
                         │        → HTTP commit → Code 渲染 → answer │
                         └───────┬───────────────────────┬──────────┘
                                 │ HTTP                   │ HTTP
                    ┌────────────▼───────────┐  ┌────────▼─────────────┐
                    │ 庭审后端 FastAPI :8088  │  │ PowerContext :8000   │
                    │ 量刑 / 校验 / 渲染       │  │ 跨会话记忆            │
                    └───────┬────────────────┘  └────────▲─────────────┘
                            │ SQL                          │ memory search/remember
                    ┌───────▼──────────────────────────────┴─────────┐
                    │ OceanBase seekdb :2881                          │
                    │ statutes（法典）· precedents（判例）             │
                    │ players / cases / turns（档案与案卷）            │
                    └─────────────────────────────────────────────────┘
```

| 技术 | 在本作品里具体做什么 | 可核对的证据 |
| --- | --- | --- |
| **Dify** | Chatflow 编排：输入 → HTTP 检索 → 提示词组装 → 模型调用 → JSON 解析 → HTTP 落库 → 渲染输出；提示词、开场白、建议问题都在 DSL 内 | `dsl/absurd-court.chatflow.yml`（8 节点 / 7 边，`scripts/validate_dsl.py` 校验通过） |
| **seekdb** | ① 72 条法典 + 向量索引（HNSW，当前精确排序）+ ngram2 全文索引，做混合检索；② 判例库供「本院曾判」召回；③ 玩家档案、案卷、庭审记录、案号序列 | `evidence/seekdb_records.json`：3 条判例、2 个玩家、72 条法典、一次混合检索的命中与融合分 |
| **PowerContext** | 保存法官对玩家的主观记忆（上次起诉谁、判了几天、法官评语），新会话按相关度召回；同时把每轮庭审写入 Source journal | `evidence/powercontext_records.json`：`p-1001` 的 2 条跨案记忆；`evidence/transcript.md` 场景 B 的「🧠 记忆回响」 |

**为什么不是「为了用而用」**：

- 法条不能靠模型编——法典有 72 条，编号、量刑区间、赔偿都必须是数据库里的真值，所以需要 seekdb 的检索与结构化过滤；
- 「记得你」不能靠把历史对话塞回上下文——Dify 会话上下文只覆盖当前会话，换一个会话就断了；跨会话的「前科」必须落到 PowerContext，才能在第三次开庭时被召回；
- 判例库让世界有连续性：新玩家也能看到「本院曾判……」，而不是每次都是平行宇宙。

更细的分工与接口见 [`docs/04-技术结合与分工.md`](docs/04-技术结合与分工.md)。

---

## 5. 验证样例（已实际跑通）

完整记录见 [`evidence/transcript.md`](evidence/transcript.md)，原始请求/响应见 [`evidence/demo_run.json`](evidence/demo_run.json)。

| 场景 | 玩家 | 输入 | 预期 | 实际结果 |
| --- | --- | --- | --- | --- |
| A 首案 | `p-1001` | 起诉猫凌晨蹦迪 + 打翻水杯，共 3 轮 | 无法条编造；第 3 轮宣判 | 引用 `AB-001`/`AB-002`，判 **7 天**，赔偿小鱼干 + 键盘垫 |
| B 跨会话 | `p-1001` | 新会话，起诉周一，共 3 轮 | 法官提起 A 案；量刑受前科影响 | 召回 A 案记忆，两轮台词出现「🧠 记忆回响」，引用 `AB-010`，判 **1 天**（累犯上限 10 天） |
| C 对照 | `p-2002` | 与 A 完全相同的猫案，共 3 轮 | 无记忆、无翻旧账；判决与 A 一致 | 无记忆召回，判 **7 天**，与 A 相同 |

A 与 C 的判决一致，说明系统没有「全局记忆串味」；B 出现记忆回响而 C 没有，说明 PowerContext 的记忆确实按玩家隔离、按会话复用。

数据库落库核对（`evidence/seekdb_records.json`）：

```json
{
  "seekdb_version": "5.7.25-OceanBase seekdb-v1.4.0.0",
  "statutes": { "count": 72 },
  "precedents": [
    { "case_no": "（3026）离民初字第0001号", "defendant": "原告的猫", "cited": "AB-001,AB-002", "sentence_days": 7 },
    { "case_no": "（3026）离民初字第0002号", "defendant": "周一", "cited": "AB-010", "sentence_days": 1 },
    { "case_no": "（3026）离民初字第0003号", "defendant": "原告的猫", "cited": "AB-001,AB-002", "sentence_days": 7 }
  ]
}
```

---

## 6. 目录结构

```text
dify/
├── README.md                     # 本文件
├── dsl/
│   ├── absurd-court.chatflow.yml # Dify Chatflow DSL（8 节点）
│   └── README.md                 # 导入顺序、模型/地址重绑定
├── backend/                      # 庭审后端（FastAPI）
│   ├── app/
│   │   ├── statutes.py           # 72 条《宇宙离谱法典》
│   │   ├── db.py                 # seekdb：建表、混合检索、判例、档案
│   │   ├── powercontext.py       # PowerContext HTTP 客户端
│   │   ├── court.py              # 立案/量刑/落库
│   │   ├── prompt.py             # 法官提示词（与 DSL 一致）
│   │   ├── render.py             # 判决书渲染
│   │   ├── main.py               # API
│   │   └── cli.py                # 初始化 / 自检
│   ├── requirements.txt
│   └── ...
├── deploy/
│   ├── docker-compose.yml        # seekdb + PowerContext + 后端
│   ├── court.Dockerfile
│   ├── powercontext.Dockerfile
│   └── .env.example
├── scripts/
│   ├── run_demo.py               # 按 Dify 节点顺序回放 A/B/C 三幕
│   ├── collect_evidence.py       # 抓取 seekdb / PowerContext 证据
│   └── validate_dsl.py           # DSL 静态校验
├── evidence/                     # 实测记录（见第 5 节）
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
| Dify | 1.x（对齐 1.17.1 语义） | DSL `version: 0.1.5`；Dify 导入时会自动迁移并给出一次版本提示，不影响节点导入 |
| OceanBase seekdb | 1.4.0.0 | 使用 `VECTOR(n)`、`VECTOR INDEX ... WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag)`、`FULLTEXT INDEX ... WITH PARSER ngram2`、`ORGANIZATION = HEAP` |
| PowerContext | 1.4.1 | 使用 `/v1/scopes`、`/v1/memory/search`、`/v1/memory/remember`、`/v1/sources/content` |
| 庭审后端 | Python 3.12 / FastAPI | `backend/requirements.txt` |
| 模型 | MiniMax-Text-01（录制证据时） | 任意 OpenAI 兼容对话模型均可，改绑 LLM 节点即可 |

---

## 8. 已知限制与验证边界

- **不依赖 Embedding 服务**：默认使用零依赖的确定性哈希向量（128 维），配合 72 条法典的丰富关键词与全文索引，离线可跑。想要更好的语义召回，可切换真实 Embedding（见 `docs/02-运行说明.md` 第 6 节），但需要按新维度重建索引。
- **Dify 侧交付边界**：提交环境未安装 Dify 控制台，因此没有 Dify 运行截图；DSL 通过静态校验（节点、边、变量引用、Code 语法），后端链路（检索 → 提示词 → 模型 → 落库 → 记忆召回）已用 `scripts/run_demo.py` 按同一节点顺序真实跑通并留证。评审导入 DSL 后走的是同一套后端与提示词。
- **模型输出不是 100% 稳定**：法官可能给出不同措辞或建议刑期；后端会把刑期夹回法定区间，并在 `evidence/demo_run.json` 里保留模型原始输出，便于核对「哪些是模型说的、哪些是后端定的」。
- **单机/单实例**：案号序列用 seekdb 的 `counters` 表自增，适合演示；高并发下需要改成号段或分布式 ID。
- **PowerContext 记忆检索是文本召回**：未配置其 embedding 模型时，使用关键词召回；代码里做了「相关查询为空 → 退回庭审关键词」的兜底，保证跨会话连续性。

---

## 9. 提交清单

| 产物 | 位置 | 说明 |
| --- | --- | --- |
| Dify DSL | `dsl/absurd-court.chatflow.yml` | 8 节点 Chatflow，导入即用（改模型/地址） |
| 运行说明 | `docs/02-运行说明.md` | Docker / 本机两种起法，Dify 部署与网络 |
| 验证样例 | `docs/03-验证样例.md` + `evidence/` | A/B/C 三幕、预期、实际输出、落库记录 |
| 配套源码 | `backend/` | FastAPI 后端、法典、检索、量刑 |
| 部署配置 | `deploy/` | seekdb + PowerContext + 后端的 compose 与 Dockerfile |
| 数据初始化 | `backend/app/cli.py` | `python -m app.cli init --recreate` |
| 复现脚本 | `scripts/` | 回放、证据抓取、DSL 校验 |

**没有提交任何真实密钥**：模型 Key 只从环境变量 `LLM_API_KEY` / `EMBEDDING_API_KEY` 读取；`evidence/` 里也不含凭据。


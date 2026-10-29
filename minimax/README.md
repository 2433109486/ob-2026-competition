# 规有所依：BookNest SDD 上下文管理系统（MiniMax 赛道）

面向持续演进项目的规格驱动开发（Spec-Driven Development）上下文模块。它从
**seekdb** 中检索当前有效的规格、相关代码符号和测试，把任务进展写入
**PowerContext** 并在重启后读回，再把上下文交给 **MiniMax** 完成一次真实的
代码修改，最后用同一组测试验证修改前后。

- 业务样例：`booknest/`，一个只用标准库运行的图书商品搜索服务与 HTTP API。
- 上下文模块：`sdd_context/`，CLI、Python API 均可调用。
- 验证样例：`tasks/BOOK-001.md`，增加闭区间价格筛选 `min_price` / `max_price`。
- 证据目录：`demo/`、`artifacts/`。
- 说明文档：`docs/`。

## 1. 结果先行

| 验收项 | 证据 | 实际结果 |
| --- | --- | --- |
| 能够运行 | `demo/08_verify.txt`、`demo/summary.json` | 数据初始化、上下文构建、测试均可复现 |
| MiniMax 实际参与 | `demo/minimax_records/call-01-*`、`demo/03_minimax_attempts.json` | MiniMax-M3.1-Flash 生成 2 个文件的完整内容，一次通过 20 个测试 |
| 上下文正确 | `demo/01_context_before.*`、`demo/04_context_after_spec_update.*` | 命中 4 条规格/决策、3 个代码符号、20 个测试；规格升到 v2 后返回 `REQ-005` |
| 数据库实际参与 | `demo/context/*/queries.json`、`demo/powercontext_records.jsonl` | seekdb 中 31 条资料、78 条链接；每次上下文执行 6 条 SQL |
| 状态能够复用 | `demo/07_state_after_restart.json` | PowerContext 重启后从新进程读到 seq=3 的完成项与两次验证结果 |
| 代码修改有效 | `artifacts/test_logs/01_tests_before.log`、`02_tests_after.log` | 修改前 `11 failed, 9 passed`；修改后 `20 passed` |

修改前失败的是 11 个目标功能测试，9 个既有回归测试在修改前已经通过。两者使用
同一组测试文件、同一组断言，没有删除、跳过或修改预期值。

## 2. 目录结构

```text
minimax/
├── booknest/                 # 可运行业务样例（搜索服务 + stdlib HTTP API）
│   ├── seed/products.json
│   ├── service.py            # 目标修改点
│   └── api.py                # 目标修改点
├── tests/
│   ├── test_price_filter.py       # 11 个目标测试中的 7 个
│   ├── test_api_price_filter.py   # 11 个目标测试中的 4 个
│   └── test_search_existing.py    # 9 个回归测试
├── specs/                    # 当前有效规格/决策（v2）
│   ├── BOOK-SPEC-001-price-filter.md
│   ├── BOOK-SPEC-002-search-compatibility.md
│   ├── BOOK-SPEC-003-api-contract.md
│   ├── BOOK-DEC-001-price-boundaries.md
│   ├── archive/              # v1 历史快照
│   └── updates/              # 演示用 v2 更新文件
├── tasks/BOOK-001.md         # 验证样例任务
├── sdd_context/              # 上下文模块
│   ├── config.py             # 环境配置
│   ├── db.py                 # seekdb 连接、DDL、查询审计
│   ├── embeddings.py         # MiniMax embo-01 + 确定性回退
│   ├── ingest.py             # 规格/代码/测试入库、版本与链接
│   ├── retrieval.py          # 向量 + 全文 + 图链接混合检索
│   ├── context.py            # 上下文组装与 Markdown 渲染
│   ├── powercontext.py       # PowerContext 状态读写
│   ├── minimax_client.py     # MiniMax 调用与受限补丁协议
│   └── cli.py                # CLI 入口
├── baseline/                 # 修改前代码与 v1 规格快照
├── examples/state-payload.json
├── artifacts/                # before/after 快照、diff、测试日志
├── demo/                     # 上下文、MiniMax 调用、PowerContext 记录
├── scripts/
│   ├── run_demo.py           # 一键跑完整验证链路
│   ├── reproduce_before.py   # 在临时目录复现修改前失败
│   ├── verify_acceptance.py  # 核对提交证据
│   └── powercontext_service.py
├── docs/
│   ├── validation-sample.md  # 验证样例（必看）
│   ├── technical-note.md     # 一页技术说明
│   ├── tech-usage.md         # 三项技术使用记录
│   └── test-report.md        # 测试报告
├── .env.example
├── .env.powercontext.example
├── pyproject.toml
└── requirements.txt
```

## 3. 依赖与版本

本项目在 **Windows 11 + PowerShell 7** 上完成，Linux/macOS 命令等价。

| 组件 | 实际版本 | 用途 |
| --- | --- | --- |
| Python | 3.12.13（`uv` 管理） | 模块、样例、测试 |
| seekdb | 1.4.0.0（Windows 原生） | 工程资料、版本、链接、向量/全文索引 |
| PowerContext | 1.4.1（SQLite 后端） | 任务检查点与验证结果 |
| MiniMax 生成 | `MiniMax-M3.1-Flash`，OpenAI 兼容接口 `https://api.minimaxi.com/v1` | 生成代码修改 |
| MiniMax 嵌入 | `embo-01`，1536 维 | 资料与查询向量 |
| PyMySQL | 1.2.0（PowerContext 环境）/ `>=1.1.1`（项目） | seekdb SQL |
| pytest | 8.x | 功能与回归测试 |

> seekdb 1.4.0.0 原生 Windows 版可直接启动；本项目没有使用 Docker。PowerContext
> 官方对 Windows 标注为 experimental，本项目使用其 SQLite 后端并验证了状态复用。

## 4. 安装

### 4.1 启动 seekdb

使用本机已安装的 seekdb 1.4.0.0（监听 `127.0.0.1:2881`，用户 `root`，空密码）：

```powershell
cd D:\agent\sandbox\seekdb14\seekdb-data
& 'D:\agent\sandbox\seekdb14\seekdb-1.4.0\seekdb.exe' `
  '--base-dir=D:/agent/sandbox/seekdb14/seekdb-data' '--port=2881' --nodaemon
```

保持该终端打开。验证：

```powershell
.\.venv\Scripts\python.exe -c "import pymysql; c=pymysql.connect(host='127.0.0.1',port=2881,user='root',password=''); print(c.cursor().execute('SELECT 1'))"
```

其他环境的 seekdb 安装方式见官方文档；连接参数通过 `SEEKDB_*` 环境变量覆盖。

### 4.2 安装 PowerContext 1.4.1

```powershell
cd D:\agent\sandbox
uv venv pc-venv --python 3.12
uv pip install --python .\pc-venv\Scripts\python.exe "powercontext[cli,server]==1.4.1"
```

如果 `powercontext` 不在 PATH，设置：

```powershell
$env:POWERCONTEXT_EXE = 'D:\agent\sandbox\pc-venv\Scripts\powercontext.exe'
```

> Windows 上 `jieba==0.42.1` 只有源码包，若构建环境受限，可先在本机构建 wheel
> 再安装；Linux/macOS 直接安装即可。本项目的 `demo/` 记录来自上述版本。

### 4.3 安装项目依赖

```powershell
cd D:\agent\sandbox\comp\comp\minimax
uv venv .venv --python 3.12
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
```

也可以使用 `uv sync`（`pyproject.toml` 已声明 `pymysql`、`pytest`）。

## 5. 配置

### 5.1 `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

至少填写：

```dotenv
MINIMAX_API_KEY=<你的 MiniMax key>
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M3.1-Flash
MINIMAX_EMBEDDING_MODEL=embo-01

SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_USER=root
SEEKDB_PASSWORD=
SEEKDB_DATABASE=sdd_context

POWERCONTEXT_URL=http://127.0.0.1:8765
```

`.env` 已被 `.gitignore` 排除，不要提交真实 key。没有 key 时，资料入库会退回
确定性哈希向量，但 `run_demo.py` 的 MiniMax 代码生成会失败。

### 5.2 `.env.powercontext`

复制 `.env.powercontext.example` 为 `.env.powercontext`，把两处绝对路径改成
本机路径。SQLite URL 必须是绝对路径，例如：

```dotenv
POWERCONTEXT_HOME=D:/agent/sandbox/.powercontext
POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
POWERCONTEXT_SERVER_HTTP_PORT=8765
POWERCONTEXT_SERVER_DATABASE_KIND=sqlite
POWERCONTEXT_SERVER_DATABASE_URL=sqlite+aiosqlite:///D:/agent/sandbox/.powercontext/powercontext.db
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
```

> 在本机沙箱中，PowerContext 首次启动会写临时迁移脚本；如果临时目录被限制，
> 将 `TMP`/`TEMP` 指向工作区目录（`scripts/powercontext_service.py` 已处理）。

## 6. 启动与初始化

```powershell
# 1) seekdb 已启动
# 2) 启动 PowerContext（后台）
.\.venv\Scripts\python.exe scripts\powercontext_service.py start

# 3) 建表并导入规格/代码/测试
.\.venv\Scripts\python.exe -m sdd_context.cli init --reset

# 4) 构建一次上下文
.\.venv\Scripts\python.exe -m sdd_context.cli context `
  --task tasks/BOOK-001.md --out demo/context/manual
```

`init --reset` 会重建 `documents`、`document_versions`、`links`、`context_runs`、
`query_log`、`ingest_runs` 六张表；不会动 PowerContext 的数据库。

## 7. 调用入口与输出

### 7.1 CLI

```powershell
# 初始化/重新导入
python -m sdd_context.cli init --reset
python -m sdd_context.cli ingest

# 构建上下文（JSON + Markdown + SQL 审计）
python -m sdd_context.cli context --task tasks/BOOK-001.md --out demo/context/my-run

# 保存/读取任务状态
python -m sdd_context.cli state-save --payload examples/state-payload.json
python -m sdd_context.cli state-show --task-id BOOK-001

# 核对数据库、来源文件、PowerContext 状态
python -m sdd_context.cli verify
```

`context` 的输出（`context.json`）字段：

| 字段 | 含义 |
| --- | --- |
| `task` | 任务 ID、标题、关键词、目标符号、正文 |
| `specs[]` | 本次适用的规格/决策：`id`、`version`、`path`、`requirements`、`score`、`reasons` |
| `code[]` | 需要修改的代码：`path`、`symbol`、`kind`、`start_line`/`end_line`、`content` |
| `tests[]` | 功能与回归测试：`path`、`test_name`、`kind`（target/regression）、`spec_ids` |
| `state` | PowerContext 中的已完成、待办、验证结果及其 Artifact 引用 |
| `retrieval.queries[]` | 实际执行的 seekdb SQL、参数、行数、耗时 |
| `context_markdown` | 可直接放进模型提示词的渲染结果 |

所有来源路径在输出前都会用 `Path.exists()` 校验；不存在的来源会被丢弃并写入
`retrieval.warnings`，不会伪造引用。

### 7.2 Python API

```python
from pathlib import Path
from sdd_context.config import Settings
from sdd_context.context import build_context

settings = Settings.load()
bundle = build_context(settings, Path("tasks/BOOK-001.md"))
print([s["metadata"]["id"] for s in bundle["specs"]])
print(bundle["state"]["completed"])
```

## 8. 验证样例怎么跑

完整步骤、预期结果和重置方法见 [`docs/validation-sample.md`](docs/validation-sample.md)。
最短路径：

```powershell
# 修改前：11 failed, 9 passed（在临时目录复现，不动当前代码）
.\.venv\Scripts\python.exe scripts\reproduce_before.py

# 修改后：20 passed
.\.venv\Scripts\python.exe -m pytest -q

# 从零重跑整条链路（会重建 seekdb 表、清空本次 demo 记录、重启 PowerContext）
.\.venv\Scripts\python.exe -m scripts.run_demo
```

`run_demo.py` 依次完成：导入 v1 → 构建上下文 → 跑修改前测试 → 写 checkpoint 1
→ 重新构建带状态的上下文 → 调 MiniMax → 应用补丁 → 跑修改后测试 → 写
checkpoint 2 → 规格升 v2 并重新导入 → 写 checkpoint 3 → 重启 PowerContext →
新进程读回状态 → 生成 `demo/summary.json`。

## 9. 提交证据索引

| 文件 | 内容 |
| --- | --- |
| `artifacts/before/` | 修改前 `service.py`、`api.py`、规格 v1 快照 |
| `artifacts/after/` | 修改后 `service.py`、`api.py`、规格 v2 快照 |
| `artifacts/changes.diff` | 代码统一 diff |
| `artifacts/spec-changes.diff` | 规格 v1→v2 diff |
| `artifacts/test_logs/01_tests_before.log` | 修改前命令、退出码、代码版本、11 failed/9 passed |
| `artifacts/test_logs/02_tests_after.log` | 修改后命令、退出码、代码版本、20 passed |
| `demo/01_context_before.json/.md` | 修改前上下文（规格 v1） |
| `demo/02_context_before_with_state.json` | 带 checkpoint 1 的上下文，MiniMax 实际输入 |
| `demo/03_minimax_attempts.json` | 每次 MiniMax 调用的 response id、token、时延、应用结果 |
| `demo/minimax_records/call-01-request.json` | 发送给 MiniMax 的完整消息 |
| `demo/minimax_records/call-01-response.json` | MiniMax 原始响应与 usage |
| `demo/04_context_after_spec_update.json/.md` | 规格 v2 重新导入后的上下文 |
| `demo/05_spec_update_evidence.json` | v1/v2 版本、需求项、历史状态 |
| `demo/07_state_after_restart.json` | 重启后新进程读到的 seq=3 状态 |
| `demo/powercontext_records.jsonl` | PowerContext 每次写入/读取的路径、状态码、scope |
| `demo/context/*/queries.json` | 上下文实际执行的 seekdb SQL |

## 10. 三项技术怎么参与

- **MiniMax**：`MiniMax-M3.1-Flash` 通过 OpenAI 兼容的
  `/chat/completions` 接收“任务 + 规格 + 代码 + 测试 + 失败输出”，返回完整
  `booknest/service.py` 与 `booknest/api.py`；`sdd_context/minimax_client.py`
  校验路径、禁止改测试/规格、应用后跑测试。`embo-01` 同时用于 seekdb 的
  1536 维向量。
- **seekdb**：保存 `documents`、`document_versions`、`links`、`context_runs`、
  `query_log`；检索 SQL 同时使用 `cosine_distance(VECTOR)`、`MATCH ... AGAINST`
  （ngram2 全文）和 `links` 图扩展。每次上下文返回 6 条 SQL 审计。
- **PowerContext**：用 `POST /v1/scopes` 建 Scope，`POST /v1/memory/remember`
  写 `sdd_task_state` 检查点，`POST /v1/memory/entries/list` 读回，
  `POST /v1/sources/content` 保存测试日志证据。重启 Server 后，CLI 新进程仍能
  读到 checkpoint 3。

## 11. 已知限制

1. `demo/` 中的 response id、scope id、时间戳是本次运行的真实值；重新运行会
   产生新值，不能要求模型生成完全相同的补丁。
2. PowerContext 使用 SQLite 后端，只适合单机演示；没有启用鉴权、Dashboard
   多用户或远程访问。
3. MiniMax key 只放在本地 `.env`，仓库内没有真实凭据；测评环境若没有 key，
   可复现上下文、数据库、状态与测试，但不能复现新的模型调用。
4. 重新导入会为全部资料重新计算 embedding（v2 导入约 7.8k tokens），没有做
   增量 embedding；这是已知成本优化点。
5. 样例只覆盖一个局部任务；模块的解析器面向 Markdown frontmatter、Python
   `ast` 和 pytest 测试，不是通用多语言索引器。
6. Windows 上的绝对路径会出现在证据日志里；换机器时按第 3、5 节改路径即可。

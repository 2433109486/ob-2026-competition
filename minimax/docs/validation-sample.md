# 验证样例：BOOK-001 商品价格区间筛选

本文件说明“要改什么”“哪些原有行为必须保持”“上下文中必须出现哪些真实来源”，
以及从初始数据到修改后验证的完整操作步骤。

## 1. 任务描述

在 `booknest` 样例中，为商品搜索增加价格区间筛选：

- `search_products` 接受可选 `min_price` / `max_price`，按**闭区间**过滤；
- `GET /api/products` 暴露同名查询参数；
- 非数字、负数、倒置区间返回 HTTP 400；
- 空结果返回空列表/HTTP 200，不回退到未过滤结果；
- 不传价格参数时，分类、关键词、排序、`limit`、`/health` 行为保持不变。

任务文件：[`tasks/BOOK-001.md`](../tasks/BOOK-001.md)。

## 2. 上下文中必须包含的来源

### 2.1 规格/决策（4 条）

| ID | 版本 | 文件 | 与任务的关系 |
| --- | --- | --- | --- |
| `BOOK-SPEC-001` | v2（修改前为 v1） | `specs/BOOK-SPEC-001-price-filter.md` | 新增闭区间筛选、校验、边界、过滤顺序 |
| `BOOK-SPEC-002` | v1 | `specs/BOOK-SPEC-002-search-compatibility.md` | 分类/关键词/排序/limit 的回归约束 |
| `BOOK-SPEC-003` | v1 | `specs/BOOK-SPEC-003-api-contract.md` | HTTP 参数、400、200、健康检查 |
| `BOOK-DEC-001` | v1 | `specs/BOOK-DEC-001-price-boundaries.md` | 闭区间、零价、空结果决策 |

必须出现的关键需求项：

- `BOOK-SPEC-001/REQ-001`：`min_price <= price <= max_price`；
- `BOOK-SPEC-001/REQ-003`：负数/倒置区间抛 `ValueError`，信息含 `min_price`；
- `BOOK-SPEC-001/REQ-004`：等边界、空结果、`0` 是合法边界；
- `BOOK-SPEC-001/REQ-005`（仅 v2）：先过滤、再排序、最后 `limit`；
- `BOOK-SPEC-002/REQ-001..004`：既有行为不变；
- `BOOK-SPEC-003/REQ-001..004`：API 参数、错误、成功响应、健康检查；
- `BOOK-DEC-001/DEC-001..003`：闭区间、零价、空结果。

### 2.2 代码来源（3 个符号）

| 文件 | 符号 | 修改后行号 | 作用 |
| --- | --- | --- | --- |
| `booknest/service.py` | `booknest.service.search_products` | 13–80 | 服务层过滤与校验 |
| `booknest/api.py` | `booknest.api.ProductRequestHandler` | 20–71 | HTTP 参数解析与 400 |
| `booknest/api.py` | `booknest.api.create_server` | 103–115 | 测试用服务器构造 |

### 2.3 测试来源（20 个）

目标功能测试（11 个，修改前必须失败）：

| 文件 | 测试 | 断言要点 |
| --- | --- | --- |
| `tests/test_price_filter.py` | `test_price_range_is_inclusive` | 58–99 闭区间返回 4 个商品 |
| `tests/test_price_filter.py` | `test_max_price_zero_selects_free_item` | `max_price=0` 只返回零价商品 |
| `tests/test_price_filter.py` | `test_min_price_only_filters_lower_bound` | 只给下界 |
| `tests/test_price_filter.py` | `test_equal_min_and_max_selects_exact_boundary` | 等边界 |
| `tests/test_price_filter.py` | `test_empty_range_returns_empty_list` | 空结果 |
| `tests/test_price_filter.py` | `test_negative_price_is_rejected` | 负数 `ValueError` |
| `tests/test_price_filter.py` | `test_inverted_range_is_rejected` | 倒置 `ValueError` |
| `tests/test_api_price_filter.py` | `test_api_filters_by_price_range` | API 200 + 4 条 |
| `tests/test_api_price_filter.py` | `test_api_rejects_non_numeric_price` | API 400 |
| `tests/test_api_price_filter.py` | `test_api_rejects_inverted_range` | API 400 |
| `tests/test_api_price_filter.py` | `test_api_accepts_zero_upper_bound` | `max_price=0` 200 + 1 条 |

回归测试（9 个，修改前后都必须通过）：

`tests/test_search_existing.py` 中的
`test_category_filter_is_case_insensitive`、
`test_keyword_matches_title_and_tags`、
`test_price_desc_sort_is_unchanged`、
`test_default_search_returns_all_seed_rows`、
`test_no_price_parameters_keeps_previous_result`、
`test_limit_is_validated`、
`test_unknown_category_returns_empty`、
`test_api_health`、
`test_api_keeps_existing_query_contract`。

## 3. 初始数据与基线行为

`booknest/seed/products.json` 有 10 条商品，关键边界：

| ID | 标题 | 分类 | 价格 | 用途 |
| --- | --- | --- | --- | --- |
| `BK-1005` | Atomic Habits | Lifestyle | 58.0 | 区间下界 |
| `BK-1001` | Deep Work | Business | 68.0 | 区间内 |
| `BK-1006` | The Lean Startup | Business | 88.0 | 区间内 |
| `BK-1003` | The Pragmatic Programmer | Technology | 99.0 | 区间上界 |
| `BK-1007` | Free Culture | Culture | 0.0 | 零价边界 |
| `BK-1004` | Designing Data-Intensive Applications | Technology | 168.0 | 区间外 |

基线快照在 `baseline/` 与 `artifacts/before/`：

- `service.search_products` 接受 `min_price`/`max_price`，但一旦传入就抛
  `NotImplementedError`；
- `api` 解析分类/关键词/排序/limit，但忽略价格参数，因此带价格参数会返回
  未过滤的 200。

## 4. 从零执行

### 4.1 准备

```powershell
cd D:\agent\sandbox\comp\comp\minimax
Copy-Item .env.example .env
# 编辑 .env：填 MINIMAX_API_KEY 等
Copy-Item .env.powercontext.example .env.powercontext
# 编辑 .env.powercontext：两处绝对路径改成自己的
uv venv .venv --python 3.12
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
```

### 4.2 启动 seekdb 与 PowerContext

```powershell
# 终端 A：seekdb 1.4.0.0
cd D:\agent\sandbox\seekdb14\seekdb-data
& 'D:\agent\sandbox\seekdb14\seekdb-1.4.0\seekdb.exe' `
  '--base-dir=D:/agent/sandbox/seekdb14/seekdb-data' '--port=2881' --nodaemon

# 终端 B：项目根目录
cd D:\agent\sandbox\comp\comp\minimax
.\.venv\Scripts\python.exe scripts\powercontext_service.py start
```

### 4.3 导入 v1 资料并构建上下文

```powershell
.\.venv\Scripts\python.exe -m sdd_context.cli init --reset
.\.venv\Scripts\python.exe -m sdd_context.cli context `
  --task tasks/BOOK-001.md --out demo/context/manual
```

预期 `context.json`：

- `specs` 含 `BOOK-SPEC-001`（version 1）、`BOOK-SPEC-002`、`BOOK-SPEC-003`、
  `BOOK-DEC-001`；
- `code` 含 `booknest.service.search_products`、`booknest.api.ProductRequestHandler`、
  `booknest.api.create_server`；
- `tests` 含 11 个 target + 9 个 regression；
- `state.status = "empty"`（还没有 checkpoint）；
- `retrieval.queries` 至少 5 条 SQL。

### 4.4 修改前测试

```powershell
.\.venv\Scripts\python.exe scripts\reproduce_before.py
```

预期输出：`exit_code: 1`、`summary: "11 failed, 9 passed"`，日志
`artifacts/test_logs/00_before_repro.log`。这是功能未实现导致的失败，不是依赖
缺失或服务启动失败。

### 4.5 完整链路

```powershell
.\.venv\Scripts\python.exe -m scripts.run_demo
```

该命令会：

1. 重置代码/规格到 v1，重建 seekdb 表；
2. 用新 Scope 启动空状态；
3. 构建上下文、跑修改前测试、写 checkpoint 1；
4. 把带状态的上下文交给 MiniMax，应用补丁，跑修改后测试；
5. 写 checkpoint 2，生成 before/after/diff；
6. 规格升 v2、重新导入、确认 `REQ-005` 出现且 v1 变为 `superseded`；
7. 写 checkpoint 3，重启 PowerContext，用新进程读回 seq=3；
8. 写 `demo/summary.json`。

### 4.6 修改后测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

预期：`20 passed`。同一组 20 个测试，未改断言。

### 4.7 状态复用验证

```powershell
.\.venv\Scripts\python.exe -m sdd_context.cli state-show --task-id BOOK-001
```

预期：`status: "loaded"`、`seq: 3`、`completed` 含 5 项、`verifications` 含
修改前失败与修改后通过两条记录。证据文件
`demo/07_state_after_restart.json`。

## 5. 预期结果与实际结果

| 检查 | 预期 | 实际（本次提交） |
| --- | --- | --- |
| 修改前目标测试 | 11 failed | `11 failed, 9 passed`，exit 1 |
| 修改前回归测试 | 9 passed | 同左 |
| 修改后全部测试 | 20 passed | `20 passed`，exit 0 |
| 上下文规格 | 4 条，001 为 v1 | 4 条，001 v1 |
| 规格更新后 | 001 为 v2，含 `REQ-005` | v2，`REQ-001..005`，v1 `superseded` |
| 代码来源 | 3 个符号真实存在 | 3 个，全部 `exists: true` |
| 测试来源 | 20 个真实存在 | 20 个，全部 `exists: true` |
| 状态复用 | 重启后 seq=3 | `loaded`，seq=3 |
| seekdb 查询 | 每次上下文有 SQL 审计 | 6 条/次 |

## 6. 重置方法

### 只重置代码与规格到修改前

```powershell
Copy-Item baseline\booknest\service.py booknest\service.py -Force
Copy-Item baseline\booknest\api.py booknest\api.py -Force
Copy-Item baseline\specs\BOOK-SPEC-001-price-filter.md specs\BOOK-SPEC-001-price-filter.md -Force
```

### 重置 seekdb 资料

```powershell
.\.venv\Scripts\python.exe -m sdd_context.cli init --reset
```

### 重置 PowerContext 任务状态

方式一（推荐，保留数据库）：

```powershell
Remove-Item demo\runtime\powercontext_scope.txt -Force
$env:POWERCONTEXT_SCOPE_KEY = "booknest-sdd-$(Get-Date -Format yyyyMMddHHmmss)"
```

之后运行的进程会用新 key 建立新 Scope；旧 Scope 不会被读取。

方式二（彻底清空）：停止 PowerContext，删除 `.env.powercontext` 中
`POWERCONTEXT_HOME` 指向的 `powercontext.db`，再启动。

### 恢复修改后状态

```powershell
Copy-Item artifacts\after\booknest\service.py booknest\service.py -Force
Copy-Item artifacts\after\booknest\api.py booknest\api.py -Force
Copy-Item artifacts\after\specs\BOOK-SPEC-001-price-filter.md specs\BOOK-SPEC-001-price-filter.md -Force
.\.venv\Scripts\python.exe -m sdd_context.cli init
```

## 7. 证据对照

| 结论 | 文件 |
| --- | --- |
| 修改前失败 | `artifacts/test_logs/01_tests_before.log`、`00_before_repro.log` |
| 修改后通过 | `artifacts/test_logs/02_tests_after.log` |
| 代码差异 | `artifacts/changes.diff` |
| 规格差异 | `artifacts/spec-changes.diff` |
| 规格更新生效 | `demo/04_context_after_spec_update.json`、`demo/05_spec_update_evidence.json` |
| 状态复用 | `demo/07_state_after_restart.json`、`demo/powercontext_records.jsonl` |
| 数据库参与 | `demo/context/*/queries.json`、`demo/08_verify.txt` |
| MiniMax 参与 | `demo/minimax_records/call-01-request.json`、`call-01-response.json`、`demo/03_minimax_attempts.json` |

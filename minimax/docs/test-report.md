# 测试报告

## 1. 环境

| 项 | 值 |
| --- | --- |
| 日期 | 2026-10-29（UTC+8） |
| Python | 3.12.13（项目 `.venv`） |
| pytest | 8.x |
| 业务样例 | `booknest`（纯标准库） |
| 测试文件 | `tests/test_price_filter.py`、`tests/test_api_price_filter.py`、`tests/test_search_existing.py` |
| 测试总数 | 20（11 目标 + 9 回归） |

## 2. 修改前

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

代码版本（`service.py` + `api.py` 聚合 SHA-256）：

```text
sha256:ac5d907f8ff183cfae5309110d23763eacca464da973cbe944ba2c544b9f0327
```

结果：

```text
11 failed, 9 passed in 3.18s
exit code: 1
```

失败原因（功能未实现，不是环境错误）：

- 7 个服务层目标测试触发 `NotImplementedError: price-range filtering is not implemented yet`；
- 4 个 API 目标测试拿到未过滤的 200 响应，断言数量/状态失败；
- 9 个既有回归测试全部通过，说明应用能启动、依赖完整、测试框架正常。

日志：`artifacts/test_logs/01_tests_before.log`（含命令、cwd、退出码、代码版本）。

无副作用复现：

```powershell
.\.venv\Scripts\python.exe scripts\reproduce_before.py
# -> {"exit_code": 1, "summary": "11 failed, 9 passed in 3.18s"}
```

日志：`artifacts/test_logs/00_before_repro.log`。

## 3. 修改后

命令与测试文件完全相同：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

代码版本：

```text
sha256:0397caf0486d84e2905142f54fce78f6ceee30ac2fa2ffc4968a74ad6734d351
```

结果：

```text
20 passed in 3.13s
exit code: 0
```

日志：`artifacts/test_logs/02_tests_after.log`。

## 4. 分类结果

| 类别 | 文件 | 数量 | 修改前 | 修改后 |
| --- | --- | --- | --- | --- |
| 目标：服务层价格筛选 | `tests/test_price_filter.py` | 7 | 7 failed | 7 passed |
| 目标：API 价格筛选 | `tests/test_api_price_filter.py` | 4 | 4 failed | 4 passed |
| 回归：既有搜索/接口 | `tests/test_search_existing.py` | 9 | 9 passed | 9 passed |
| 合计 | 3 个文件 | 20 | 11 failed / 9 passed | 20 passed |

## 5. 断言与测试集一致性

- 修改前后使用同一组 20 个测试函数、同一组断言和同一份 `products.json`；
- 没有删除测试、没有 `skip`/`xfail`、没有修改预期值；
- 修改前失败是目标行为缺失（`NotImplementedError` 或未过滤结果），不是缺少
  依赖、导入错误、端口占用等环境错误；
- 修改后 9 个回归测试仍全部通过，说明分类、关键词、排序、limit、`/health`
  没有被破坏。

## 6. 其他验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| seekdb 资料数 | 31 条 active | `demo/08_verify.txt` |
| seekdb 图链接 | 78 条 | `demo/08_verify.txt` |
| 规格 001 版本 | v2 active，v1 superseded | `demo/05_spec_update_evidence.json` |
| 上下文来源真实存在 | 4 规格 + 3 代码 + 20 测试全部 `exists: true` | `demo/summary.json` |
| 状态重启复用 | `loaded`，seq=3 | `demo/07_state_after_restart.json` |
| MiniMax 调用 | response `073239b65f...`，一次通过 | `demo/minimax_records/calls.jsonl` |

## 7. 一键复核

```powershell
.\.venv\Scripts\python.exe scripts\verify_acceptance.py
```

该脚本检查证据文件、before/after 日志、seekdb 文档数/查询数、规格 v2、
PowerContext seq=3，并重新跑一次当前 `pytest`。

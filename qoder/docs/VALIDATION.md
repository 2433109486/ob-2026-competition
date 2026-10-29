# 验证样例与复现记录

本页是可直接照着执行的验收样例。所有结果来自 2026-10-29 的本机运行，
证据文件在 [`docs/evidence/`](evidence/)，截图在 [`docs/screenshots/`](screenshots/)。

## 0. 初始状态

| 项 | 值 |
| --- | --- |
| 资料 | 10 份（9 篇论文 + 1 份内置组会笔记） |
| 证据片段 | 34 个，带章节/页码 |
| 精读笔记 | 5 条 |
| 研究画像 | 林然 / 教育技术学 / 文献综述 |
| 关注主题 | 生成式AI、编程教育、初学者、学习迁移、实证研究 |
| 研究问题 | 生成式 AI 编程助手如何影响初学者的编程学习与迁移？ |
| seekdb | `yanmai` 库，`papers` / `chunks` / `notes` / `search_log` / `activity` |
| PowerContext | Scope `研脉 · 研究上下文`，已有画像、4 条阅读进度、1 条综述决策 |

初始化命令：

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py --reset
```

## 样例 A：混合检索与 SQL 轨迹

### 输入

在「证据检索」输入：

```text
AI 编程助手对初学者学习迁移的影响
```

不勾选任何筛选（`全部状态`、年份不限、论文与笔记）。

### 操作步骤

1. 打开 <http://127.0.0.1:7860/#/search>。
2. 输入上面的问题，回车或点「检索」。
3. 等待结果列表出现。
4. 点右侧「查看 SQL 轨迹」。
5. 点第 2 条结果「AI 代码生成器如何支持编程入门学习者」→「证据片段」。

### 预期结果

- 返回 **8 篇**结果（limit 默认 12，资料库共 10 篇；实际以当前库为准，应 ≥ 6）。
- 第一页包含以下论文（顺序可能因资料增删而变化）：
  - `组会纪要：AI 编程助手研究设计讨论`（2026，内置笔记）
  - `AI 代码生成器如何支持编程入门学习者`（CHI 2023）
  - `没有护栏的生成式 AI 可能损害学习：高中数学证据`（PNAS 2025）
  - `AI 对开发者生产力的影响：来自 GitHub Copilot 的证据`（2023）
- 每条结果展示：
  - 融合分（0–100）；
  - 命中理由：`语义相似度`、`全文相关度`、`记忆主题命中`；
  - 原文片段（带 `<mark>` 高亮）与章节/页码。
- 右侧「本次记忆上下文」显示：
  - 画像：`教育技术学 · 文献综述；当前关注 生成式AI、编程教育、初学者`
  - 标签：生成式AI、编程教育、初学者、学习迁移、实证研究
  - 正在精读：`机器人已至：计算教育中的生成式 AI 变革`
- SQL 轨迹弹窗显示至少 2 条 SQL：
  1. `cosine_distance(c.embedding, ...)` + `ORDER BY vector_distance ASC LIMIT 60`；
  2. `MATCH(c.search_text) AGAINST(...)` + `ORDER BY text_score DESC LIMIT 30`。
- 实际候选数示例：向量 34 个片段，全文 30 个片段，融合 34 个片段，耗时约 170–240 ms。

### seekdb 实际发挥作用的记录

`docs/evidence/search_trace.json` 保存了完整响应，其中：

```json
{
  "counts": {
    "vector_candidates": 34,
    "text_candidates": 30,
    "fused_chunks": 34,
    "papers": 10
  },
  "trace": [
    {"label": "seekdb 向量召回（cosine_distance + HNSW）", "...": "..."},
    {"label": "seekdb 全文召回（ngram2 MATCH AGAINST）", "...": "..."}
  ]
}
```

可自行核对：

```sql
SELECT COUNT(*) FROM yanmai.papers;   -- 10
SELECT COUNT(*) FROM yanmai.chunks;   -- 34
SELECT chunk_id, section, page FROM yanmai.chunks LIMIT 5;
```

## 样例 B：研究记忆被保存并复用

### B1. 改阅读状态

1. 在资料库打开 `非英语母语者学习编程：障碍、愿望与设计机会`。
2. 点状态「精读中」。
3. 在「综述字段」保存任意一个字段（可保持原文不变）。
4. 回到「研究记忆」。

### 预期

- 页面提示「已标记为精读中，进度写入研究记忆」。
- PowerContext 时间线新增一条 `reading_progress`，包含 `paper_id=guo2018`、`status=reading`、
  `takeaway`、`saved_at`、`artifact_id`、`revision=1`。
- 刷新页面后，今日页「继续阅读」可能切换到这篇（取决于最新阅读顺序）。
- 下一次检索时，`guo2018` 因状态加权获得更高的排序解释「正在精读，优先呈现」。

### B2. 写一条研究判断

在「研究记忆 → 写一条研究判断」输入：

```text
主终点坚持用延迟迁移，不用课堂练习成绩替代。
```

提交。

### 预期

- 返回 `saved: true` 与 `artifact_id`。
- 时间线出现 `research_note`。
- 在「召回一条记忆」输入 `学习迁移`，应召回画像/阅读进度/研究判断中的相关条目。
- 调用记录追加到 `runtime/powercontext_calls.jsonl`（提交版另存于
  `docs/evidence/powercontext_calls.jsonl`）。

### 证据

```text
docs/evidence/powercontext_entries.json   # Scope 内 Atomic Memory 列表
docs/evidence/powercontext_calls.jsonl    # 每次 HTTP 调用：path/status/kind/scope
```

## 样例 C：综述矩阵与引用草稿

### 输入

在「综述矩阵」中选择这 4 篇：

- `kazemitabaar2023`（CHI 2023）
- `bastani2025`（PNAS 2025）
- `prather2023`（ITiCSE-WGR 2023）
- `denny2024`（CACM 2024）

问题：

```text
生成式 AI 编程助手如何影响初学者的编程学习与迁移？
```

### 操作

点「生成 / 更新矩阵」。

### 预期

- 矩阵：4 行 × 6 列（研究问题、研究设计、样本/情境、主要发现、局限、可复用点）。
- 覆盖率：100%（这 4 篇的字段都已填写）。
- 顶部统计：`2 篇含实证/调查数据`（Prather 工作组报告与 Denny 观点文章不计为原始实证）。
- 草稿包含 5 节：问题、研究怎么做、发现与分歧、局限与空白、对当前研究的启示。
- 草稿带 `[1]–[4]` 引用编号，文末 4 条参考文献，含 DOI。
- 点「导出 Markdown」下载 `yanmai-review-draft.md`；内容与页面一致。
- 综述选择写入 PowerContext 的 `review_board`，刷新页面后 4 篇仍处于选中状态。

### 实际结果

`docs/evidence/acceptance.json`：

```json
{
  "matrix": {"rows": 4, "columns": 6, "coverage": 100, "citations": 4, "memory_saved": true},
  "status": "pass"
}
```

## 自动验收结果

`scripts/acceptance.py` 在 2026-10-29 的实际输出：

```text
[OK] seekdb 可连接: 5.7.25-OceanBase seekdb-v1.4.0.0
[OK] PowerContext 可连接: http://127.0.0.1:8765
[OK] 资料库已初始化: 10 篇
[OK] 研究记忆可用: 6 条
[OK] 研究画像已读取: 3 周内完成「生成式 AI 辅助编程学习」开题综述
[OK] 混合检索返回结果: 8 篇 / 236 ms
[OK] 执行向量与全文两条 SQL: [...]
[OK] seekdb 向量召回: 34 个片段
[OK] seekdb 全文召回: 30 个片段
[OK] 记忆参与本次检索排序: [...]
[OK] 可打开原文证据片段: 组会纪要... / 3 段
[OK] 综述矩阵包含 4 篇文献: ...
[OK] 矩阵包含 6 个维度: [...]
[OK] 结构化字段覆盖度: 100%
[OK] 草稿带 4 条引用: Kazemitabaar, ...
[OK] 综述决策写入 PowerContext: art_...
[OK] 研究判断写入 PowerContext: art_...
[OK] 记忆时间线包含综述决策: [...]
[OK] 记忆时间线包含研究判断: 8 条
[OK] PowerContext 可召回刚写入的记忆: research_note
[OK] 保留 PowerContext 调用证据: 38 条
PASS: 21 checks
```

> 重新运行会产生新的 `artifact_id`、时间戳与耗时，数量可能因新增验收记忆而变化；
> 断言检查的是“功能成立”，不是固定 UUID。

## 浏览器验收

`scripts/e2e_ui.py` 实际覆盖：

- 搜索「怎么避免学生直接抄答案」，第一条是 `没有护栏的生成式 AI 可能损害学习`；
- 打开精读抽屉 → 证据片段 ≥ 2；
- 生成矩阵（4 行、7 个表头含文献列）并下载 Markdown；
- 研究记忆召回、画像弹窗打开/关闭；
- 资料库多选与选择条清空；
- 浏览器 console 无错误。

## 重置与再次验证

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py --reset
.\.venv\Scripts\python.exe scripts\reset_demo_scope.py
.\.venv\Scripts\python.exe scripts\acceptance.py
```

`init_db.py --reset` 只重建 **yanmai** 数据库；`reset_demo_scope.py` 新建一个干净的
PowerContext Scope 并写入演示画像/阅读进度/综述选择，不会删除旧 Scope。

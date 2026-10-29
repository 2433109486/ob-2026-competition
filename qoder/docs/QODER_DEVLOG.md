# Qoder 开发记录（重放与证据清单）

> **证据状态说明（提交前请读）**
>
> 本文件是项目的开发过程记录与 Qoder 重放脚本。仓库里的代码、测试和截图已经完成；
> **Qoder CN 已实际完成一次 BibTeX 功能开发（12 passed / 23 checks），但对话截图仍需从
> 当前 Qoder 会话中保存到 `docs/qoder-evidence/`，Qoder UID 也需填写。**
> 请按 [`QODER_HANDOFF.md`](QODER_HANDOFF.md) 在 Qoder 中导入本目录，依次发送下面的任务，
> 把每一步的对话与运行结果截图保存到 `docs/qoder-evidence/`，再把本页的“证据”列替换为实际截图链接。
> 不要把本页当作已经完成的 Qoder 使用证明；赛题要求的是可核对的真实记录。

- Qoder 账号 UID：`1473193271554286`（Qoder CN 个人信息页的阿里云账号 ID；如客户端显示不同 UID，以客户端为准）
- 项目目录：`qoder/`
- 分支/基线：`2026-competition-ecosystem` 导入后的同名分支；本目录位于 `qoder/`
- 站点：`site/`（静态网站，发布后填写 URL）
- 代码仓库：`<填写公开仓库或评审可访问地址>`

## 1. 任务拆解与实现顺序

| # | 阶段 | Qoder 应完成的事 | 当前产物 | Qoder 证据位 |
| --- | --- | --- | --- | --- |
| 1 | 需求拆解 | 把“文献综述工作台”拆成资料库、混合检索、精读、矩阵、记忆五条流程 | `README.md`、`docs/ARCHITECTURE.md` | `01-requirements.png` |
| 2 | 数据层 | 建 `yanmai` 库、5 张表、VECTOR(768) + ngram2 索引、导入 10 份资料 | `app/db.py`、`seed/papers.json` | `02-seekdb-schema.png` |
| 3 | 混合检索 | 两路 SQL + 融合评分 + SQL 轨迹 | `app/retrieval.py`、`app/embeddings.py` | `03-hybrid-search.png` |
| 4 | 研究记忆 | Scope、画像、阅读进度、综述决策的写入/读回 | `app/memory.py` | `04-powercontext.png` |
| 5 | 前端 | 今日、检索、资料库、矩阵、记忆、精读抽屉 | `web/` | `05-ui.png` |
| 6 | 调试 | 修复 422、分页上限、矩阵编辑同步、移动端 | 本页第 3 节 | `06-debug.png` |
| 7 | 验收 | 23 项自动验收 + 5 条浏览器路径 | `scripts/acceptance.py`、`scripts/e2e_ui.py` | `07-acceptance.png` |
| 8 | 发布 | 用 Qoder Sites 发布 `site/`，设为公开 | `site/` | `08-sites.png` |
| 9 | Qoder 实际增量 | 新增单篇 BibTeX 导出（后端、前端、测试、验收） | `app/bibtex.py`、`app/main.py`、`web/assets/app.js` | `09-bibtex.png` |

## 2. 可直接粘贴到 Qoder 的任务

### 任务 1：需求与架构

```text
你在仓库的 qoder/ 目录工作。请先不要写代码，先输出一份实现计划。

背景：我要做一个面向研究生文献综述的工作台，名字叫「研脉 ResearchPulse」。
真实痛点：文献读了很多但写综述时找不到原句；关键词检索和语义检索各有缺口；
综述矩阵每次重做；AI 每次都重新问一遍研究方向。

约束：
- 必须实际使用 seekdb（向量 + 全文 + 结构化过滤）和 PowerContext（研究画像/阅读进度/综述决策）。
- 本地可运行，不依赖外部 LLM Key。
- 前端要中文、精致、可演示，不能是脚手架默认样式。
- 先只做 10 份演示资料，保证评审 10 分钟内能跑通。

请输出：页面/接口清单、seekdb 表结构、PowerContext 记忆类型、验收样例、风险。
保存为 docs/PLAN.md。
```

### 任务 2：seekdb schema 与种子数据

```text
按 docs/PLAN.md 实现 app/db.py：
- 创建 yanmai 数据库；
- papers / chunks / notes / search_log / activity / app_meta；
- chunks.embedding VECTOR(768)，cosine + HNSW + vsag；
- chunks.search_text 使用 ngram2 全文索引；
- 支持 reset 与幂等 seed；
- 从 seed/papers.json 导入 10 份资料和 34 个片段，中文不乱码。

验收：
1) python scripts/init_db.py --reset 输出 papers=10, chunks=34；
2) SHOW CREATE TABLE chunks 能看到 VECTOR INDEX 和 FULLTEXT；
3) 重复执行不会重复插入。
```

### 任务 3：混合检索

```text
实现 app/retrieval.py：
1) 768 维离线特征哈希向量（中文 uni/bi/trigram + 英文词，带符号、L2 归一化），不要依赖外部 API；
2) 向量召回 Top-60：cosine_distance(embedding, query)；
3) 全文召回 Top-30：MATCH(search_text) AGAINST(query)，ngram2；
4) 合并去重，按论文聚合，最多返回 2 个证据片段；
5) 融合分 = 0.44 语义 + 0.31 全文 + 0.15 主题重合 + 0.10 阅读状态；
6) 返回 trace（SQL、参数摘要、行数、耗时）和 reasons；
7) 写 search_log 与 activity。

验收：
- 查询「AI 编程助手对初学者学习迁移的影响」返回 ≥6 篇；
- trace 至少两条 SQL，候选数 >0；
- 结果片段必须来自 chunks 原文，不能拼接假句子。
```

### 任务 4：PowerContext 记忆

```text
实现 app/memory.py，接入本地 PowerContext 1.4.1：
- POST /v1/scopes 创建 Scope，idempotency_key 固定，scope_id 写 runtime/powercontext_scope.txt；
- POST /v1/memory/remember 写 research_profile / reading_progress / review_board / research_note；
- POST /v1/memory/entries/list 读回，按 saved_at 取最新；
- POST /v1/memory/search 使用 mode=fts（不要用 text，1.4.1 不接受）；
- 每次调用写入 runtime/powercontext_calls.jsonl（不记录正文/密钥）；
- 服务不可用时降级，不阻塞检索。

验收：
1) 保存画像后 entries/list 能看到 research_profile；
2) 改阅读状态后 timeline 新增 reading_progress；
3) 生成矩阵后 review_board 可恢复 paper_ids；
4) 召回「学习迁移」能命中刚写的判断。
```

### 任务 5：前端

```text
实现 web/ 下的中文 SPA（原生 HTML/CSS/ES Module，无构建步骤）：
- 左侧栏：今日 / 证据检索 / 资料库 / 综述矩阵 / 研究记忆；
- 今日：问候、今日聚焦、继续阅读、记忆卡片、四个统计、推荐、活动、主题分布；
- 检索：大搜索框、筛选、结果卡（分数环、命中理由、原文片段、加入综述）；
- 资料库：状态筛选、标签、多选、综述字段覆盖度；
- 矩阵：4×6 表、覆盖率、缺口、单元格编辑、草稿、导出 Markdown；
- 记忆：画像、时间线、召回测试、写判断、Scope/Revision；
- 精读抽屉：导读/证据/笔记/综述字段四个 tab。

视觉：暖纸色底、深绿 + 珊瑚色、中文衬线标题、细边框、克制阴影；
不要紫色渐变、不要默认卡片堆叠。桌面 1440、移动 390 都要可用。
```

### 任务 6：调试与验收

```text
请按 docs/VALIDATION.md 跑完整验收，并修复：
- 浏览器 console 错误；
- PowerContext 422；
- 资料库筛选影响综述备选列表；
- 矩阵编辑后本地状态不同步；
- 小屏侧栏与表格溢出。

每修一个 bug，记录：现象、定位、修复、验证命令、截图。
最后把结果写入 docs/evidence/acceptance.json 和 docs/qoder-evidence/06-debug.png。
```

### 任务 7：Qoder Sites

```text
把 site/ 目录发布为 Qoder Site：
- 站点名称：研脉 ResearchPulse；
- 可见范围：任何人都可访问（个人账号，不是企业版）；
- 首页要包含项目简介、痛点、核心功能、演示视频/截图、技术架构、代码仓库链接、运行说明入口；
- 发布后用无痕窗口打开验证，不需要登录；
- 把 URL、访问统计截图保存到 docs/qoder-evidence/08-sites.png。
```

## 2.1 Qoder CN 实际执行结果（2026-10-29）

实际使用 **Qoder CN CLI 1.1.80**，账号 `nick2670519458`（Pro Trial），工作目录
`D:\agent\sandbox\submission-wt`。Qoder 在现有项目上完成了单篇文献 BibTeX 导出：

| 文件 | Qoder 的改动 |
| --- | --- |
| `app/bibtex.py` | 新增 BibTeX 生成模块：cite key、LaTeX 转义、entry type、字段拼接 |
| `app/main.py` | 新增 `GET /api/papers/{paper_id}/bibtex`，返回 `application/x-bibtex` 下载 |
| `web/assets/app.js` | 精读抽屉增加「导出 BibTeX」按钮与下载函数 |
| `tests/test_units.py` | 新增 3 个单元测试 |
| `tests/test_api.py` | 新增 2 个 API 测试（200 / 404） |
| `scripts/acceptance.py` | 新增 2 项 BibTeX 验收 |
| `app/db.py` | 本地 TestClient 连接加 `ssl_disabled=True` |

实际测试结果：

```text
pytest:             12 passed
acceptance.py:      PASS 23 checks（原 21 + BibTeX 2）
```

对应截图请补：

```text
docs/qoder-evidence/09-bibtex.png
```

> 这一节证明 Qoder 不是只用来发布网站，而是实际读取了代码、实现了功能、补了测试并跑通验收。
> 仍建议补一张 Qoder 终端截图（能同时看到账号、任务和 `PASS 23 checks`）。

## 3. 实际调试记录（可作为 Qoder 对话素材）

| 现象 | 定位 | 修复 | 验证 |
| --- | --- | --- | --- |
| `/v1/memory/entries/list` 返回 422 | PowerContext 1.4.1 的 `limit` 最大 100，代码传了 200 | 改为 100 并 clamp | acceptance 通过 |
| `/v1/memory/search` 返回 422 | 1.4.1 的 `mode` 枚举是 `auto/fts/vector/hybrid`，不是 `text` | 改为 `fts` | 召回测试返回 `research_note` |
| `/v1/memory/search` 503 | 后端已改但 uvicorn 未重启 | 重启服务并复跑 | acceptance 23/23 |
| 综述矩阵右侧列被截断 | 表格 `min-width:1060px`，实际内容宽约 878px | 调整列宽/字号到 840px | 1440 截图 6 列完整 |
| 矩阵编辑后切页丢失 | 只改 DOM，没有更新 `state.review` | `focusout` 同步 row.cells | 重新生成覆盖度正确 |
| 资料库筛选后矩阵备选变少 | 复用了 `state.papers` | 新增 `state.allPapers` 供矩阵使用 | 10 篇备选始终可见 |
| 移动端内容过窄 | 桌面固定侧栏 | 760px 以下改为抽屉侧栏 | 390×844 截图通过 |
| 记忆召回显示原始 JSON | `memory.search` 直接返回 text | 解析 JSON + `_summarize_memory` | UI 显示人类可读摘要 |

## 4. 关键设计决策

1. **两路召回而非单 SQL 相加**：BM25 与 cosine 量纲不同，应用层归一化融合可解释、可调。
2. **不用 LLM 生成综述**：评审环境不一定有 Key；确定性抽取 + 引用编号更可核对。
3. **记忆只加权、不改证据**：避免“AI 用记忆编造文献”的常见问题。
4. **特征哈希向量**：离线可复现；文档明确它不是神经 embedding，生产可替换。
5. **无构建前端**：减少评审环境风险，`python -m uvicorn` 即可打开。

## 5. 提交前证据核对

- [ ] Qoder UID 已填写
- [ ] 8 个截图位都有真实截图（不是本页文字）
- [ ] Qoder Sites URL 可无痕访问
- [ ] 仓库 `qoder/` 目录代码与截图一致
- [ ] `.env`、`runtime/`、真实 Key 未提交
- [ ] `scripts/acceptance.py` 在干净环境重跑通过
- [ ] 项目网站包含代码仓库链接与运行说明入口

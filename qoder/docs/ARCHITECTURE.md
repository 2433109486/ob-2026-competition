# 技术说明

## 1. 设计原则

1. **证据先于生成**：检索片段、综述字段和引用编号都来自 seekdb 中可回查的记录；草稿只做确定性组装。
2. **记忆只影响“怎么找/怎么排”，不伪造“找到了什么”**：PowerContext 改变主题与阅读状态权重，
   但展示的片段仍然是 seekdb 原文。
3. **离线可复现**：不依赖外部 LLM/embedding API 才能跑通；评审只需 seekdb + PowerContext + Python。
4. **每一步可观察**：检索结果附 SQL、参数摘要、候选数、耗时；记忆附 Scope、Artifact ID、Revision。

## 2. 组件

```text
web/ (Vanilla ES Modules)
  ├─ 今日 / 证据检索 / 资料库 / 综述矩阵 / 研究记忆
  ├─ 精读抽屉（导读、证据、笔记、综述字段）
  └─ 画像弹窗 / SQL 轨迹弹窗
        │ fetch JSON
        ▼
app/main.py (FastAPI)
  ├─ /api/bootstrap /api/papers /api/notes
  ├─ /api/search
  ├─ /api/review/matrix /api/review/export
  ├─ /api/memory /api/memory/profile /api/memory/note /api/memory/search
  └─ /api/health /api/stats /api/activity
        │                    │
        ▼                    ▼
app/db.py              app/memory.py
seekdb (PyMySQL)       PowerContext (HTTP)
```

## 3. seekdb 数据模型

```sql
papers(
  paper_id PK, title, title_en, authors, year, venue, doi, url, abstract,
  tags, status, priority, read_minutes, source_type, cite_text,
  review_problem, review_method, review_sample, review_finding,
  review_limitation, review_reuse, added_at, updated_at, last_read_at
)

chunks(
  chunk_id PK, paper_id, section, page, content, search_text,
  embedding VECTOR(768),
  FULLTEXT INDEX ft_chunks(search_text) WITH PARSER ngram2,
  VECTOR INDEX vidx_chunks(embedding)
    WITH (DISTANCE=cosine, TYPE=hnsw, LIB=vsag)
)

notes(note_id PK, paper_id, note_type, content, created_at)
search_log(search_id PK, query, filters_json, result_count, latency_ms, mode, memory_used, created_at)
activity(activity_id PK, kind, title, detail_json, created_at)
app_meta(meta_key PK, meta_value, updated_at)
```

- 表使用 `ORGANIZATION = HEAP`，与 seekdb 1.4 的向量索引要求一致。
- `tags` 存成 `,tag1,tag2,`，便于 `LIKE '%,tag,%'` 精确匹配，避免“教育”命中“教育技术”之类的子串误判。
- 资料与片段分离：一篇论文可以有多个带章节/页码的证据片段，检索结果按论文聚合，不重复刷屏。
- `search_log` 是使用统计与调参依据；`activity` 是今日页的研究日志。

## 4. 混合检索

### 4.1 离线向量

`app/embeddings.py`：

- 中文：连续汉字串的 unigram（低权重）、bigram、trigram；
- 英文：单词；
- 每个 token 做 4 次带符号 BLAKE2b 特征哈希到 768 维，按 token 权重与词频累加，最后 L2 归一化；
- 文档向量会把标题、标签重复一次，让元数据有适度权重。

这是**确定性特征哈希向量**，不是神经 embedding。它保证：

- 无需下载模型、无需 API Key、离线可复现；
- 相同语料与查询每次得到相同向量；
- 对中文术语重合与局部语序敏感。

代价是语义泛化弱于 BGE/OpenAI embedding。生产部署可以替换 `embed_text`，只要保持 768 维；
检索 SQL、融合逻辑和 UI 不需要改动。这一点在“已知限制”中明确写出。

### 4.2 两路召回

**向量路**：

```sql
SELECT c.chunk_id, c.paper_id, c.section, c.page, c.content,
       cosine_distance(c.embedding, %s) AS vector_distance,
       MATCH(c.search_text) AGAINST(%s) AS text_score
FROM chunks c JOIN papers p ON p.paper_id = c.paper_id
WHERE <filters>
ORDER BY vector_distance ASC
LIMIT 60;
```

**全文路**：

```sql
SELECT c.chunk_id, ..., 0.0 AS vector_distance,
       MATCH(c.search_text) AGAINST(%s) AS text_score
FROM chunks c JOIN papers p ON p.paper_id = c.paper_id
WHERE MATCH(c.search_text) AGAINST(%s) AND <filters>
ORDER BY text_score DESC
LIMIT 30;
```

`MATCH` 使用 `ngram2` 解析器，适合中文短语；查询与片段都保留原始文本，不做翻译。

### 4.3 融合与排序

```text
vector_similarity = clamp(1 - cosine_distance, 0, 1)
text_similarity   = log1p(text_score) / log1p(max_text_score)
tag_overlap       = |paper.tags ∩ profile.focus_tags| / min(4, |focus_tags|)
status_boost      = reading 1.0 / read 0.55 / to_read 0.15

score = 0.44 * vector_similarity
      + 0.31 * text_similarity
      + 0.15 * tag_overlap
      + 0.10 * status_boost
```

- 融合按 `chunk_id` 去重；同一篇论文只保留最高分片段作为主证据，最多返回 2 个片段。
- 结果记录 `channels`（vector/text）、`matched_tags`、`reasons`，UI 直接展示。
- 主题重合与阅读状态来自 PowerContext 的画像/进度；没有记忆时这两项为 0，检索仍成立。

### 4.4 为什么不用“一个 SQL 同时 ORDER BY 两路”

seekdb 支持在同一条 SQL 里计算 `cosine_distance` 与 `MATCH` 分数，但把两路候选的原始分直接相加会
被不同量纲支配（cosine 距离 0–2，BM25 分数无上界）。本项目采用“两路各自召回 → 应用层归一化融合”，
并在 UI 中公开两条 SQL 和候选数。这是有意的工程选择，不是绕过数据库。

## 5. PowerContext 记忆

### 5.1 Scope

- 标题：`研脉 · 研究上下文`
- 创建：`POST /v1/scopes`，带 `idempotency_key`，返回 `scope_id`
- `scope_id` 存在 `runtime/powercontext_scope.txt`（不提交）

### 5.2 记忆类型

| kind | 何时写 | 关键字段 | 后续怎么用 |
| --- | --- | --- | --- |
| `research_profile` | 保存画像 | field/stage/goal/question/methods/preferences/focus_tags | 检索主题加权；今日页问候与推荐 |
| `reading_progress` | 改阅读状态/写 takeaway | paper_id/title/status/takeaway | 今日页“继续阅读”；检索状态加权 |
| `review_board` | 生成/保存矩阵 | paper_ids/question/note | 下次打开矩阵恢复选择 |
| `research_note` | 写研究判断/精读笔记 | text/paper_id/note_kind | 记忆时间线；召回测试 |
| `search_decision` | 主动记住一次检索 | query/insight | 研究决策记录 |

### 5.3 读写 API

```http
POST /v1/memory/remember
{
  "scope_id": "scp_...",
  "kind": "research_profile",
  "text": "{\"name\":\"林然\",...}",
  "reason": "用户更新研究画像"
}

POST /v1/memory/entries/list
{"scope_id": "scp_...", "limit": 100}

POST /v1/memory/search
{"scope_id": "scp_...", "query": "学习迁移", "mode": "fts", "limit": 6}
```

`text` 是 UTF-8 JSON，必须 ≤ 8192 字节；每次写入返回真实 `artifact_id` 与 `revision`。
应用按 `saved_at` 取每种 kind 的最新记录，避免“读回旧画像”。

> 1.4.1 的 `mode` 接受 `auto/fts/vector/hybrid`；本项目使用 `fts`，不要求额外 embedding 配置。

### 5.4 降级

PowerContext 不可用时：

- `/api/health` 返回 `powercontext.ok=false`；
- `/api/bootstrap` 使用 `seed/profile.json` 的只读默认画像；
- 检索继续，`memory.available=false`，UI 显示“记忆降级”；
- 写记忆返回 503 并显示可操作错误。

这样评审即使只启动 seekdb 也能验证检索，但完整验收需要两者都启动。

## 6. 综述矩阵与草稿

`app/review.py` 是确定性的：

1. 从 `papers.review_*` 六列读取；
2. 生成 4×6 矩阵，计算字段覆盖率与缺口；
3. 按“问题—方法—发现—分歧—局限—启示”组织段落；
4. 每篇论文分配 `[n]` 引用编号，文末按 `cite_text` 输出参考文献；
5. 把 `paper_ids/question` 写入 `review_board`。

不调用 LLM 的原因：

- 评审环境不保证有模型 Key；
- 综述草稿需要可核对，不能用流畅但无出处的句子；
- 结构化字段由研究者维护，才是最可靠的“证据压缩”。

页面上的“重新生成”只重新读取当前字段，不会擅自补写未记录的内容。

## 7. 前端

- 无构建步骤：`index.html` + `styles.css` + `app.js`（ES Module）。
- 路由：hash 路由（`#/today`、`#/search`、`#/library`、`#/review`、`#/memory`）。
- 状态：模块内 `state` 对象；`window.__yanmai` 仅用于本地验收脚本。
- 安全：所有服务端文本经 `escapeHtml`；检索 snippet 在服务端先转义再插入 `<mark>`；
  Markdown 渲染器不使用 `innerHTML` 直接注入原始 Markdown。
- 响应式：1440 桌面、1160/920 折叠、760 以下移动端侧栏抽屉；支持 `prefers-reduced-motion`。

## 8. 已知限制

1. 特征哈希向量不是神经语义模型；同义改写（如“编程新手” vs “初学者”）可能依赖全文路兜底。
2. 演示语料只有 10 份，检索指标用于功能验收，不代表领域综述的召回率。
3. PowerContext 使用 SQLite 单机后端、未启用鉴权，只适合本地演示。
4. 综述草稿是骨架，不是最终论文；引用信息需回查 DOI。
5. 使用效果目前只有开发自测（脚本、截图、调用日志），没有外部真实用户数据。

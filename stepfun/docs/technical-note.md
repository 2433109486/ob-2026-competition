# SeekBase 技术说明
### 浏览器端向量化 × seekdb 混合检索 · stepfun 赛题

**一句话**：文档解析、分块、embedding、查询编码全部在当前浏览器完成；原文、向量和元数据写入本机 seekdb，查询由 seekdb 的 `DBMS_HYBRID_SEARCH` 一次完成全文 + 向量 + RRF 融合，前端不做两路结果拼合。

```
文件/粘贴 → 分块 → Transformers.js(WebGPU FP16 / WASM INT8) → 向量
                                                        ↓
                                               seekdb-js upsert
                                                        ↓
用户查询 → 浏览器查询向量 → 一次 hybridSearch → seekdb 内 RRF → 排序结果 + 原文
```

---

## 1. 模型与量化

- **模型**：`Xenova/bge-small-zh-v1.5`（BAAI/bge-small-zh-v1.5 的 ONNX 转换），512 维，MIT 许可证，固定 revision `75c43b0…d2781`。
- **来源/哈希**：`web/models/manifest.json` 记录每个文件的 SHA-256；`npm run fetch-model -- --check` 可校验。
- **方案**：直接采用上游发布的 ONNX 产物，不改量化算法；Transformers.js 的 `dtype` 决定加载哪个文件。
  - INT8：`model_quantized.onnx`，ORT 动态量化（权重 INT8，激活动态缩放），用于 WASM。
  - FP16：`model_fp16.onnx`，权重/计算 FP16，用于 WebGPU。
  - FP32：`model.onnx`，仅作质量基线，默认不加载。

**模型体积与检索质量**（同一 48 篇 / 48 块语料、20 条查询、3 次独立建库的中位数；R@5 / nDCG@5 / MRR@10）：

| 精度 | 权重文件 | 体积 | 压缩比 | R@5 | nDCG@5 | MRR@10 |
|---|---|---:|---:|---:|---:|---:|
| FP32 基线 | `model.onnx` | 90.46 MiB | 1.00× | 0.750 | 0.866 | 0.975 |
| **INT8 + WASM** | `model_quantized.onnx` | **22.90 MiB** | **3.95×** | 0.733 | 0.861 | 0.975 |
| **FP16 + WebGPU** | `model_fp16.onnx` | **45.30 MiB** | **2.00×** | 0.750 | 0.866 | 0.975 |

INT8 的 R@5 相对下降 1.7 个百分点、nDCG 下降 0.5 个百分点，MRR 不变；FP16 与 FP32 在本评测集上指标一致。体积只统计 ONNX 权重；tokenizer/config 约 0.53 MiB，各精度共用，未计入压缩比。

---

## 2. 端侧运行与后端降级

- 运行时：`@huggingface/transformers` 3.7.5 + ONNX Runtime Web；模型由同源 `/models/` 加载，`env.allowRemoteModels=false`，推理期间无外部请求。
- 选择逻辑：`navigator.gpu` 存在且 `requestAdapter()` 返回 adapter 时，使用 `device:'webgpu'`、`dtype:'fp16'`；否则使用 `device:'wasm'`、`dtype:'q8'`。
- 如果 WebGPU 初始化抛错，`EmbeddingService.load()` 会捕获并自动重试 WASM，界面 badge 显示 `WASM · Q8`，后端卡片显示降级原因；核心导入、检索流程不受影响。
- 降级验证：用 `--disable-gpu` 启动 Edge 模拟无 adapter，`requestAdapter()` 返回 null，应用记录“navigator.gpu 存在，但没有可用的 GPU adapter”，切换 WASM Q8，查询仍返回 8 条结果。
- 查询侧使用 BGE 推荐指令前缀“为这个句子生成表示以用于检索相关文章：”；文档侧不加前缀。

---

## 3. seekdb 数据层

seekdb 1.4.0.0，server 模式（Windows 不支持 embedded，Linux/macOS 可通过 `SEEKDB_MODE=embedded` 使用嵌入式）。`seekdb-js` 连接后由 SDK 生成集合表，核心结构：

```sql
CREATE TABLE `c$v2$<id>` (
  id        VARBINARY(512) PRIMARY KEY,
  document  STRING,
  embedding VECTOR(512),
  metadata  JSON,
  FULLTEXT INDEX idx_fts (document) WITH PARSER ngram2,
  VECTOR INDEX idx_vec (embedding) WITH (
    DISTANCE=cosine, TYPE=hnsw, LIB=vsag,
    M=16, EF_CONSTRUCTION=200, EF_SEARCH=64)
) ORGANIZATION = HEAP;
```

另有关系表 `kb_collections`（显示名、模型、维度、精度、文档/块计数、最近导入/刷新时间）和 `kb_documents`（docId、标题、来源、tags、块数），用于集合与会话状态。

混合检索由服务端一次调用完成：

```js
await collection.hybridSearch({
  query: { whereDocument: { $contains: normalizedQuery } },
  knn: { queryEmbeddings: [queryVector] },
  rank: { rrf: { rankWindowSize: 40, rankConstant: 60 } },
  nResults: topK,
  include: ["documents", "metadatas", "distances"]
});
```

它对应 seekdb 的 `DBMS_HYBRID_SEARCH`（全文 query_string + 向量 KNN + RRF），前端只渲染返回的 `ids/documents/metadatas`，没有客户端融合或二次排序。

**增量与刷新**：块 ID 由 `docId#chunkIndex` 生成，重复导入用 `upsert` 幂等覆盖；一次导入只在最后调用一次 `collection.refresh_index()`（内部 `CALL dbms_index_manager.refresh()`），随后用新文档向量做自检查询，验收中 10/10 通过，新增文档刷新后立即命中。

---

## 4. 状态、优化与实测

**状态**：localStorage 保存当前集合、后端、精度、批大小；页面加载时校验集合并恢复。切换集合会重新读取 `kb_collections` 并清空旧结果。验收覆盖“创建→导入 2 篇→检索→增量 1 篇→切换默认集合→切回→删除”，旧集合结果不残留。

**优化**（同一设备、同一语料，48 块）：

| 优化项 | 优化前 | 优化后 | 结果 |
|---|---:|---:|---:|
| embedding 批大小 1 → 16（FP16 WebGPU） | 352.9 ms | 84.2 ms | **4.19×** 吞吐 |
| 每 8 块刷新一次 → 整批只刷新一次 | 3395 ms | 837 ms | **4.06×** 端到端 |
| INT8 vs FP32（WASM，48 块向量化） | 2072 ms | 1288 ms | **1.61×** |
| FP16 vs FP32（WebGPU，48 块向量化） | 299 ms | 236 ms | **1.26×** |
| WebGPU FP16 vs WASM INT8（48 块向量化） | 1288 ms | 236 ms | **5.45×** |

**分阶段实测**（48 篇 / 48 块，batch=16，3 次建库中位数；浏览器端 `performance.now()`）：

| 配置 | 模型加载 / 预热 | 文档向量化 | 写入 | 索引刷新 | 查询编码 P50 | seekdb 检索 P50 | 端到端 P50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| INT8 + WASM | 588 / 551 ms | 1288 ms | 167 ms | 705 ms | 8.5 ms | 9.8 ms | 27.4 ms |
| FP16 + WebGPU | 824 / 620 ms | 236 ms | 158 ms | 706 ms | 10.3 ms | 7.3 ms | 25.5 ms |
| FP32 + WASM | 1040 / 675 ms | 2072 ms | 156 ms | 404 ms | 10.8 ms | 7.1 ms | 26.0 ms |
| FP32 + WebGPU | 1166 / 708 ms | 299 ms | 175 ms | 604 ms | 9.7 ms | 6.8 ms | 24.9 ms |

端到端 = 查询编码 + HTTP + seekdb 混合检索，不含模型加载；预热后重复 20 条查询取 P50/P95。首次打开到首条结果：FP16 约 `0.82 + 0.62 + 0.10 ≈ 1.5 s`，INT8 约 `0.59 + 0.55 + 0.10 ≈ 1.2 s`（模型文件已在本机，不含下载）。首次真实查询约 90–110 ms，预热后 P50 约 25–27 ms。

测试条件：Windows 11，Edge 156.0.4314.50，Node 24.15，16 逻辑核，AMD Radeon 780M / NVIDIA RTX 4060（WebGPU adapter），seekdb 1.4.0.0 @ 127.0.0.1:2881，HNSW `M=16 / EF_CONSTRUCTION=200 / EF_SEARCH=64`，全文 `ngram2 2–2`，RRF `k=60`。质量集 48 篇 / 20 查询，相关度 2/1/0，R@5、nDCG@5、MRR@10；每配置 3 次独立建库，性能取中位数。

---

## 5. 合规与复现

- 无云端推理：所有 embedding 在浏览器执行；模型文件同源静态提供；服务端只接收向量、原文和元数据，并与本机 seekdb 通信。
- 存储与检索全部使用 seekdb；没有用 IndexedDB / 内存数组替代向量检索。
- 复现：`npm install` → 启动 seekdb → `npm start`；模型文件已随仓库提供，`npm run fetch-model -- --check` 可校验；`npm test`、`node scripts/acceptance.mjs`、`node scripts/fallback-test.mjs` 可复跑功能与降级测试。
- 更详细的逐条日志、原始 JSON 和复现命令见 `docs/benchmark.md`、`docs/test-log.md`、`docs/reproduction.md`。

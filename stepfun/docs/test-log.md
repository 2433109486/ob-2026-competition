# 测试日志

运行时间：2026-10-29（Asia/Shanghai）  
环境：Windows 11，Node 24.15.0，Edge 156.0.4314.50，seekdb 1.4.0.0 @ `127.0.0.1:2881`。

## 1. 单元测试

```text
$ npm test
> node --test tests/unit.test.js
✔ chunkText keeps paragraphs and respects the configured window
✔ makeChunks produces stable ids for idempotent imports
✔ extractTitle prefers markdown heading
✔ parseFiles supports markdown and JSON arrays
✔ retrieval metrics handle graded relevance and duplicate chunks
ℹ tests 5
ℹ pass 5
ℹ fail 0
```

## 2. 功能验收

`node scripts/acceptance.mjs` 会创建一个临时集合，完成两篇首次导入、增量第三篇、两次检索、切换默认集合、切回、删除，并检查浏览器运行时错误。

```text
PASS 创建并切换集合 — accept_mvtfgxig
PASS 首次增量导入两篇 — docs=2 chunks=2, refreshMs=704.7, verified=true
PASS 首次导入后刷新自检
PASS 检索量子文档命中 top1 — 量子纠缠实验记录
PASS 增量导入第三篇 — docs=3 chunks=3, refreshMs=504.6, verified=true
PASS 新增文档刷新后可检索 — 深海热泉生态系统
PASS 切换到默认集合后不残留临时集合结果
PASS 切回临时集合状态正确
PASS 删除临时集合
PASS 浏览器无运行时错误
{ "passed": 10, "failed": 0 }
```

覆盖点：

- `upsert` 幂等与 `docId#chunkIndex` 稳定 ID；
- 增量写入后 `refresh_index()`，新文档立即被混合检索命中；
- 集合切换后查询结果、统计与会话状态与当前集合一致；
- 删除集合清理 `kb_collections` / `kb_documents` 与向量表。

## 3. WebGPU 自动降级

`node scripts/fallback-test.mjs` 使用 `--disable-gpu --disable-software-rasterizer` 启动 Edge，模拟“`navigator.gpu` 存在但 adapter 不可用”。

```text
BEFORE {"gpu":true,"state":{"ok":true,"backend":"seekdb-server","mode":"server","version":"5.7.25-OceanBase seekdb-v1.4.0.0"}}
AFTER {
  "device":"wasm",
  "dtype":"q8",
  "fallback":"navigator.gpu 存在，但没有可用的 GPU adapter",
  "badge":"WASM · Q8",
  "hits":8
}
```

后端卡片同时显示降级原因；应用仍完成查询向量化、seekdb 混合检索和结果展示。截图：[`screenshots/05-fallback-wasm.png`](screenshots/05-fallback-wasm.png)。

## 4. 网络审计

`node scripts/network-audit.mjs` 加载页面、加载模型并执行一次查询，记录所有请求：

```json
{
  "requestCount": 20,
  "externalRequests": [],
  "hosts": ["127.0.0.1:5173"]
}
```

20 个请求全部是同源静态文件、模型文件和本地 API；没有 Hugging Face CDN、embedding API 或其他外部主机。模型编码实际发生在浏览器 ONNX Runtime Web 中。

## 5. 端到端冒烟

`node scripts/e2e.mjs`（`backend=auto`，WebGPU FP16）：页面加载、集合恢复、模型加载、查询、结果渲染均无 `pageerror`：

```text
STATE collection=default, docCount=48, chunkCount=48, dtype=fp16, seekdb=ready
SEARCH hits=8, queryMs=90.6ms, searchMs=10.5ms, e2eMs=111.8ms, backend=webgpu, dtype=fp16
ERRORS 0
```

首次查询的 90 ms 包含 WebGPU 缓存/着色器冷启动；预热后 P50 见基准报告。

## 6. 基准脚本

```text
node scripts/bench-collections.mjs       # 4 个精度/后端组合 × 3 次建库
node scripts/repeat-bench.mjs            # 每个配置同一建库重复 3 次
node scripts/optimization-bench.mjs      # batch 1/4/8/16/32 + 刷新策略
```

全部完成，无脚本异常；原始 JSON 见 [`results/`](results/)。关键结果：

- 48 篇文档 / 48 块；
- INT8 WASM：R@5 0.733，nDCG@5 0.861；FP32 WASM：0.750 / 0.866；
- FP16 WebGPU：R@5 0.750，nDCG@5 0.866，与 FP32 WebGPU 一致；
- batch 16 比 batch 1 快 4.19×；整批刷新比每 8 块刷新快 4.06×；
- 查询端到端 P50：25–27 ms（预热后，不含模型加载）。

## 7. 已知限制

- Windows 上 seekdb 的 embedded 模式尚未支持，应用默认 server 模式；Linux/macOS 可通过 `SEEKDB_MODE=embedded` 使用嵌入式。
- HNSW 是近似索引，重建后个别查询的排序会有小幅波动（本评测集约 ±0.03 nDCG）；报告中给出 3 次独立建库的中位数。
- WebGPU 在 headless Edge 下的 P95 会受系统调度影响；P50 更稳定。
- 切换集合后如果手动改变精度/后端，查询向量空间可能与集合已存向量不一致；界面会显示精度不一致警告。重新导入或保持同一精度即可。

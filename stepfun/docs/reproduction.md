# 复现步骤

## 0. 目录与前置条件

```bash
cd stepfun
node --version   # >= 20
npm --version
```

需要：

- Node.js 20+（实测 24.15.0）
- Chrome/Edge 最新版（实测 Edge 156）
- seekdb 1.4.0（Windows 使用本地 server；Linux/macOS 也可以嵌入式）

## 1. 安装

```bash
npm install
```

仓库根目录的 `.npmrc` 设置了 `legacy-peer-deps=true`：`seekdb@1.4.0` 的可选 peer `@seekdb/default-embed` 在 npm 上存在 `workspace:*` 元数据，普通 npm 解析会报 `EUNSUPPORTEDPROTOCOL`。本项目不使用该默认 embedding，因此忽略 peer 依赖即可。

模型文件（INT8 + FP16）已随仓库提供。若克隆时缺失：

```bash
npm run fetch-model
npm run fetch-model -- --check
# 需要 FP32 基线时：
npm run fetch-model -- --all
```

模型固定 revision 与 SHA-256 见 `web/models/manifest.json`；默认镜像 `hf-mirror.com`，可通过 `HF_ENDPOINT=https://huggingface.co` 切换。

## 2. 启动 seekdb

### Windows（server 模式）

1. 从 <https://github.com/oceanbase/seekdb/releases> 下载 seekdb 1.4 win64。
2. 解压到 `vendor/seekdb/`，或设置 `SEEKDB_EXE` 指向 `seekdb.exe`。
3. 启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-seekdb.ps1
```

脚本默认：

```text
host      127.0.0.1
port      2881
user      root
password  (empty)
base-dir  .\runtime\seekdb-server
params    log_disk_size=2G datafile_size=512M datafile_maxsize=4G
```

首次 bootstrap 可能需要 1–2 分钟。脚本在端口监听后会再等 10 秒让系统包加载完成。如果 2881 已有 seekdb，会直接复用。

### Linux / macOS

Server 模式：

```bash
./seekdb --base-dir=./runtime/seekdb-server --port=2881
```

或嵌入式模式（无需单独 server）：

```bash
export SEEKDB_MODE=embedded
export SEEKDB_PATH=./runtime/seekdb-embedded
```

## 3. 启动应用

```bash
npm start
```

打开 <http://127.0.0.1:5173>。

可选 `.env`：

```bash
cp .env.example .env
```

常用变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` | 5173 | Web/API 端口 |
| `SEEKDB_HOST` / `SEEKDB_PORT` | 127.0.0.1 / 2881 | seekdb 连接 |
| `SEEKDB_DATABASE` | stepfun_kb | 数据库名 |
| `SEEKDB_MODE` | auto | `server` / `embedded` |
| `SEEKDB_PATH` | 空 | 嵌入式数据目录 |
| `MODEL_DTYPE` | q8 | 默认精度（前端可覆盖） |

健康检查：

```bash
curl http://127.0.0.1:5173/api/health
```

预期 `ok=true`、`backend=seekdb-server`、版本 `OceanBase seekdb-v1.4.0.0`。

## 4. 手工验收

1. 点击“载入示例知识库”，等待进度完成；统计应为 **48 篇 / 48 块**。
2. 搜索“新写入的数据检索不到 如何刷新索引”，应看到“增量导入与索引刷新策略”或“增量写入后检索不到”在 top 2。
3. 点击“查看原文”展开完整块。
4. 点击“运行基准”，应显示 Recall@5 ≈ 0.73（INT8）或 0.75（FP16/FP32），以及 P50/P95。
5. 左栏“新建知识库”→ 切换 → 导入 → 切回；旧集合的结果不应残留。

强制后端：

```text
http://127.0.0.1:5173/?backend=wasm
http://127.0.0.1:5173/?backend=webgpu
http://127.0.0.1:5173/?backend=auto&dtype=fp32
```

URL 参数只写入当前浏览器的 localStorage；可用 DevTools → Application → Local Storage 清除。

## 5. 自动化测试

```bash
npm test
node scripts/acceptance.mjs
node scripts/fallback-test.mjs
node scripts/network-audit.mjs
node scripts/e2e.mjs
```

这些脚本使用 `playwright-core`，默认寻找：

```text
C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
```

其他平台/路径：

```bash
export EDGE_PATH=/path/to/msedge-or-chrome
node scripts/acceptance.mjs
```

`acceptance.mjs` 会创建并删除临时集合，不影响默认知识库；`fallback-test.mjs` 使用 `--disable-gpu` 启动浏览器，不需要真实无 GPU 设备。

## 6. 重新跑基准

```bash
node scripts/bench-collections.mjs
node scripts/optimization-bench.mjs
```

`bench-collections.mjs` 会：

1. 删除并重建 `bench_{int8_wasm,fp32_wasm,fp16_webgpu,fp32_webgpu}`；
2. 用示例语料分别导入；
3. 跑 20 条查询，写 `runtime/results/*.json`；
4. 写截图到 `runtime/screens/`。

只跑某个配置：

```bash
# Windows PowerShell
$env:ONLY="fp16-webgpu"; node scripts/bench-collections.mjs
```

`optimization-bench.mjs` 测 batch 1/4/8/16/32 和“每批刷新 / 只刷新一次”。

## 7. 清理

```bash
# 删除基准集合（在应用运行时）
curl -X DELETE http://127.0.0.1:5173/api/collections/bench_int8_wasm
# ...其余同理
```

`runtime/`、`node_modules/`、`.cache/` 已在 `.gitignore` 中。

import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { config, WEB_DIR, ROOT } from "./config.js";
import { store } from "./db.js";

const app = express();
const here = path.dirname(fileURLToPath(import.meta.url));
const NODE_MODULES = path.join(ROOT, "node_modules");

app.disable("x-powered-by");
app.use(express.json({ limit: "64mb" }));

// SharedArrayBuffer (WASM threads) requires cross-origin isolation. The same
// headers do not affect WebGPU execution.
app.use((req, res, next) => {
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  res.setHeader("X-Content-Type-Options", "nosniff");
  next();
});

const staticOptions = {
  setHeaders(res, filePath) {
    if (filePath.endsWith(".onnx") || filePath.endsWith(".wasm")) {
      res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    } else if (filePath.endsWith(".js") || filePath.endsWith(".mjs")) {
      res.setHeader("Cache-Control", "public, max-age=3600");
    } else {
      res.setHeader("Cache-Control", "no-cache");
    }
  },
};

app.use(
  "/vendor/transformers",
  express.static(path.join(NODE_MODULES, "@huggingface/transformers/dist"), staticOptions),
);
app.use(
  "/vendor/ort",
  express.static(path.join(NODE_MODULES, "onnxruntime-web/dist"), staticOptions),
);
app.use("/models", express.static(path.join(WEB_DIR, "models"), staticOptions));
app.use("/seed", express.static(path.join(WEB_DIR, "seed"), staticOptions));
app.use("/docs", express.static(path.join(ROOT, "docs"), staticOptions));

async function ensureStore(req, res, next) {
  try {
    await store.init();
    next();
  } catch (error) {
    res.status(503).json({
      error: "seekdb 尚未就绪",
      detail: error instanceof Error ? error.message : String(error),
      hint:
        "请确认 seekdb 1.4 已启动并监听 SEEKDB_HOST:SEEKDB_PORT（默认 127.0.0.1:2881）。",
    });
  }
}

app.get("/api/health", async (req, res) => {
  try {
    await store.init();
    res.json(await store.health());
  } catch (error) {
    res.status(503).json({
      ok: false,
      backend: store.backend,
      mode: store.mode,
      error: error instanceof Error ? error.message : String(error),
      hint: "启动 seekdb 1.4 后重试；Windows 请使用本地 server 模式。",
    });
  }
});

app.get("/api/config", (req, res) => {
  const modelDir = path.join(WEB_DIR, "models", config.model.id, "onnx");
  const sizes = {};
  for (const file of ["model_quantized.onnx", "model_fp16.onnx", "model.onnx"]) {
    try {
      sizes[file] = fs.statSync(path.join(modelDir, file)).size;
    } catch {
      sizes[file] = null;
    }
  }
  res.json({
    model: {
      ...config.model,
      localPath: `/models/${config.model.id}/`,
      files: sizes,
    },
    seekdb: {
      host: config.seekdb.host,
      port: config.seekdb.port,
      database: config.seekdb.database,
      mode: config.seekdb.mode,
    },
    collection: {
      defaultName: config.collection.defaultName,
      hnsw: config.collection.hnsw,
      fulltext: config.collection.fulltext,
    },
    limits: config.limits,
    node: process.version,
    platform: `${process.platform}-${process.arch}`,
  });
});

app.get("/api/collections", ensureStore, async (req, res, next) => {
  try {
    res.json({ collections: await store.listCollections() });
  } catch (error) {
    next(error);
  }
});

app.post("/api/collections", ensureStore, async (req, res, next) => {
  try {
    const info = await store.createCollection({
      name: req.body?.name,
      displayName: req.body?.displayName,
    });
    res.status(201).json({ collection: info });
  } catch (error) {
    next(error);
  }
});

app.get("/api/collections/:name", ensureStore, async (req, res, next) => {
  try {
    res.json({ collection: await store.collectionInfo(req.params.name) });
  } catch (error) {
    next(error);
  }
});

app.delete("/api/collections/:name", ensureStore, async (req, res, next) => {
  try {
    res.json(await store.deleteCollection(req.params.name));
  } catch (error) {
    next(error);
  }
});

app.post("/api/collections/:name/clear", ensureStore, async (req, res, next) => {
  try {
    res.json(await store.clearCollection(req.params.name));
  } catch (error) {
    next(error);
  }
});

app.get("/api/documents", ensureStore, async (req, res, next) => {
  try {
    const limit = Number(req.query.limit || 200);
    const docs = await store.listDocuments(req.query.collection, limit);
    res.json({ documents: docs });
  } catch (error) {
    next(error);
  }
});

app.post("/api/import", ensureStore, async (req, res, next) => {
  try {
    const body = req.body || {};
    const result = await store.importDocuments(body.collection || config.collection.defaultName, {
      documents: body.documents,
      embeddings: body.embeddings,
      model: body.model,
      dtype: body.dtype,
      refresh: body.refresh !== false,
    });
    res.json(result);
  } catch (error) {
    next(error);
  }
});

app.post("/api/search", ensureStore, async (req, res, next) => {
  try {
    const body = req.body || {};
    const result = await store.search(body.collection || config.collection.defaultName, {
      query: body.query,
      embedding: body.embedding,
      topK: body.topK,
    });
    res.json(result);
  } catch (error) {
    next(error);
  }
});

app.post("/api/reset", ensureStore, async (req, res, next) => {
  try {
    const name = req.body?.collection || config.collection.defaultName;
    res.json(await store.clearCollection(name));
  } catch (error) {
    next(error);
  }
});

app.get("/api/version", (req, res) => {
  res.json({
    app: "seekdb-browser-kb",
    version: "1.0.0",
    commit: process.env.GIT_COMMIT || null,
    model: config.model,
    seekdb: { host: config.seekdb.host, port: config.seekdb.port },
  });
});

app.use("/api", (req, res) => {
  res.status(404).json({ error: "API 不存在", path: req.path });
});

app.use(express.static(WEB_DIR, staticOptions));

app.use((req, res, next) => {
  if (req.method !== "GET" && req.method !== "HEAD") return next();
  const index = path.join(WEB_DIR, "index.html");
  if (fs.existsSync(index)) return res.sendFile(index);
  next();
});

app.use((error, req, res, next) => {
  if (res.headersSent) return next(error);
  const status = Number(error?.statusCode) || 500;
  const message = error instanceof Error ? error.message : String(error);
  if (status >= 500) console.error("[api]", error);
  res.status(status).json({ error: message });
});

const server = app.listen(config.port, config.host, () => {
  console.log(`[seekdb-kb] http://${config.host}:${config.port}`);
  console.log(`[seekdb-kb] web root: ${WEB_DIR}`);
  store
    .init()
    .then(() => console.log(`[seekdb-kb] seekdb ready (${store.backend})`))
    .catch((error) => {
      console.error("[seekdb-kb] seekdb not ready:", error.message);
      console.error("[seekdb-kb] start seekdb 1.4 on 127.0.0.1:2881, then reload.");
    });
});

function shutdown(signal) {
  console.log(`[seekdb-kb] ${signal}, closing...`);
  server.close(async () => {
    await store.close();
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 5000).unref();
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

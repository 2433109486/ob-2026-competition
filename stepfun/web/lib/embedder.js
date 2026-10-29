import { pipeline, env } from "@huggingface/transformers";

const MODEL_ID = "bge-small-zh-v1.5";
const DIMENSION = 512;

function now() {
  return performance.now();
}

function sleep(ms = 0) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class EmbeddingService {
  constructor({ queryPrefix = "" } = {}) {
    this.queryPrefix = queryPrefix;
    this.pipe = null;
    this.device = null;
    this.dtype = null;
    this.loadInfo = null;
    this.loadPromise = null;
    this.fallbackReason = "";
    this.detectedGpu = null;
    this.lastRun = null;
    this._configureEnv();
  }

  _configureEnv() {
    env.allowRemoteModels = false;
    env.allowLocalModels = true;
    env.localModelPath = "/models/";
    env.useBrowserCache = true;
    env.backends.onnx.wasm.wasmPaths = "/vendor/ort/";
    env.backends.onnx.wasm.simd = true;
    const cores = Number(navigator.hardwareConcurrency || 2);
    env.backends.onnx.wasm.numThreads = Math.max(1, Math.min(4, cores - 1));
    env.backends.onnx.wasm.proxy = false;
  }

  async detectWebGPU() {
    if (this.detectedGpu !== null) return this.detectedGpu;
    if (!("gpu" in navigator) || !navigator.gpu) {
      this.detectedGpu = { available: false, reason: "当前浏览器未暴露 navigator.gpu" };
      return this.detectedGpu;
    }
    try {
      const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
      if (!adapter) {
        this.detectedGpu = { available: false, reason: "navigator.gpu 存在，但没有可用的 GPU adapter" };
      } else {
        this.detectedGpu = {
          available: true,
          adapter: adapter.info || {},
          reason: "",
        };
      }
    } catch (error) {
      this.detectedGpu = {
        available: false,
        reason: `requestAdapter 失败：${error instanceof Error ? error.message : String(error)}`,
      };
    }
    return this.detectedGpu;
  }

  async resolveDevice(preference = "auto") {
    if (preference === "wasm") return { device: "wasm", reason: "用户手动选择 WASM" };
    const gpu = await this.detectWebGPU();
    if (gpu.available) return { device: "webgpu", reason: "" };
    if (preference === "webgpu") {
      return { device: "wasm", reason: `WebGPU 不可用，已自动降级：${gpu.reason}` };
    }
    return { device: "wasm", reason: gpu.reason || "WebGPU 不可用" };
  }

  resolveDtype(device, requested = "auto") {
    if (requested && requested !== "auto") return requested;
    return device === "webgpu" ? "fp16" : "q8";
  }

  async load({ backend = "auto", dtype = "auto", onProgress = () => {} } = {}) {
    const resolved = await this.resolveDevice(backend);
    const device = resolved.device;
    const finalDtype = this.resolveDtype(device, dtype);
    const key = `${device}:${finalDtype}`;

    if (this.pipe && this.loadInfo?.key === key) return this.loadInfo;

    if (this.loadPromise) {
      await this.loadPromise;
      if (this.loadInfo?.key === key) return this.loadInfo;
    }

    this.pipe = null;
    this.device = device;
    this.dtype = finalDtype;
    this.fallbackReason = resolved.reason;
    const started = now();
    const fileProgress = new Map();

    const progressCallback = (event) => {
      if (!event?.file) return;
      if (event.status === "progress" || event.status === "done" || event.status === "initiate") {
        fileProgress.set(event.file, {
          status: event.status,
          progress: event.progress ?? (event.status === "done" ? 100 : 0),
          loaded: event.loaded,
          total: event.total,
        });
        onProgress({
          stage: "model",
          file: event.file,
          status: event.status,
          progress: event.progress ?? (event.status === "done" ? 100 : 0),
          loaded: event.loaded,
          total: event.total,
          device,
          dtype: finalDtype,
          reason: this.fallbackReason,
        });
      }
    };

    onProgress({
      stage: "model",
      status: "start",
      device,
      dtype: finalDtype,
      reason: this.fallbackReason,
      message:
        device === "webgpu"
          ? "正在加载 WebGPU 推理会话（FP16）"
          : "正在加载 WASM 推理会话（INT8）",
    });

    this.loadPromise = (async () => {
      let pipe;
      try {
        pipe = await pipeline("feature-extraction", MODEL_ID, {
          dtype: finalDtype,
          device,
          progress_callback: progressCallback,
        });
      } catch (error) {
        if (device === "webgpu") {
          this.fallbackReason = `WebGPU 初始化失败，自动降级 WASM：${
            error instanceof Error ? error.message : String(error)
          }`;
          this.device = "wasm";
          this.dtype = dtype === "auto" ? "q8" : finalDtype === "fp16" ? "q8" : finalDtype;
          this.loadInfo = null;
          onProgress({
            stage: "model",
            status: "fallback",
            device: "wasm",
            dtype: this.dtype,
            reason: this.fallbackReason,
          });
          pipe = await pipeline("feature-extraction", MODEL_ID, {
            dtype: this.dtype,
            device: "wasm",
            progress_callback: progressCallback,
          });
        } else {
          throw error;
        }
      }

      this.pipe = pipe;
      const loadMs = now() - started;
      onProgress({
        stage: "warmup",
        status: "start",
        device: this.device,
        dtype: this.dtype,
        loadMs,
      });
      const warmStarted = now();
      // Warm the batch shape used by the import path, not just a single
      // sequence: the first WebGPU dispatch for a new shape pays shader
      // compilation cost that should not land on the user's first document.
      const warmupText =
        "端侧知识库需要在浏览器内完成文档分块、向量化与混合检索。".repeat(5);
      await this.embed(
        Array.from({ length: 16 }, (_, index) => `${warmupText} ${index + 1}`),
        { batchSize: 16, skipStats: true },
      );
      const warmupMs = now() - warmStarted;
      this.loadInfo = {
        key: `${this.device}:${this.dtype}`,
        model: MODEL_ID,
        dimension: DIMENSION,
        device: this.device,
        dtype: this.dtype,
        loadMs,
        warmupMs,
        fallbackReason: this.fallbackReason,
        files: [...fileProgress.entries()].map(([file, value]) => ({ file, ...value })),
        loadedAt: new Date().toISOString(),
      };
      onProgress({
        stage: "model",
        status: "ready",
        device: this.device,
        dtype: this.dtype,
        loadMs,
        warmupMs,
        reason: this.fallbackReason,
      });
      return this.loadInfo;
    })();

    try {
      return await this.loadPromise;
    } finally {
      this.loadPromise = null;
    }
  }

  async embed(texts, { batchSize = 8, onBatch = () => {}, skipStats = false } = {}) {
    if (!this.pipe) throw new Error("embedding 模型尚未加载");
    if (!Array.isArray(texts) || texts.length === 0) return [];
    const size = Math.max(1, Math.min(Number(batchSize) || 8, 32));
    const vectors = [];
    const batchTimes = [];
    const started = now();
    for (let start = 0; start < texts.length; start += size) {
      const batch = texts.slice(start, start + size);
      const batchStarted = now();
      const output = await this.pipe(batch, { pooling: "cls", normalize: true });
      const batchMs = now() - batchStarted;
      const rows = output.tolist();
      if (!Array.isArray(rows) || rows.length !== batch.length) {
        throw new Error(`模型输出批次不匹配：输入 ${batch.length}，输出 ${rows?.length}`);
      }
      for (const row of rows) {
        if (!Array.isArray(row) || row.length !== DIMENSION) {
          throw new Error(`模型输出维度异常：${row?.length}，期望 ${DIMENSION}`);
        }
        vectors.push(row);
      }
      batchTimes.push(batchMs);
      onBatch({
        done: Math.min(start + size, texts.length),
        total: texts.length,
        batchMs,
        textsPerSecond: (batch.length * 1000) / Math.max(batchMs, 0.01),
      });
      // Let the browser paint the progress bar between batches.
      await sleep(0);
    }
    const totalMs = now() - started;
    if (!skipStats) {
      this.lastRun = {
        count: texts.length,
        batchSize: size,
        totalMs,
        textsPerSecond: (texts.length * 1000) / Math.max(totalMs, 0.01),
        batchTimes,
        device: this.device,
        dtype: this.dtype,
        at: new Date().toISOString(),
      };
    }
    return vectors;
  }

  async embedQuery(query) {
    if (!this.pipe) throw new Error("embedding 模型尚未加载");
    const text = `${this.queryPrefix}${String(query || "").trim()}`;
    const started = now();
    const output = await this.pipe([text], { pooling: "cls", normalize: true });
    const rows = output.tolist();
    const ms = now() - started;
    return { vector: rows[0], ms, text };
  }

  status() {
    return {
      loaded: Boolean(this.pipe),
      model: MODEL_ID,
      dimension: DIMENSION,
      device: this.device,
      dtype: this.dtype,
      loadInfo: this.loadInfo,
      fallbackReason: this.fallbackReason,
      gpu: this.detectedGpu,
      lastRun: this.lastRun,
    };
  }
}

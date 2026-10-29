import { api } from "./lib/api.js";
import { EmbeddingService } from "./lib/embedder.js";
import { makeChunks, parseFiles, extractTitle, hashString } from "./lib/chunk.js";
import {
  escapeHtml,
  formatMs,
  highlight,
  median,
  ndcgAtK,
  percentile,
  recallAtK,
  mrrAtK,
  downloadJson,
  round,
} from "./lib/metrics.js";

const $ = (id) => document.getElementById(id);
const formatInt = new Intl.NumberFormat("zh-CN");
const STORAGE = {
  collection: "seekbase.collection",
  backend: "seekbase.backend",
  dtype: "seekbase.dtype",
  batchSize: "seekbase.batchSize",
};

const state = {
  config: null,
  health: null,
  collections: [],
  collection: null,
  documents: [],
  embedder: null,
  modelLoading: null,
  serverReady: false,
  busy: false,
  searching: false,
  benchmarking: false,
  pendingFiles: [],
  lastImport: null,
  lastSearch: null,
  lastBenchmark: null,
  toastTimer: null,
  modalAction: null,
  initialized: false,
};

/* ------------------------------------------------------------------ boot */
const ready = init();
window.__SEEKBASE__ = {
  ready,
  getState: () => ({
    collection: state.collection,
    collections: state.collections,
    config: state.config,
    health: state.health,
    lastImport: state.lastImport,
    lastSearch: state.lastSearch,
    lastBenchmark: state.lastBenchmark,
    embedding: state.embedder?.status() || null,
  }),
  importSample: (force = true) => loadSample(force),
  importDocs: (docs) => runImport(docs, "API 导入"),
  search: (query) => runSearch(query),
  benchmark: () => runBenchmark(),
  switchCollection: (name) => selectCollection(name),
  downloadBenchmark: () => downloadBenchmark(),
  ensureModel: () => ensureModel(),
  embedTexts: async (texts, batchSize, collect = true) => {
    await ensureModel();
    const started = performance.now();
    const vectors = await state.embedder.embed(texts, { batchSize });
    return {
      vectors: collect ? vectors : undefined,
      ms: performance.now() - started,
      status: state.embedder.status(),
    };
  },
};

async function init() {
  bindEvents();
  try {
    state.config = await api.config();
    state.embedder = new EmbeddingService({ queryPrefix: state.config.model.queryPrefix });
    applyConfig();
    await refreshHealth();
    if (state.serverReady) {
      await loadCollections();
      const saved = localStorage.getItem(STORAGE.collection);
      const target =
        state.collections.find((item) => item.name === saved)?.name ||
        state.collections[0]?.name;
      if (target) await selectCollection(target, { initial: true });
    } else {
      renderUnavailable();
    }
  } catch (error) {
    console.error(error);
    showFatal(error);
  } finally {
    state.initialized = true;
  }
}

function applyConfig() {
  const { model, collection } = state.config;
  $("statDim").textContent = model.dimension;
  $("modelBadge").textContent = "模型未加载";
  const params = new URLSearchParams(location.search);
  const backend = params.get("backend");
  if (backend === "wasm" || backend === "webgpu") {
    localStorage.setItem(STORAGE.backend, backend);
  }
  const dtypeParam = params.get("dtype");
  if (["q8", "fp16", "fp32"].includes(dtypeParam)) {
    localStorage.setItem(STORAGE.dtype, dtypeParam);
  }
  const savedBackend = localStorage.getItem(STORAGE.backend) || "auto";
  const savedDtype = localStorage.getItem(STORAGE.dtype) || "auto";
  const savedBatch = localStorage.getItem(STORAGE.batchSize) || "16";
  $("backendSelect").value = ["auto", "webgpu", "wasm"].includes(savedBackend)
    ? savedBackend
    : "auto";
  $("dtypeSelect").value = ["auto", "q8", "fp16", "fp32"].includes(savedDtype)
    ? savedDtype
    : "auto";
  $("batchSize").value = ["1", "4", "8", "16", "32"].includes(savedBatch) ? savedBatch : "8";

  const files = model.files || {};
  const dtypeOption = (value, file) => {
    const option = $("dtypeSelect").querySelector(`option[value="${value}"]`);
    if (!option) return;
    if (!files[file]) {
      option.disabled = true;
      option.textContent = `${option.textContent}（文件未安装）`;
    }
  };
  dtypeOption("q8", "model_quantized.onnx");
  dtypeOption("fp16", "model_fp16.onnx");
  dtypeOption("fp32", "model.onnx");

  $("currentTitle").textContent = "我的知识库";
  $("currentMeta").textContent = `默认集合：${collection.defaultName} · ${model.dimension} 维 · ${
    model.dtype === "q8" ? "INT8" : model.dtype
  }`;
}

async function refreshHealth() {
  try {
    const health = await api.health();
    state.health = health;
    state.serverReady = Boolean(health.ok);
    $("dbDot").className = "status-dot ok";
    $("dbStatus").textContent = "seekdb 已连接";
    $("dbVersion").textContent = `${health.host || "embedded"} · v${health.version || "?"}`;
    $("dbVersion").title = `${health.backend} · ping ${health.pingMs} ms`;
  } catch (error) {
    state.serverReady = false;
    $("dbDot").className = "status-dot bad";
    $("dbStatus").textContent = "seekdb 未连接";
    $("dbVersion").textContent = error.message || "请启动 seekdb";
    $("dbVersion").title = error.hint || "";
    throw error;
  }
}

async function loadCollections() {
  const response = await api.collections();
  state.collections = response.collections || [];
  $("collectionCount").textContent = state.collections.length;
  renderCollections();
  return state.collections;
}

async function selectCollection(name, { initial = false } = {}) {
  if (!name) return;
  const info = (await api.collection(name)).collection;
  state.collection = info;
  localStorage.setItem(STORAGE.collection, name);
  state.lastSearch = null;
  state.lastBenchmark = null;
  state.pendingFiles = [];
  $("fileInput").value = "";
  $("results").innerHTML = emptyStateMarkup();
  bindEmptyState();
  $("searchMeta").hidden = true;
  $("benchBody").innerHTML = benchPlaceholder();
  $("benchStatus").textContent = "基准会复用当前集合与当前模型精度；建议先导入示例知识库。";
  $("benchDownloadBtn").disabled = true;
  renderAll();
  if (!initial) {
    toast(`已切换到「${info.displayName}」`);
  }
}

function renderAll() {
  renderCollections();
  renderHeader();
  renderStats();
  renderBackendCard();
  renderTiming();
}

function renderCollections() {
  const list = $("collectionList");
  list.innerHTML = state.collections
    .map((item) => {
      const active = state.collection?.name === item.name;
      const defaultKey = state.config?.collection?.defaultName || "default";
      const deleteButton =
        item.name === defaultKey
          ? ""
          : `<button class="c-delete" type="button" data-delete="${escapeHtml(item.name)}" title="删除集合" aria-label="删除 ${escapeHtml(item.displayName)}">×</button>`;
      return `<div class="collection-item ${active ? "active" : ""}" role="button" tabindex="0" data-collection="${escapeHtml(item.name)}">
        <span class="c-icon">◈</span>
        <span class="c-main">
          <span class="c-name">${escapeHtml(item.displayName)}</span>
          <span class="c-meta">${formatInt.format(item.docCount || 0)} 篇 · ${formatInt.format(item.chunkCount || 0)} 块</span>
        </span>
        ${deleteButton}
      </div>`;
    })
    .join("");
}

function renderHeader() {
  const current = state.collection;
  if (!current) return;
  $("currentTitle").textContent = current.displayName || current.name;
  const refresh = current.lastRefreshAt ? `上次刷新 ${relativeTime(current.lastRefreshAt)}` : "尚未建立索引";
  $("currentMeta").textContent = `${formatInt.format(current.docCount)} 篇文档 · ${formatInt.format(
    current.chunkCount,
  )} 个分块 · ${current.dimension || 512} 维 · ${refresh}`;
  const model = state.embedder?.status();
  $("modelBadge").textContent = model?.loaded
    ? `${model.model} · ${model.dtype.toUpperCase()}`
    : "模型未加载";
}

function renderStats() {
  const current = state.collection;
  if (!current) return;
  $("statDocs").textContent = formatInt.format(current.docCount || 0);
  $("statChunks").textContent = formatInt.format(current.chunkCount || 0);
  $("statDim").textContent = current.dimension || state.config?.model?.dimension || 512;
  $("statRefresh").textContent = current.lastRefreshAt ? relativeTime(current.lastRefreshAt) : "—";
  const side = $("sidebarStats");
  if (side) {
    side.innerHTML = `<div><strong>${formatInt.format(current.docCount || 0)}</strong><span>文档</span></div>
      <div><strong>${formatInt.format(current.chunkCount || 0)}</strong><span>分块</span></div>
      <div><strong>${current.dimension || 512}</strong><span>维向量</span></div>`;
  }
}

function renderBackendCard() {
  const status = state.embedder?.status();
  const badge = $("backendBadge");
  const cardBadge = $("backendCardBadge");
  const body = $("backendCardBody");
  badge.className = "badge badge-backend";
  if (!status?.loaded) {
    badge.innerHTML = `<span class="badge-dot"></span>后端待加载`;
    cardBadge.textContent = "待加载";
    body.innerHTML = `<p class="muted">首次导入或检索时加载模型。支持时优先 WebGPU，不可用会自动降级到 WASM。</p>`;
    return;
  }
  const isWebGPU = status.device === "webgpu";
  badge.classList.add(isWebGPU ? "is-webgpu" : "is-wasm");
  badge.innerHTML = `<span class="badge-dot"></span>${isWebGPU ? "WebGPU" : "WASM"} · ${status.dtype.toUpperCase()}`;
  badge.title = status.fallbackReason || (isWebGPU ? "WebGPU 执行提供器" : "WASM 执行提供器");
  cardBadge.textContent = `${isWebGPU ? "WebGPU" : "WASM"} / ${status.dtype}`;
  const load = status.loadInfo?.loadMs;
  const warm = status.loadInfo?.warmupMs;
  const collectionDtype = state.collection?.dtype;
  const mismatch =
    collectionDtype && String(collectionDtype).toLowerCase() !== String(status.dtype).toLowerCase();
  body.innerHTML = `
    <div class="bc-line"><span>模型</span><strong>${escapeHtml(status.model)}</strong></div>
    <div class="bc-line"><span>精度 / 维度</span><strong>${status.dtype.toUpperCase()} · ${status.dimension}d</strong></div>
    <div class="bc-line"><span>加载 / 预热</span><strong>${formatMs(load)} / ${formatMs(warm)}</strong></div>
    <div class="bc-line"><span>执行位置</span><strong>当前浏览器</strong></div>
    ${status.fallbackReason ? `<p class="fallback-note">${escapeHtml(status.fallbackReason)}</p>` : ""}
    ${
      mismatch
        ? `<p class="fallback-note">当前集合的向量由 ${escapeHtml(
            collectionDtype.toUpperCase(),
          )} 生成，查询编码为 ${status.dtype.toUpperCase()}；建议保持同一精度，或重新导入该集合。</p>`
        : ""
    }
  `;
}

function renderTiming() {
  const target = $("timingList");
  if (!target) return;
  const search = state.lastSearch;
  const imp = state.lastImport;
  if (!search && !imp) {
    target.innerHTML = `<div class="timing-row"><span>等待操作</span><span>—</span></div>`;
    return;
  }
  if (search && (!imp || search.at > imp.at)) {
    target.innerHTML = `
      <div class="timing-row"><span>查询向量化</span><span>${formatMs(search.queryMs)}</span></div>
      <div class="timing-row"><span>seekdb 混合检索</span><span>${formatMs(search.searchMs)}</span></div>
      <div class="timing-row"><span>端到端</span><span>${formatMs(search.e2eMs)}</span></div>
      <div class="timing-row"><span>后端</span><span>${search.backend} · ${search.dtype}</span></div>`;
    return;
  }
  target.innerHTML = `
    <div class="timing-row"><span>文档向量化</span><span>${formatMs(imp.embedMs)}</span></div>
    <div class="timing-row"><span>写入 seekdb</span><span>${formatMs(imp.writeMs)}</span></div>
    <div class="timing-row"><span>索引刷新</span><span>${formatMs(imp.refreshMs)}</span></div>
    <div class="timing-row"><span>刷新后可检索</span><span>${imp.verified ? "已验证" : "—"}</span></div>`;
}

/* ------------------------------------------------------------------ import */
function bindEvents() {
  $("dropzone").addEventListener("click", () => $("fileInput").click());
  $("dropzone").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      $("fileInput").click();
    }
  });
  $("fileInput").addEventListener("change", () => {
    state.pendingFiles = [...$("fileInput").files];
    if (state.pendingFiles.length) {
      logImport("已选择文件", state.pendingFiles.map((file) => file.name).join("、"));
    }
  });
  for (const event of ["dragenter", "dragover"]) {
    $("dropzone").addEventListener(event, (e) => {
      e.preventDefault();
      $("dropzone").classList.add("dragover");
    });
  }
  for (const event of ["dragleave", "drop"]) {
    $("dropzone").addEventListener(event, (e) => {
      e.preventDefault();
      $("dropzone").classList.remove("dragover");
    });
  }
  $("dropzone").addEventListener("drop", (event) => {
    const files = [...(event.dataTransfer?.files || [])];
    state.pendingFiles = files;
    if (files.length) logImport("已选择文件", files.map((file) => file.name).join("、"));
  });
  $("sampleBtn").addEventListener("click", () => loadSample(false));
  $("emptySampleBtn").addEventListener("click", () => loadSample(false));
  $("importBtn").addEventListener("click", () => importFromInputs());
  $("searchForm").addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch($("queryInput").value);
  });
  $("exampleChips").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-query]");
    if (!button) return;
    $("queryInput").value = button.dataset.query;
    runSearch(button.dataset.query);
  });
  $("results").addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-toggle]");
    if (!toggle) return;
    const target = document.getElementById(toggle.dataset.toggle);
    if (!target) return;
    const open = target.classList.toggle("open");
    toggle.textContent = open ? "收起原文" : "查看原文";
  });
  $("collectionList").addEventListener("click", async (event) => {
    const deleteButton = event.target.closest("[data-delete]");
    if (deleteButton) {
      event.stopPropagation();
      deleteCollection(deleteButton.dataset.delete);
      return;
    }
    const item = event.target.closest("[data-collection]");
    if (!item) return;
    if (item.dataset.collection === state.collection?.name) return;
    try {
      await selectCollection(item.dataset.collection);
    } catch (error) {
      toast(error.message, "error");
    }
  });
  $("collectionList").addEventListener("keydown", async (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const item = event.target.closest("[data-collection]");
    if (!item) return;
    event.preventDefault();
    if (item.dataset.collection !== state.collection?.name) {
      await selectCollection(item.dataset.collection).catch((error) => toast(error.message, "error"));
    }
  });
  $("newCollectionBtn").addEventListener("click", createCollectionDialog);
  $("clearBtn").addEventListener("click", clearCollectionDialog);
  $("benchBtn").addEventListener("click", runBenchmark);
  $("benchDownloadBtn").addEventListener("click", downloadBenchmark);
  $("backendSelect").addEventListener("change", saveSettings);
  $("dtypeSelect").addEventListener("change", saveSettings);
  $("batchSize").addEventListener("change", saveSettings);
  $("modalCancel").addEventListener("click", closeModal);
  $("modalBackdrop").addEventListener("click", (event) => {
    if (event.target === $("modalBackdrop")) closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("modalBackdrop").hidden) closeModal();
  });
  $("modalConfirm").addEventListener("click", async () => {
    if (!state.modalAction) return;
    const action = state.modalAction;
    $("modalConfirm").disabled = true;
    try {
      const keepOpen = await action();
      if (!keepOpen) closeModal();
    } catch (error) {
      toast(error.message || "操作失败", "error");
    } finally {
      $("modalConfirm").disabled = false;
    }
  });
}

function saveSettings() {
  localStorage.setItem(STORAGE.backend, $("backendSelect").value);
  localStorage.setItem(STORAGE.dtype, $("dtypeSelect").value);
  localStorage.setItem(STORAGE.batchSize, $("batchSize").value);
  if (state.embedder?.status().loaded) {
    logImport("设置已更新", "下一次导入或检索时重新加载模型");
  }
}

async function importFromInputs() {
  const paste = $("pasteText").value.trim();
  try {
    const docs = await parseFiles(state.pendingFiles);
    if (paste) {
      docs.push({
        id: `paste-${hashString(paste)}`,
        title: extractTitle(paste, "粘贴的文本"),
        source: "粘贴文本",
        tags: [],
        text: paste,
      });
    }
    if (!docs.length) {
      toast("请先选择文件或粘贴一段文本", "error");
      return;
    }
    await runImport(docs, "导入");
    state.pendingFiles = [];
    $("fileInput").value = "";
    $("pasteText").value = "";
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadSample(force) {
  if (!state.collection) return;
  if (state.collection.chunkCount > 0 && !force) {
    openModal({
      title: "追加示例知识库？",
      body: `<p>当前集合已有 ${formatInt.format(state.collection.chunkCount)} 个分块。示例语料会使用稳定的文档 ID，重复导入不会产生重复块。</p>`,
      confirmText: "继续导入",
      onConfirm: async () => {
        await loadSample(true);
      },
    });
    return;
  }
  try {
    const response = await fetch("/seed/corpus.json", { cache: "no-store" });
    if (!response.ok) throw new Error("示例语料加载失败");
    const docs = await response.json();
    await runImport(docs, "示例知识库");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function runImport(docs, label) {
  if (state.busy) return;
  if (!state.collection) {
    toast("seekdb 尚未连接", "error");
    return;
  }
  if (!state.serverReady) {
    toast("seekdb 未连接，请先启动本地数据库", "error");
    return;
  }
  state.busy = true;
  setBusy(true);
  $("importLog").innerHTML = "";
  $("importProgress").hidden = false;
  setProgress(2, "准备导入", "正在分块…");
  const started = performance.now();
  try {
    const chunks = docs.flatMap((doc) => makeChunks(doc, { maxChars: 440, overlap: 80 }));
    if (!chunks.length) throw new Error("文本为空，无法分块");
    logImport("解析完成", `${docs.length} 个文档 → ${chunks.length} 个分块`, "ok");
    setProgress(6, "加载 embedding 模型", "首次加载包含模型文件读取与会话创建");

    const wasLoaded = Boolean(state.embedder?.status().loaded);
    const modelInfo = await ensureModel();
    logImport(
      "模型就绪",
      `${modelInfo.device.toUpperCase()} · ${modelInfo.dtype.toUpperCase()} · 加载 ${formatMs(
        modelInfo.loadMs,
      )} / 预热 ${formatMs(modelInfo.warmupMs)}`,
      "ok",
    );
    setProgress(18, "文档向量化", `0 / ${chunks.length} 个分块`);

    const embedStarted = performance.now();
    const vectors = await state.embedder.embed(
      chunks.map((chunk) => `${chunk.title}\n${chunk.text}`),
      {
        batchSize: Number($("batchSize").value) || 8,
        onBatch: (batch) => {
          const pct = 18 + (72 * batch.done) / batch.total;
          setProgress(
            pct,
            "文档向量化",
            `${batch.done} / ${batch.total} 个分块 · ${Math.round(batch.textsPerSecond)} 条/秒`,
          );
        },
      },
    );
    const embedMs = performance.now() - embedStarted;
    logImport(
      "向量化完成",
      `${chunks.length} 个分块 · ${formatMs(embedMs)} · ${Math.round(
        (chunks.length * 1000) / Math.max(embedMs, 1),
      )} 条/秒`,
      "ok",
    );

    setProgress(92, "写入 seekdb", "按批次 upsert，最后统一刷新索引");
    const importStarted = performance.now();
    let writeMs = 0;
    let refreshMs = 0;
    let inserted = 0;
    const batchSize = 128;
    for (let start = 0; start < chunks.length; start += batchSize) {
      const end = Math.min(start + batchSize, chunks.length);
      const isLast = end === chunks.length;
      const result = await api.importDocuments({
        collection: state.collection.name,
        documents: chunks.slice(start, end),
        embeddings: vectors.slice(start, end),
        model: state.config.model.id,
        dtype: state.embedder.status().dtype,
        refresh: isLast,
      });
      writeMs += Number(result.writeMs || 0);
      refreshMs += Number(result.refreshMs || 0);
      inserted += Number(result.insertedChunks || 0);
      setProgress(
        92 + (5 * end) / chunks.length,
        "写入 seekdb",
        `${end} / ${chunks.length} 个分块 · 写入 ${formatMs(writeMs)}${
          isLast ? ` · 刷新 ${formatMs(refreshMs)}` : ""
        }`,
      );
    }
    const importMs = performance.now() - importStarted;
    logImport(
      "写入与刷新",
      `${inserted} 个分块 · 写入 ${formatMs(writeMs)} · 刷新 ${formatMs(refreshMs)}`,
      "ok",
    );

    await refreshHealth();
    await loadCollections();
    state.collection = (await api.collection(state.collection.name)).collection;
    renderAll();

    setProgress(99, "验证新内容", "用刚写入的向量做一次检索，确认刷新后可命中");
    let verified = false;
    try {
      const probe = await api.search({
        collection: state.collection.name,
        query: docs[0]?.title || "新导入的文档",
        embedding: vectors[0],
        topK: Math.min(10, Math.max(5, chunks.length)),
      });
      verified = Boolean(probe.hits?.some((hit) => hit.docId === chunks[0].docId));
    } catch (error) {
      logImport("自检失败", error.message, "warn");
    }
    const totalMs = performance.now() - started;
    state.lastImport = {
      at: Date.now(),
      label,
      docs: docs.length,
      chunks: chunks.length,
      modelLoadMs: wasLoaded ? 0 : modelInfo.loadMs,
      embedMs,
      writeMs,
      refreshMs,
      importMs,
      totalMs,
      verified,
      backend: modelInfo.device,
      dtype: modelInfo.dtype,
    };
    setProgress(100, "导入完成", verified ? "新文档已可检索" : "写入完成，建议手动检索确认");
    logImport(
      "完成",
      `${docs.length} 篇文档 / ${chunks.length} 个分块 · 总耗时 ${formatMs(totalMs)} · ${
        verified ? "刷新后自检通过" : "未通过自检"
      }`,
      verified ? "ok" : "warn",
    );
    renderTiming();
    renderHeader();
    toast(`已写入 ${chunks.length} 个分块，索引刷新后已可检索`);
    if (chunks.length >= 8) {
      $("queryInput").value = docs[0]?.title || "向量检索";
    }
  } catch (error) {
    console.error(error);
    setProgress(100, "导入失败", error.message);
    logImport("错误", error.message, "warn");
    toast(error.message || "导入失败", "error");
  } finally {
    state.busy = false;
    setBusy(false);
    setTimeout(() => {
      $("importProgress").hidden = true;
    }, 3500);
  }
}

async function ensureModel() {
  if (state.modelLoading) return state.modelLoading;
  $("modelLoadProgress").hidden = false;
  $("modelProgressBar").style.width = "0%";
  $("modelProgressText").textContent = "准备加载模型…";
  state.modelLoading = state.embedder
    .load({
      backend: $("backendSelect").value,
      dtype: $("dtypeSelect").value,
      onProgress: (event) => {
        if (event.stage === "model") {
          if (event.status === "start") {
            $("modelProgressText").textContent = event.message || "加载模型…";
          } else if (event.status === "progress") {
            const pct = Math.round(event.progress || 0);
            $("modelProgressBar").style.width = `${pct}%`;
            $("modelProgressText").textContent = `${event.file || "模型文件"} · ${pct}%`;
          } else if (event.status === "fallback") {
            $("modelProgressText").textContent = event.reason;
            toast("WebGPU 不可用，已自动降级到 WASM", "error");
          } else if (event.status === "ready") {
            $("modelProgressBar").style.width = "100%";
            $("modelProgressText").textContent = `就绪 · ${event.device.toUpperCase()} ${String(
              event.dtype,
            ).toUpperCase()} · 预热 ${formatMs(event.warmupMs)}`;
            $("modelLoadProgress").hidden = true;
          }
        } else if (event.stage === "warmup") {
          $("modelProgressText").textContent = "模型已加载，正在预热…";
        }
      },
    })
    .then((info) => {
      renderBackendCard();
      renderHeader();
      updateBadgeAfterLoad(info);
      return info;
    })
    .catch((error) => {
      $("modelProgressText").textContent = `加载失败：${error.message}`;
      toast(`模型加载失败：${error.message}`, "error");
      throw error;
    })
    .finally(() => {
      state.modelLoading = null;
    });
  return state.modelLoading;
}

function updateBadgeAfterLoad(info) {
  $("backendBadge").title = info.fallbackReason || "";
  $("modelBadge").textContent = `${info.model} · ${String(info.dtype).toUpperCase()}`;
}

/* ------------------------------------------------------------------ search */
async function runSearch(queryInput) {
  const query = String(queryInput || "").trim();
  if (!query || state.searching) return;
  if (!state.collection) return;
  if (!state.collection.chunkCount) {
    toast("当前集合还没有文档，请先导入语料", "error");
    return;
  }
  state.searching = true;
  setBusy(true);
  $("searchBtn").disabled = true;
  $("queryInput").value = query;
  const firstLoad = !state.embedder?.status().loaded;
  const started = performance.now();
  try {
    const modelInfo = await ensureModel();
    const queryStart = performance.now();
    const { vector, ms: queryMs } = await state.embedder.embedQuery(query);
    const searchStart = performance.now();
    const result = await api.search({
      collection: state.collection.name,
      query,
      embedding: vector,
      topK: Number($("topKSelect").value) || 8,
    });
    const searchMs = result.searchMs ?? performance.now() - searchStart;
    const e2eMs = performance.now() - searchStart + queryMs;
    state.lastSearch = {
      at: Date.now(),
      query,
      queryMs,
      searchMs,
      e2eMs,
      backend: modelInfo.device,
      dtype: modelInfo.dtype,
      firstLoad,
      hits: result.hits,
      engine: result.engine,
    };
    renderSearchMeta(result, { queryMs, searchMs, e2eMs, firstLoad, modelInfo });
    renderResults(result.hits, query);
    renderTiming();
    window.__SEEKBASE__.lastSearch = state.lastSearch;
  } catch (error) {
    console.error(error);
    toast(error.message || "检索失败", "error");
    $("results").innerHTML = `<div class="no-hits">检索失败：${escapeHtml(error.message)}</div>`;
  } finally {
    state.searching = false;
    setBusy(false);
    $("searchBtn").disabled = false;
  }
}

function renderSearchMeta(result, { queryMs, searchMs, e2eMs, firstLoad, modelInfo }) {
  const meta = $("searchMeta");
  meta.hidden = false;
  meta.innerHTML = `
    <span><strong>${result.hits.length}</strong> 条结果</span>
    <span>查询向量 <strong>${formatMs(queryMs)}</strong></span>
    <span>seekdb 检索 <strong>${formatMs(searchMs)}</strong></span>
    <span>端到端 <strong>${formatMs(e2eMs)}</strong></span>
    ${firstLoad ? `<span>含模型加载 <strong>${formatMs(modelInfo.loadMs)}</strong></span>` : ""}
    <span class="chip">${escapeHtml(result.engine)}</span>`;
}

function renderResults(hits, query) {
  const container = $("results");
  if (!hits?.length) {
    container.innerHTML = `<div class="no-hits">没有检索到结果。试试更短的查询，或检查集合是否为空。</div>`;
    return;
  }
  container.innerHTML = hits
    .map((hit, index) => {
      const fullId = `full-${index}`;
      const snippet = hit.text.length > 260 ? `${hit.text.slice(0, 260)}…` : hit.text;
      const tags = (hit.tags || [])
        .slice(0, 3)
        .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
        .join("");
      return `<article class="result-card" style="animation-delay:${index * 22}ms">
        <div class="result-top">
          <span class="rank">${index + 1}</span>
          <div class="result-main">
            <div class="result-title">
              <h4>${escapeHtml(hit.title)}</h4>
              ${tags}
            </div>
            <p class="result-snippet">${highlight(snippet, query)}</p>
            <div class="result-foot">
              <span class="src">${escapeHtml(hit.source || "local")} · 块 ${hit.chunkIndex + 1}</span>
              <span class="score">融合分 ${Number(hit.score || 0).toFixed(4)}</span>
              <span class="spacer"></span>
              <button type="button" class="result-toggle" data-toggle="${fullId}">查看原文</button>
            </div>
            <div id="${fullId}" class="result-full">${highlight(hit.text, query)}</div>
          </div>
        </div>
      </article>`;
    })
    .join("");
}

/* ------------------------------------------------------------------ benchmark */
async function runBenchmark() {
  if (state.benchmarking) return;
  if (!state.collection?.chunkCount) {
    toast("请先导入示例知识库或自己的文档", "error");
    return;
  }
  state.benchmarking = true;
  setBusy(true);
  $("benchBtn").disabled = true;
  $("benchDownloadBtn").disabled = true;
  $("benchStatus").textContent = "正在加载评测集与模型…";
  $("benchBody").innerHTML = `<div class="bench-placeholder"><div class="bench-bars"><span></span><span></span><span></span><span></span><span></span></div><p>评测运行中，请保持页面在前台。</p></div>`;
  try {
    const evalResponse = await fetch("/seed/eval.json", { cache: "no-store" });
    if (!evalResponse.ok) throw new Error("评测集加载失败");
    const evaluation = await evalResponse.json();
    const modelInfo = await ensureModel();
    const queries = evaluation.queries || [];
    if (!queries.length) throw new Error("评测集为空");

    // Warm up both the model and seekdb before measuring. The warmup results
    // are intentionally excluded from the reported medians.
    $("benchStatus").textContent = "预热模型与 seekdb…";
    for (let i = 0; i < 2; i += 1) {
      const warm = await state.embedder.embedQuery(queries[0].query);
      await api.search({
        collection: state.collection.name,
        query: queries[0].query,
        embedding: warm.vector,
        topK: 10,
      });
    }

    const rows = [];
    for (let index = 0; index < queries.length; index += 1) {
      const item = queries[index];
      const queryStarted = performance.now();
      const embedded = await state.embedder.embedQuery(item.query);
      const dbStarted = performance.now();
      const result = await api.search({
        collection: state.collection.name,
        query: item.query,
        embedding: embedded.vector,
        topK: 10,
      });
      const dbMs = result.searchMs ?? performance.now() - dbStarted;
      const e2eMs = performance.now() - queryStarted;
      rows.push({
        id: item.id,
        query: item.query,
        queryMs: embedded.ms,
        dbMs,
        e2eMs,
        recall5: recallAtK(result.hits, item.relevant, 5),
        ndcg5: ndcgAtK(result.hits, item.relevant, 5),
        mrr10: mrrAtK(result.hits, item.relevant, 10),
        topDocIds: [...new Set(result.hits.map((hit) => hit.docId))].slice(0, 5),
      });
      $("benchStatus").textContent = `评测中 ${index + 1} / ${queries.length} · ${item.query}`;
    }

    const quality = {
      recall5: mean(rows.map((row) => row.recall5)),
      ndcg5: mean(rows.map((row) => row.ndcg5)),
      mrr10: mean(rows.map((row) => row.mrr10)),
    };
    const latency = {
      queryP50: median(rows.map((row) => row.queryMs)),
      queryP95: percentile(rows.map((row) => row.queryMs), 0.95),
      dbP50: median(rows.map((row) => row.dbMs)),
      dbP95: percentile(rows.map((row) => row.dbMs), 0.95),
      e2eP50: median(rows.map((row) => row.e2eMs)),
      e2eP95: percentile(rows.map((row) => row.e2eMs), 0.95),
      modelLoadMs: modelInfo.loadMs,
      warmupMs: modelInfo.warmupMs,
    };
    const result = {
      schema: "seekbase-benchmark/v1",
      timestamp: new Date().toISOString(),
      evaluation: evaluation.name,
      evaluationDescription: evaluation.description,
      collection: state.collection.name,
      collectionDisplayName: state.collection.displayName,
      corpusDocuments: state.collection.docCount,
      corpusChunks: state.collection.chunkCount,
      k: 5,
      queries: rows.length,
      model: {
        id: modelInfo.model,
        revision: state.config.model.revision,
        dimension: modelInfo.dimension,
        dtype: modelInfo.dtype,
        source: state.config.model.source,
      },
      backend: {
        requested: $("backendSelect").value,
        actual: modelInfo.device,
        fallbackReason: modelInfo.fallbackReason || "",
        userAgent: navigator.userAgent,
        hardwareConcurrency: navigator.hardwareConcurrency,
      },
      quality: mapRound(quality),
      latency: mapRound(latency),
      perQuery: rows.map((row) => ({
        ...row,
        queryMs: round(row.queryMs),
        dbMs: round(row.dbMs),
        e2eMs: round(row.e2eMs),
        recall5: round(row.recall5),
        ndcg5: round(row.ndcg5),
        mrr10: round(row.mrr10),
      })),
      notes: [
        "所有查询向量均在浏览器内计算；seekdb 只接收查询向量与查询文本。",
        "延迟为预热后连续运行的实测值，质量指标使用同一套 20 条查询与人工相关度标注。",
        "RRF 融合分不是概率，仅用于排序。",
      ],
    };
    state.lastBenchmark = result;
    window.__SEEKBASE__.lastBenchmark = result;
    renderBenchmark(result);
    $("benchDownloadBtn").disabled = false;
    $("benchStatus").textContent = `完成 · ${rows.length} 条查询 · ${modelInfo.device.toUpperCase()} ${String(
      modelInfo.dtype,
    ).toUpperCase()} · ${state.collection.displayName}`;
    toast("基准完成，可下载 JSON");
  } catch (error) {
    console.error(error);
    $("benchStatus").textContent = `基准失败：${error.message}`;
    toast(error.message || "基准失败", "error");
  } finally {
    state.benchmarking = false;
    setBusy(false);
    $("benchBtn").disabled = false;
  }
}

function renderBenchmark(result) {
  const q = result.quality;
  const l = result.latency;
  const rows = result.perQuery
    .map(
      (row) => `<tr>
        <td>${escapeHtml(row.id)}</td>
        <td>${row.recall5.toFixed(2)}</td>
        <td>${row.ndcg5.toFixed(2)}</td>
        <td>${row.mrr10.toFixed(2)}</td>
        <td>${row.queryMs.toFixed(0)}</td>
        <td>${row.dbMs.toFixed(0)}</td>
        <td>${row.e2eMs.toFixed(0)}</td>
      </tr>`,
    )
    .join("");
  $("benchBody").innerHTML = `
    <div class="bench-grid">
      <div>
        <div class="metric-row">
          <div class="metric"><span>${q.recall5.toFixed(3)}</span><label>Recall@5</label></div>
          <div class="metric"><span>${q.ndcg5.toFixed(3)}</span><label>nDCG@5</label></div>
          <div class="metric"><span>${q.mrr10.toFixed(3)}</span><label>MRR@10</label></div>
        </div>
        <table class="bench-table">
          <thead><tr><th>阶段</th><th>P50</th><th>P95</th></tr></thead>
          <tbody>
            <tr><td>查询向量化</td><td>${formatMs(l.queryP50)}</td><td>${formatMs(l.queryP95)}</td></tr>
            <tr><td>seekdb 混合检索</td><td>${formatMs(l.dbP50)}</td><td>${formatMs(l.dbP95)}</td></tr>
            <tr><td>端到端</td><td>${formatMs(l.e2eP50)}</td><td>${formatMs(l.e2eP95)}</td></tr>
            <tr><td>模型加载 / 预热</td><td>${formatMs(l.modelLoadMs)}</td><td>${formatMs(l.warmupMs)}</td></tr>
          </tbody>
        </table>
        <p class="bench-note">${escapeHtml(result.backend.actual.toUpperCase())} · ${escapeHtml(
          result.model.dtype.toUpperCase(),
        )} · ${result.corpusDocuments} 篇 / ${result.corpusChunks} 块 · 20 条查询。端到端含查询编码与数据库检索，不含模型加载。</p>
      </div>
      <div class="bench-details">
        <details open>
          <summary>逐条查询指标</summary>
          <table class="query-eval-table">
            <thead><tr><th>查询</th><th>R@5</th><th>nDCG@5</th><th>MRR</th><th>编码 ms</th><th>DB ms</th><th>E2E ms</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </details>
      </div>
    </div>`;
}

function downloadBenchmark() {
  if (!state.lastBenchmark) return;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  downloadJson(`seekbase-benchmark-${stamp}.json`, state.lastBenchmark);
}

/* ------------------------------------------------------------------ dialogs */
function createCollectionDialog() {
  openModal({
    title: "新建知识库",
    body: `<p>每个集合独立保存文档、向量和索引；当前页面会记住上次选择。</p>
      <label for="newDisplayName">显示名称</label>
      <input id="newDisplayName" maxlength="60" placeholder="例如：论文笔记" />
      <label for="newKey">集合标识（可选，小写字母/数字）</label>
      <input id="newKey" maxlength="40" placeholder="例如：papers" />`,
    confirmText: "创建",
    onConfirm: async () => {
      const displayName = $("newDisplayName")?.value.trim();
      const rawKey = $("newKey")?.value.trim();
      if (!displayName) {
        toast("请输入显示名称", "error");
        return true;
      }
      const key = (rawKey || `kb-${Date.now().toString(36)}`).toLowerCase().replace(/[^a-z0-9_-]/g, "");
      if (!key) {
        toast("集合标识不合法", "error");
        return true;
      }
      const response = await api.createCollection({ name: key, displayName });
      await loadCollections();
      await selectCollection(response.collection.name);
      toast(`已创建「${displayName}」`);
      return false;
    },
  });
  setTimeout(() => $("newDisplayName")?.focus(), 30);
}

function deleteCollection(name) {
  const info = state.collections.find((item) => item.name === name);
  openModal({
    title: "删除知识库",
    body: `<p>确定删除「${escapeHtml(info?.displayName || name)}」吗？其中的文档、向量和索引都会从 seekdb 中移除，无法撤销。</p>`,
    confirmText: "删除",
    danger: true,
    onConfirm: async () => {
      await api.deleteCollection(name);
      if (state.collection?.name === name) {
        const fallback = state.collections.find((item) => item.name !== name)?.name;
        await loadCollections();
        if (fallback) await selectCollection(fallback);
      } else {
        await loadCollections();
      }
      toast("集合已删除");
      return false;
    },
  });
}

function clearCollectionDialog() {
  if (!state.collection) return;
  openModal({
    title: "清空当前集合",
    body: `<p>将删除「${escapeHtml(state.collection.displayName)}」中的 ${formatInt.format(
      state.collection.chunkCount,
    )} 个分块并重建空集合。集合本身会保留。</p>`,
    confirmText: "清空",
    danger: true,
    onConfirm: async () => {
      await api.clearCollection(state.collection.name);
      await loadCollections();
      state.collection = (await api.collection(state.collection.name)).collection;
      state.lastImport = null;
      state.lastSearch = null;
      state.lastBenchmark = null;
      $("results").innerHTML = emptyStateMarkup();
      bindEmptyState();
      $("searchMeta").hidden = true;
      $("benchBody").innerHTML = benchPlaceholder();
      $("benchDownloadBtn").disabled = true;
      renderAll();
      toast("集合已清空");
      return false;
    },
  });
}

function openModal({ title, body, confirmText = "确定", danger = false, onConfirm }) {
  $("modalTitle").textContent = title;
  $("modalBody").innerHTML = body;
  $("modalConfirm").textContent = confirmText;
  $("modalConfirm").className = `btn ${danger ? "btn-secondary" : "btn-primary"}`;
  $("modalBackdrop").hidden = false;
  state.modalAction = onConfirm;
}

function closeModal() {
  $("modalBackdrop").hidden = true;
  state.modalAction = null;
  $("modalBody").innerHTML = "";
}

/* ------------------------------------------------------------------ ui utils */
function setBusy(busy) {
  $("importBtn").disabled = busy;
  $("sampleBtn").disabled = busy;
  $("searchBtn").disabled = busy;
  $("benchBtn").disabled = busy;
}

function setProgress(percent, label, detail) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  $("progressBar").style.width = `${value}%`;
  $("progressValue").textContent = `${Math.round(value)}%`;
  $("progressLabel").textContent = label;
  $("progressDetail").textContent = detail || "";
}

function logImport(label, value, cls = "") {
  const row = document.createElement("div");
  row.className = "log-line";
  row.innerHTML = `<strong>${escapeHtml(label)}</strong><span class="${cls}">${escapeHtml(value)}</span>`;
  $("importLog").append(row);
  while ($("importLog").children.length > 8) $("importLog").firstChild.remove();
}

function toast(message, type = "") {
  const element = $("toast");
  element.textContent = message;
  element.className = `toast show ${type === "error" ? "error" : ""}`;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    element.className = "toast";
  }, type === "error" ? 5200 : 3200);
}

function renderUnavailable() {
  $("currentTitle").textContent = "seekdb 未连接";
  $("currentMeta").textContent = "应用已启动，但数据库还没有就绪。";
  $("results").innerHTML = `<div class="no-hits">seekdb 未连接。请启动 seekdb 1.4 并监听 127.0.0.1:2881，然后刷新页面。<br/>Windows 请使用本地 server 模式；Linux/macOS 可设置 SEEKDB_MODE=embedded。</div>`;
  $("benchStatus").textContent = "数据库未连接，基准不可用。";
}

function emptyStateMarkup() {
  return `<div class="empty-state" id="emptyState">
    <div class="empty-mark">◌</div>
    <h3>还没有检索结果</h3>
    <p>先导入语料，再问一个具体的问题。所有 embedding 都在当前浏览器内计算。</p>
    <button id="emptySampleBtn" class="btn btn-ghost" type="button">载入 48 篇示例文档</button>
  </div>`;
}

function bindEmptyState() {
  $("emptySampleBtn")?.addEventListener("click", () => loadSample(false));
}

function benchPlaceholder() {
  return `<div class="bench-placeholder">
    <div class="bench-bars" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
    <p>运行后显示质量指标、P50/P95 延迟和逐条查询结果。</p>
  </div>`;
}

function showFatal(error) {
  console.error(error);
  $("dbDot").className = "status-dot bad";
  $("dbStatus").textContent = "初始化失败";
  $("dbVersion").textContent = error.message || "请检查服务端";
  toast(error.message || "初始化失败", "error");
}

function relativeTime(value) {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 10) return "刚刚";
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function mean(values) {
  const valid = values.filter((value) => Number.isFinite(value));
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : 0;
}

function mapRound(values) {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [
      key,
      Number.isFinite(value) ? round(value, 4) : value,
    ]),
  );
}

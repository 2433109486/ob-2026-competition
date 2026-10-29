import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const edge =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const base = process.env.BASE_URL || "http://127.0.0.1:5173";
const collection = `bench_opt_${Date.now().toString(36)}`;
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("pageerror", (error) => console.log("[pageerror]", String(error)));
try {
  await page.goto(`${base}/?backend=webgpu&dtype=fp16`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => window.__SEEKBASE__.ready);
  await page.evaluate(() => window.__SEEKBASE__.ensureModel());

  const batching = await page.evaluate(async () => {
    const corpus = await fetch("/seed/corpus.json", { cache: "no-store" }).then((r) => r.json());
    const texts = corpus.map((doc) => `${doc.title}\n${doc.text}`);
    await window.__SEEKBASE__.embedTexts(texts.slice(0, 8), 8, false);
    const rows = [];
    for (const batchSize of [1, 4, 8, 16, 32]) {
      const samples = [];
      for (let run = 0; run < 2; run += 1) {
        const result = await window.__SEEKBASE__.embedTexts(texts, batchSize, false);
        samples.push(result.ms);
      }
      const best = Math.min(...samples);
      rows.push({
        batchSize,
        texts: texts.length,
        ms: best,
        textsPerSecond: (texts.length * 1000) / best,
        samples,
      });
    }
    return { rows, backend: window.__SEEKBASE__.getState().embedding };
  });
  console.log("BATCHING", JSON.stringify(batching, null, 2));

  const refresh = await page.evaluate(async (collection) => {
    const corpus = await fetch("/seed/corpus.json", { cache: "no-store" }).then((r) => r.json());
    const docs = corpus.map((doc) => ({
      id: doc.id,
      docId: doc.id,
      title: doc.title,
      text: doc.text,
      chunkIndex: 0,
      source: doc.source,
      tags: doc.tags || [],
    }));
    const embedded = await window.__SEEKBASE__.embedTexts(
      docs.map((doc) => `${doc.title}\n${doc.text}`),
      8,
      true,
    );
    const vectors = embedded.vectors;

    async function create() {
      await fetch(`/api/collections/${encodeURIComponent(collection)}`, { method: "DELETE" });
      const response = await fetch("/api/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: collection, displayName: "optimization" }),
      });
      if (!response.ok) throw new Error(await response.text());
    }

    async function importAll(refreshEveryBatch) {
      let writeMs = 0;
      let refreshMs = 0;
      let refreshes = 0;
      const wallStart = performance.now();
      for (let start = 0; start < docs.length; start += 8) {
        const end = Math.min(start + 8, docs.length);
        const isLast = end === docs.length;
        const response = await fetch("/api/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            collection,
            documents: docs.slice(start, end),
            embeddings: vectors.slice(start, end),
            model: "bge-small-zh-v1.5",
            dtype: "fp16",
            refresh: refreshEveryBatch || isLast,
          }),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(JSON.stringify(body));
        writeMs += Number(body.writeMs || 0);
        refreshMs += Number(body.refreshMs || 0);
        if (refreshEveryBatch || isLast) refreshes += 1;
      }
      return {
        wallMs: performance.now() - wallStart,
        writeMs,
        refreshMs,
        refreshes,
        chunks: docs.length,
      };
    }

    await create();
    const perBatch = await importAll(true);
    await create();
    const once = await importAll(false);
    await fetch(`/api/collections/${encodeURIComponent(collection)}`, { method: "DELETE" });
    return { perBatch, once, embeddingMs: embedded.ms };
  }, collection);
  console.log("REFRESH", JSON.stringify(refresh, null, 2));

  const out = { capturedAt: new Date().toISOString(), batching, refresh };
  fs.mkdirSync("runtime/results", { recursive: true });
  fs.writeFileSync(path.join("runtime/results", "optimization.json"), JSON.stringify(out, null, 2));
} finally {
  await browser.close();
}

import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const edge =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const base = process.env.BASE_URL || "http://127.0.0.1:5173";
const configs = [
  { name: "int8-wasm", collection: "bench_int8_wasm", backend: "wasm", dtype: "q8" },
  { name: "fp32-wasm", collection: "bench_fp32_wasm", backend: "wasm", dtype: "fp32" },
  { name: "fp16-webgpu", collection: "bench_fp16_webgpu", backend: "webgpu", dtype: "fp16" },
  { name: "fp32-webgpu", collection: "bench_fp32_webgpu", backend: "webgpu", dtype: "fp32" },
];
const outDir = path.resolve("runtime/results");
fs.mkdirSync(outDir, { recursive: true });
const runSuffix = process.env.RUN_SUFFIX ? `-${process.env.RUN_SUFFIX}` : "";
const only = process.env.ONLY ? process.env.ONLY.split(",") : null;
const browser = await chromium.launch({
  executablePath: edge,
  headless: process.env.HEADFUL !== "1",
  args: ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
});

for (const config of configs) {
  if (only && !only.includes(config.name)) continue;
  console.log(`\n=== ${config.name} ===`);
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("favicon") && !msg.text().includes("onnxruntime")) {
      console.log("[console]", msg.text().slice(0, 300));
    }
  });
  try {
    await page.goto(`${base}/?backend=${config.backend}&dtype=${config.dtype}`, {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await page.evaluate(() => window.__SEEKBASE__.ready);
    const setup = await page.evaluate(async (config) => {
      const deleteResponse = await fetch(`/api/collections/${encodeURIComponent(config.collection)}`, {
        method: "DELETE",
      });
      if (!deleteResponse.ok && deleteResponse.status !== 404) {
        // Default collections cannot be deleted; this is a benchmark-only name.
      }
      const createResponse = await fetch("/api/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: config.collection, displayName: config.name }),
      });
      if (!createResponse.ok) {
        const body = await createResponse.text();
        throw new Error(`create collection failed: ${createResponse.status} ${body}`);
      }
      await window.__SEEKBASE__.switchCollection(config.collection);
      document.getElementById("backendSelect").value = config.backend;
      document.getElementById("dtypeSelect").value = config.dtype;
      document.getElementById("batchSize").value = "16";
      return window.__SEEKBASE__.getState().collection;
    }, config);
    console.log("collection", setup.name, setup.docCount);

    const imported = await page.evaluate(async () => {
      await window.__SEEKBASE__.importSample(true);
      return window.__SEEKBASE__.getState().lastImport;
    });
    console.log("import", JSON.stringify(imported));

    const bench = await page.evaluate(async () => {
      await window.__SEEKBASE__.benchmark();
      return window.__SEEKBASE__.getState().lastBenchmark;
    });
    const result = {
      config,
      imported,
      benchmark: bench,
      errors,
      capturedAt: new Date().toISOString(),
    };
    fs.writeFileSync(
      path.join(outDir, `${config.name}${runSuffix}.json`),
      JSON.stringify(result, null, 2),
    );
    console.log(
      "bench",
      JSON.stringify({
        quality: bench?.quality,
        latency: bench?.latency,
        model: bench?.model,
        backend: bench?.backend,
      }),
    );
    await page.screenshot({ path: `runtime/screens/bench-${config.name}.png`, fullPage: true });
  } catch (error) {
    console.error("FAILED", error);
    fs.writeFileSync(
      path.join(outDir, `${config.name}${runSuffix}-error.txt`),
      `${error?.stack || error}\n${errors.join("\n")}`,
    );
  } finally {
    await page.close();
  }
}
await browser.close();

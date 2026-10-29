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
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
});
for (const config of configs) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const runs = [];
  try {
    await page.goto(`${base}/?backend=${config.backend}&dtype=${config.dtype}`, {
      waitUntil: "domcontentloaded",
    });
    await page.evaluate(() => window.__SEEKBASE__.ready);
    await page.evaluate(async (config) => {
      await window.__SEEKBASE__.switchCollection(config.collection);
      document.getElementById("backendSelect").value = config.backend;
      document.getElementById("dtypeSelect").value = config.dtype;
      document.getElementById("batchSize").value = "16";
    }, config);
    for (let i = 0; i < 3; i += 1) {
      const result = await page.evaluate(async () => {
        await window.__SEEKBASE__.benchmark();
        return window.__SEEKBASE__.getState().lastBenchmark;
      });
      runs.push({
        quality: result.quality,
        latency: result.latency,
        backend: result.backend.actual,
        dtype: result.model.dtype,
      });
      console.log(config.name, i + 1, JSON.stringify(result.quality), JSON.stringify(result.latency));
    }
    fs.writeFileSync(path.join(outDir, `repeat-${config.name}.json`), JSON.stringify({ config, runs }, null, 2));
  } catch (error) {
    console.error(config.name, "FAILED", error);
  } finally {
    await page.close();
  }
}
await browser.close();

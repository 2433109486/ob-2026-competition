import { chromium } from "playwright-core";

const edge =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const base = process.env.BASE_URL || "http://127.0.0.1:5173";
const backend = process.env.BACKEND || "wasm";
const mode = process.env.MODE || "smoke";

const browser = await chromium.launch({
  executablePath: edge,
  headless: process.env.HEADFUL !== "1",
  args: ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on("console", (msg) => {
  const text = msg.text();
  if (msg.type() === "error" && !text.includes("favicon")) console.log("[console]", text);
});
page.on("pageerror", (error) => {
  errors.push(String(error));
  console.log("[pageerror]", String(error));
});

try {
  await page.goto(`${base}/?backend=${backend}`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.evaluate(() => window.__SEEKBASE__.ready);
  console.log("STATE", JSON.stringify(await page.evaluate(() => {
    const s = window.__SEEKBASE__.getState();
    return { collection: s.collection, health: s.health, collections: s.collections.length };
  })));
  await page.screenshot({ path: `runtime/screens/01-home-${backend}.png`, fullPage: true });

  if (mode === "import" || mode === "full") {
    console.log("IMPORTING SAMPLE...");
    const result = await page.evaluate(async () => {
      await window.__SEEKBASE__.importSample(true);
      return window.__SEEKBASE__.getState().lastImport;
    });
    console.log("IMPORT", JSON.stringify(result));
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `runtime/screens/02-imported-${backend}.png`, fullPage: true });
  }

  if (mode === "search" || mode === "full") {
    console.log("SEARCHING...");
    const result = await page.evaluate(async () => {
      await window.__SEEKBASE__.search("新写入的数据检索不到 如何刷新索引");
      await new Promise((r) => setTimeout(r, 300));
      return {
        state: window.__SEEKBASE__.getState().lastSearch,
        cards: document.querySelectorAll(".result-card").length,
        meta: document.getElementById("searchMeta")?.innerText,
      };
    });
    console.log("SEARCH", JSON.stringify(result).slice(0, 4000));
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `runtime/screens/03-search-${backend}.png`, fullPage: true });
  }

  if (mode === "bench" || mode === "full") {
    console.log("BENCHMARKING...");
    const result = await page.evaluate(async () => {
      await window.__SEEKBASE__.benchmark();
      return window.__SEEKBASE__.getState().lastBenchmark;
    });
    console.log("BENCH", JSON.stringify(result ? {
      quality: result.quality,
      latency: result.latency,
      backend: result.backend,
      model: result.model,
      queries: result.queries,
    } : null));
    await page.waitForTimeout(3800);
    await page.screenshot({ path: `runtime/screens/04-bench-${backend}.png`, fullPage: true });
  }
  console.log("ERRORS", errors.length, errors.slice(0, 3));
} finally {
  await browser.close();
}

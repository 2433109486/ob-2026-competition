import { chromium } from "playwright-core";

const edge =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const base = process.env.BASE_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  // Disable hardware acceleration so navigator.gpu exposes no adapter. This
  // emulates a machine whose browser cannot use WebGPU.
  args: ["--disable-gpu", "--disable-software-rasterizer"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("pageerror", (error) => console.log("[pageerror]", String(error)));
try {
  await page.goto(`${base}/?backend=auto`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => window.__SEEKBASE__.ready);
  const before = await page.evaluate(() => ({
    gpu: Boolean(navigator.gpu),
    state: window.__SEEKBASE__.getState().health,
  }));
  console.log("BEFORE", JSON.stringify(before));
  const result = await page.evaluate(async () => {
    await window.__SEEKBASE__.search("索引刷新");
    return {
      embedding: window.__SEEKBASE__.getState().embedding,
      search: window.__SEEKBASE__.getState().lastSearch,
      badge: document.getElementById("backendBadge")?.innerText,
      meta: document.getElementById("backendCardBody")?.innerText,
    };
  });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "runtime/screens/05-fallback-wasm.png", fullPage: true });
  console.log(
    "AFTER",
    JSON.stringify({
      device: result.embedding?.device,
      dtype: result.embedding?.dtype,
      fallback: result.embedding?.fallbackReason,
      badge: result.badge,
      hits: result.search?.hits?.length,
      meta: result.meta,
    }),
  );
} finally {
  await browser.close();
}

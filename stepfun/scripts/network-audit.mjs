import { chromium } from "playwright-core";

const edge =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const base = process.env.BASE_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage();
const urls = new Set();
const external = new Set();
page.on("request", (request) => {
  const url = request.url();
  urls.add(url);
  try {
    const host = new URL(url).hostname;
    if (!["127.0.0.1", "localhost", "::1"].includes(host)) external.add(url);
  } catch {
    external.add(url);
  }
});
try {
  await page.goto(`${base}/?backend=auto`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => window.__SEEKBASE__.ready);
  await page.evaluate(async () => {
    await window.__SEEKBASE__.search("索引刷新");
  });
  await page.waitForTimeout(1500);
  console.log(
    JSON.stringify(
      {
        requestCount: urls.size,
        externalRequests: [...external],
        hosts: [...new Set([...urls].map((url) => new URL(url).host))],
        sample: [...urls].slice(0, 12),
      },
      null,
      2,
    ),
  );
  process.exitCode = external.size ? 1 : 0;
} finally {
  await browser.close();
}

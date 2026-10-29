import { chromium } from "playwright-core";

const edge =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const base = process.env.BASE_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
});
const vectors = [];
for (let run = 0; run < 2; run += 1) {
  const page = await browser.newPage();
  await page.goto(`${base}/?backend=webgpu&dtype=fp16`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => window.__SEEKBASE__.ready);
  const result = await page.evaluate(async () => {
    const corpus = await fetch("/seed/corpus.json", { cache: "no-store" }).then((r) => r.json());
    const texts = corpus.slice(0, 8).map((doc) => `${doc.title}\n${doc.text}`);
    const out = await window.__SEEKBASE__.embedTexts(texts, 16, true);
    return out.vectors;
  });
  vectors.push(result);
  await page.close();
}
function cosine(a, b) {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i += 1) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / Math.sqrt(na * nb);
}
const sims = vectors[0].map((vec, i) => cosine(vec, vectors[1][i]));
console.log(JSON.stringify({ sims, min: Math.min(...sims), max: Math.max(...sims) }, null, 2));
await browser.close();

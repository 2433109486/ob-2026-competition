#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MODEL_DIR = path.join(ROOT, "web", "models", "bge-small-zh-v1.5");
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "web", "models", "manifest.json"), "utf8"));
const endpoint = (process.env.HF_ENDPOINT || "https://hf-mirror.com").replace(/\/$/, "");
const args = new Set(process.argv.slice(2));
const includeFp32 = args.has("--all");
const checkOnly = args.has("--check");
const force = args.has("--force");

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

async function download(file) {
  const dest = path.join(MODEL_DIR, file.path);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const url = `${endpoint}/${manifest.model}/resolve/${manifest.revision}/${file.path}`;
  console.log(`[fetch] ${path.basename(file.path)} (${(file.bytes / 1024 / 1024).toFixed(1)} MiB)`);
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  const temp = `${dest}.part`;
  const buffer = Buffer.from(await response.arrayBuffer());
  fs.writeFileSync(temp, buffer);
  if (buffer.length !== file.bytes) {
    fs.rmSync(temp, { force: true });
    throw new Error(`size mismatch for ${file.path}: got ${buffer.length}, expected ${file.bytes}`);
  }
  fs.renameSync(temp, dest);
  const hash = sha256(dest);
  if (hash !== file.sha256) {
    throw new Error(`sha256 mismatch for ${file.path}: got ${hash}, expected ${file.sha256}`);
  }
}

for (const file of manifest.files) {
  if (!file.required && !includeFp32) continue;
  const dest = path.join(MODEL_DIR, file.path);
  const exists = fs.existsSync(dest);
  if (exists) {
    const size = fs.statSync(dest).size;
    if (size === file.bytes) {
      console.log(`[ok] ${file.path} ${(size / 1024 / 1024).toFixed(2)} MiB`);
      continue;
    }
    console.log(`[warn] ${file.path} size ${size} != ${file.bytes}`);
  }
  if (checkOnly) {
    console.error(`[missing] ${file.path}`);
    process.exitCode = 1;
    continue;
  }
  if (exists && !force) {
    console.log(`[skip] ${file.path} exists but size differs; use --force to redownload`);
    process.exitCode = 1;
    continue;
  }
  await download(file);
  console.log(`[done] ${file.path}`);
}

const total = manifest.files
  .filter((file) => file.required || includeFp32)
  .reduce((sum, file) => sum + file.bytes, 0);
console.log(`[fetch] selected files total: ${(total / 1024 / 1024).toFixed(2)} MiB`);
console.log(`[fetch] model directory: ${MODEL_DIR}`);
console.log(`[fetch] source: ${manifest.source} @ ${manifest.revision}`);

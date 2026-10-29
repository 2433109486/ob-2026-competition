"""Record a short, real walkthrough video of the running app."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\agent\sandbox\pylibs\playwright_pkg")
from playwright.sync_api import sync_playwright  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://127.0.0.1:7860"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "demo"
OUT.mkdir(parents=True, exist_ok=True)


def caption(page, text: str) -> None:
    page.evaluate(
        """(text) => {
            let node = document.getElementById('demo-caption');
            if (!node) {
                node = document.createElement('div');
                node.id = 'demo-caption';
                node.style.cssText = [
                    'position:fixed','left:50%','bottom:26px','transform:translateX(-50%)',
                    'z-index:9999','padding:10px 18px','border-radius:10px',
                    'background:rgba(29,42,37,.94)','color:#fffaf0',
                    'font:600 13px/1.5 "Noto Sans SC","Microsoft YaHei",sans-serif',
                    'letter-spacing:.02em','box-shadow:0 16px 36px -20px rgba(0,0,0,.7)',
                    'border:1px solid rgba(255,255,255,.16)','pointer-events:none'
                ].join(';');
                document.body.appendChild(node);
            }
            node.textContent = text;
        }""",
        text,
    )


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EDGE, headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=str(OUT / "_raw"),
            record_video_size={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto(f"{BASE}/#/today", wait_until="networkidle")
        page.wait_for_timeout(700)
        caption(page, "研脉 ResearchPulse · 把文献、证据和研究判断连成一条路径")
        page.wait_for_timeout(2800)

        page.goto(f"{BASE}/#/search", wait_until="networkidle")
        caption(page, "检索一个真正卡住你的问题")
        page.fill("#search-input", "AI 编程助手对初学者学习迁移的影响")
        page.wait_for_timeout(700)
        page.press("#search-input", "Enter")
        page.wait_for_selector(".result-card", timeout=15000)
        page.wait_for_timeout(2500)
        caption(page, "向量 + 全文双路召回；每条结果都有原文片段、融合分与命中理由")
        page.wait_for_timeout(2600)

        page.locator("[data-action='open-trace']").click()
        page.wait_for_selector(".trace-card", timeout=10000)
        page.wait_for_timeout(600)
        caption(page, "每次检索都能回看 seekdb 实际执行的 SQL 和候选数")
        page.wait_for_timeout(2800)
        page.locator(".modal .drawer-close").click()
        page.wait_for_timeout(300)

        page.locator(".result-title").first.click()
        page.wait_for_selector(".drawer", timeout=10000)
        page.locator("[data-action='drawer-tab'][data-tab='evidence']").click()
        page.wait_for_timeout(500)
        caption(page, "点回证据片段：章节、页码和原文，不靠模型复述")
        page.wait_for_timeout(2800)
        page.locator(".drawer-close").click()
        page.wait_for_timeout(300)

        page.goto(f"{BASE}/#/review", wait_until="networkidle")
        page.wait_for_timeout(800)
        if page.locator(".matrix-table").count() == 0:
            page.locator(".page-head-actions [data-action='generate-review']").click()
            page.wait_for_selector(".matrix-table", timeout=15000)
        page.wait_for_timeout(700)
        caption(page, "把选中的文献压成 6 维矩阵，再生成带引用编号的综述草稿")
        page.wait_for_timeout(3200)
        page.evaluate("window.scrollTo({top: 480, behavior: 'smooth'})")
        page.wait_for_timeout(1800)

        page.goto(f"{BASE}/#/memory", wait_until="networkidle")
        page.wait_for_timeout(900)
        caption(page, "研究画像、阅读进度、综述选择，都通过 PowerContext 跨会话保留")
        page.wait_for_timeout(3000)
        page.fill("#recall-query", "学习迁移")
        page.press("#recall-query", "Enter")
        page.wait_for_timeout(1200)
        caption(page, "下一次检索，不用重新讲一遍你是谁")
        page.wait_for_timeout(2200)

        video = page.video
        context.close()
        if video:
            import shutil

            target = OUT / "demo.webm"
            shutil.copyfile(video.path(), target)
            print(f"video: {target} ({target.stat().st_size} bytes)")
        else:
            print("no video recorded")
        try:
            browser.close()
        except Exception as exc:  # noqa: BLE001
            print("browser shutdown warning:", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

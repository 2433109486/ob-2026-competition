"""Capture real screenshots of the running app with Playwright + local Edge."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, r"D:\agent\sandbox\pylibs\playwright_pkg")
from playwright.sync_api import sync_playwright  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://127.0.0.1:7860"
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=EDGE,
            headless=True,
            args=["--no-sandbox", "--disable-gpu"],
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on("console", lambda msg: errors.append(f"console {msg.type}: {msg.text}") if msg.type == "error" else None)

        page.goto(f"{BASE}/#/today", wait_until="networkidle")
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / "00-hero.png"), full_page=False)
        page.screenshot(path=str(OUT / "01-today.png"), full_page=True)
        print("today", page.title(), page.locator(".stat-card").count())

        page.goto(f"{BASE}/#/search", wait_until="networkidle")
        page.fill("#search-input", "AI 编程助手对初学者学习迁移的影响")
        page.press("#search-input", "Enter")
        page.wait_for_selector(".result-card", timeout=15000)
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "02-search.png"), full_page=True)
        print("search results", page.locator(".result-card").count())

        page.locator("[data-action='open-trace']").click()
        page.wait_for_selector(".trace-card", timeout=10000)
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "08-trace.png"), full_page=False)
        page.locator(".modal .drawer-close").click()
        page.wait_for_timeout(300)

        page.locator(".result-title").first.click()
        page.wait_for_selector(".drawer", timeout=10000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "03-paper-drawer.png"), full_page=False)
        print("active nav", page.locator(".nav-item.active").inner_text())
        page.locator(".drawer-close").click()

        page.goto(f"{BASE}/#/library", wait_until="networkidle")
        page.wait_for_selector(".paper-card", timeout=15000)
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "04-library.png"), full_page=True)
        print("papers", page.locator(".paper-card").count())

        page.goto(f"{BASE}/#/review", wait_until="networkidle")
        page.wait_for_timeout(900)
        page.locator(".page-head-actions [data-action='generate-review']").click()
        page.wait_for_selector(".matrix-table", timeout=15000)
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "05-review.png"), full_page=True)
        print("matrix rows", page.locator(".matrix-table tbody tr").count())

        page.goto(f"{BASE}/#/memory", wait_until="networkidle")
        page.wait_for_timeout(4200)
        page.evaluate("document.querySelectorAll('.toast').forEach((node) => node.remove())")
        page.screenshot(path=str(OUT / "06-memory.png"), full_page=True)
        print("memory items", page.locator(".memory-item").count())

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        mpage = mobile.new_page()
        mpage.goto(f"{BASE}/#/today", wait_until="networkidle")
        mpage.wait_for_timeout(700)
        mpage.screenshot(path=str(OUT / "07-mobile-today.png"), full_page=True)
        print("mobile title", mpage.title())

        browser.close()

    if errors:
        print("\nBROWSER ERRORS:")
        for error in errors[:30]:
            print(" -", error)
    else:
        print("\nNo browser errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

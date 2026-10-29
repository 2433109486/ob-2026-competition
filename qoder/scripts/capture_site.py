"""Render the static Qoder Sites page and check that all media loads."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\agent\sandbox\pylibs\playwright_pkg")
from playwright.sync_api import sync_playwright  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://127.0.0.1:7861"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EDGE, headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1200)
        broken = page.evaluate(
            """() => [...document.images].filter((img) => !img.complete || img.naturalWidth === 0).map((img) => img.getAttribute('src'))"""
        )
        print("images", page.locator("img").count(), "broken", broken)
        print("sections", page.locator("section").count(), "videos", page.locator("video").count())
        print("title", page.title())
        page.screenshot(path=str(OUT / "09-site-hero.png"), full_page=False)
        page.screenshot(path=str(OUT / "10-site-full.png"), full_page=True)

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        mobile.goto(BASE, wait_until="networkidle")
        mobile.wait_for_timeout(600)
        mobile.screenshot(path=str(OUT / "11-site-mobile.png"), full_page=True)
        print("mobile scroll width", mobile.evaluate("document.documentElement.scrollWidth"))
        browser.close()
    if broken:
        return 1
    if errors:
        print("errors:", errors)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

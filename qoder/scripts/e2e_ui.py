"""Browser-level smoke test of the main interaction paths."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\agent\sandbox\pylibs\playwright_pkg")
from playwright.sync_api import sync_playwright  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://127.0.0.1:7860"


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EDGE, headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        page.goto(f"{BASE}/#/search", wait_until="networkidle")
        page.fill("#search-input", "怎么避免学生直接抄答案")
        page.press("#search-input", "Enter")
        page.wait_for_selector(".result-card")
        assert page.locator(".result-card").count() >= 3
        assert "没有护栏" in page.locator(".result-title").first.inner_text()
        print("[OK] search ranks the guardrail paper first")

        page.locator(".result-title").first.click()
        page.wait_for_selector(".drawer")
        assert page.locator(".drawer-title").inner_text()
        page.locator("[data-action='drawer-tab'][data-tab='evidence']").click()
        assert page.locator(".chunk-card").count() >= 2
        page.locator(".drawer-close").click()
        print("[OK] paper drawer and evidence tab")

        page.goto(f"{BASE}/#/review", wait_until="networkidle")
        page.wait_for_timeout(600)
        if page.locator(".matrix-table").count() == 0:
            page.locator(".page-head-actions [data-action='generate-review']").click()
            page.wait_for_selector(".matrix-table")
        assert page.locator(".matrix-table tbody tr").count() >= 2
        assert page.locator(".matrix-table thead th").count() == 7
        with page.expect_download() as download_info:
            page.locator("[data-action='export-review']").click()
        download = download_info.value
        assert download.suggested_filename.endswith(".md")
        print("[OK] matrix + Markdown download")

        page.goto(f"{BASE}/#/memory", wait_until="networkidle")
        page.wait_for_timeout(500)
        assert page.locator(".memory-item").count() >= 4
        page.fill("#recall-query", "学习迁移")
        page.press("#recall-query", "Enter")
        page.wait_for_selector(".recall-hit b", timeout=10000)
        recall_text = page.locator(".recall-hit").first.inner_text()
        print("recall:", recall_text[:120].replace("\n", " / "))
        assert len(recall_text) > 10
        page.locator("[data-action='open-profile']").first.click()
        page.wait_for_selector("#profile-form")
        page.locator("[data-action='close-modal']").last.click()
        print("[OK] memory recall + profile modal")

        page.goto(f"{BASE}/#/library", wait_until="networkidle")
        page.wait_for_selector(".paper-card")
        page.locator(".paper-check").first.click()
        assert page.locator(".selection-bar").count() == 1
        page.locator("[data-action='clear-library-selection']").click()
        assert page.locator(".selection-bar").count() == 0
        print("[OK] library selection bar")

        try:
            context.close()
            browser.close()
        except Exception as exc:  # noqa: BLE001 - Edge occasionally drops the driver on shutdown
            print("browser shutdown warning:", exc)

    if errors:
        print("BROWSER ERRORS:")
        for error in errors:
            print(" -", error)
        return 1
    print("PASS: UI interactions, no browser errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

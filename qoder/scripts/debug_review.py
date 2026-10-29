import sys
from pathlib import Path

sys.path.insert(0, r"D:\agent\sandbox\pylibs\playwright_pkg")
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto("http://127.0.0.1:7860/#/review", wait_until="networkidle")
    page.wait_for_timeout(800)
    print("before", page.evaluate("({selected:[...window.__yanmai.reviewSelected], papers:window.__yanmai.reviewPapers.map(p=>p.paper_id), active:[...document.querySelectorAll('.select-item.active')].map(e=>e.dataset.paperId)})"))
    page.locator(".page-head-actions [data-action='generate-review']").click()
    page.wait_for_selector(".matrix-table")
    page.wait_for_timeout(500)
    print("after", page.evaluate("({selected:[...window.__yanmai.reviewSelected], rows:window.__yanmai.review.matrix.rows.map(r=>r.paper_id), active:[...document.querySelectorAll('.select-item.active')].map(e=>e.dataset.paperId), checks:[...document.querySelectorAll('.select-item')].filter(e=>e.querySelector('.paper-check')).map(e=>({id:e.dataset.paperId, active:e.classList.contains('active')}))})"))
    browser.close()


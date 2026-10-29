import json
import urllib.error
import urllib.request

scope = open("runtime/powercontext_scope.txt", encoding="utf-8").read().strip()
for mode in ["text", "fts", "hybrid"]:
    payload = {"scope_id": scope, "query": "主终点 延迟迁移", "mode": mode, "limit": 6}
    req = urllib.request.Request(
        "http://127.0.0.1:8765/v1/memory/search",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(mode, resp.status, resp.read().decode()[:800])
    except urllib.error.HTTPError as error:
        print(mode, error.code, error.read().decode()[:1200])

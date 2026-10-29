import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_both_services(client):
    data = client.get("/api/health").json()
    assert data["seekdb"]["ok"] is True
    assert data["powercontext"]["ok"] is True
    assert data["embedding"]["dimension"] == 768


def test_bootstrap_has_demo_data_and_memory(client):
    data = client.get("/api/bootstrap").json()
    assert data["counts"]["papers"] >= 10
    assert data["memory_available"] is True
    assert data["profile"]["name"] == "林然"
    assert data["continue_reading"]


def test_hybrid_search_returns_trace_and_evidence(client):
    response = client.post(
        "/api/search",
        json={"query": "AI 编程助手对初学者学习迁移的影响", "limit": 6},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 4
    assert data["counts"]["vector_candidates"] > 0
    assert data["counts"]["text_candidates"] > 0
    assert len(data["trace"]) == 2
    assert data["results"][0]["best_chunk"]["snippet"]
    assert data["memory"]["available"] is True


def test_review_matrix_and_markdown_export(client):
    payload = {
        "paper_ids": ["kazemitabaar2023", "bastani2025", "prather2023", "denny2024"],
        "question": "生成式 AI 编程助手如何影响初学者的编程学习与迁移？",
        "remember": False,
    }
    response = client.post("/api/review/matrix", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["matrix"]["paper_count"] == 4
    assert len(data["matrix"]["columns"]) == 6
    assert data["matrix"]["empirical_count"] == 2
    assert len(data["draft"]["citations"]) == 4
    assert "## 参考文献" in data["draft"]["markdown"]

    export = client.post("/api/review/export", json=payload)
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/markdown")
    assert "yanmai-review-draft.md" in export.headers["content-disposition"]


def test_memory_endpoint_has_atomic_entries(client):
    data = client.get("/api/memory").json()
    assert data["available"] is True
    assert data["scope_id"]
    assert len(data["timeline"]) >= 4
    assert any(item["kind"] == "research_profile" for item in data["timeline"])

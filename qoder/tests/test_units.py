from app.embeddings import cosine, embed_text
from app.review import build_matrix


def test_embedding_is_deterministic_and_related_is_closer():
    query = embed_text("AI 编程助手 初学者 学习迁移")
    related = embed_text("生成式 AI 辅助编程学习，关注初学者的延迟迁移")
    unrelated = embed_text("海洋数据库的分布式事务和日志复制")
    assert query == embed_text("AI 编程助手 初学者 学习迁移")
    assert cosine(query, related) > cosine(query, unrelated)


def test_matrix_has_six_columns_and_surfaces_gaps():
    papers = [
        {
            "paper_id": "p1",
            "title": "Paper one",
            "authors": "A",
            "year": 2024,
            "review_problem": "AI 是否促进学习迁移？",
            "review_method": "随机对照实验",
            "review_sample": "100 名初学者",
            "review_finding": "延迟后测没有显著提升",
            "review_limitation": "样本较小",
            "review_reuse": "",
            "tags": ["实证研究"],
        }
    ]
    matrix = build_matrix(papers, "AI 与学习")
    assert len(matrix["columns"]) == 6
    assert matrix["rows"][0]["cells"]["problem"]
    assert any(gap["column"] == "reuse" for gap in matrix["gaps"])
    assert matrix["coverage"] < 100

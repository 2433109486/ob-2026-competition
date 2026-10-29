from app.bibtex import paper_to_bibtex
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


def test_bibtex_contains_required_fields():
    paper = {
        "paper_id": "kazemitabaar2023",
        "title": "AI 代码生成器如何支持编程入门学习者",
        "title_en": "Studying the Effect of AI Code Generators",
        "authors": "Majeed Kazemitabaar, Justin Chow",
        "year": 2023,
        "venue": "CHI 2023",
        "doi": "10.1145/3544548.3580919",
        "url": "https://arxiv.org/abs/2302.07427",
        "abstract": "研究用随机分组实验考察 OpenAI Codex 对初学者的影响。",
        "tags": ["生成式AI", "编程教育"],
        "source_type": "paper",
    }
    bib = paper_to_bibtex(paper)
    assert bib.startswith("@inproceedings{")
    assert "kazemitabaar2023" in bib
    assert "title = {" in bib
    assert "author = {" in bib
    assert "year = 2023" in bib
    assert "doi = {" in bib
    assert "10.1145/3544548.3580919" in bib


def test_bibtex_escapes_special_characters():
    paper = {
        "paper_id": "test2024",
        "title": "A Study of AI & ML",
        "authors": "Test Author",
        "year": 2024,
        "venue": "Proceedings of the 10%",
        "doi": "",
        "url": "",
        "abstract": "Uses $100 and #tags",
        "tags": [],
        "source_type": "paper",
    }
    bib = paper_to_bibtex(paper)
    assert r"\&" in bib
    assert r"\%" in bib
    assert r"\$" in bib
    assert r"\#" in bib


def test_bibtex_note_uses_misc_entry_type():
    paper = {
        "paper_id": "meeting2026",
        "title": "组会纪要",
        "authors": "内部",
        "year": 2026,
        "venue": "",
        "doi": "",
        "url": "",
        "abstract": "",
        "tags": [],
        "source_type": "note",
    }
    bib = paper_to_bibtex(paper)
    assert bib.startswith("@misc{")

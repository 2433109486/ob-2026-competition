"""Deterministic BibTeX generation from paper metadata."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict


def _latex_escape(value: str) -> str:
    # Protect the backslash first: escaping braces after inserting
    # ``\textbackslash{}`` would corrupt that command.
    marker = "\x00BACKSLASH\x00"
    value = value.replace("\\", marker)
    for char, replacement in [
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]:
        value = value.replace(char, replacement)
    return value.replace(marker, r"\textbackslash{}")


def _make_cite_key(paper: Dict[str, Any]) -> str:
    authors = str(paper.get("authors", "")).strip()
    year = str(paper.get("year", ""))
    if authors:
        first_author = authors.split(",")[0].strip().split(" and ")[0].strip()
        parts = first_author.split()
        last_name = parts[-1] if parts else "unknown"
        last_name = re.sub(r"[^a-zA-Z]", "", last_name) or "unknown"
    else:
        last_name = "unknown"
    key = f"{last_name.lower()}{year}"
    title = str(paper.get("title", "")).strip()
    if title:
        ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
        words = re.findall(r"[A-Za-z]+", ascii_title)
        for word in words:
            lower = word.lower()
            if lower not in {"the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "with", "is", "are"}:
                key += lower[:3]
                break
    return key


def _format_authors(authors: str) -> str:
    authors = authors.strip()
    if not authors:
        return ""
    if " and " in authors:
        return authors
    parts = [p.strip() for p in authors.split(",") if p.strip()]
    if len(parts) == 1:
        return parts[0]
    return " and ".join(parts)


def _entry_type(paper: Dict[str, Any]) -> str:
    source_type = str(paper.get("source_type", "paper")).strip().lower()
    if source_type == "note":
        return "misc"
    venue = str(paper.get("venue", "")).strip().lower()
    if any(token in venue for token in ["conference", "proceedings", "symposium", "chi", "cscw", "uist"]):
        return "inproceedings"
    if any(token in venue for token in ["journal", "cacm", "pnas", "tse", "tochi"]):
        return "article"
    if any(token in venue for token in ["arxiv", "preprint", "report"]):
        return "techreport"
    return "article"


def _bibtex_field(value: str, brace: bool = True) -> str:
    value = value.strip()
    if not value:
        return ""
    escaped = _latex_escape(value)
    if brace:
        return f"{{{escaped}}}"
    return f'"{escaped}"'


def paper_to_bibtex(paper: Dict[str, Any]) -> str:
    cite_key = _make_cite_key(paper)
    entry_type = _entry_type(paper)

    fields = []
    title = str(paper.get("title_en") or paper.get("title", "")).strip()
    if title:
        fields.append(f"  title = {_bibtex_field(title)}")

    authors = _format_authors(str(paper.get("authors", "")))
    if authors:
        fields.append(f"  author = {_bibtex_field(authors)}")

    year = str(paper.get("year", "")).strip()
    if year:
        fields.append(f"  year = {year}")

    venue = str(paper.get("venue", "")).strip()
    if venue:
        if entry_type == "inproceedings":
            fields.append(f"  booktitle = {_bibtex_field(venue)}")
        elif entry_type == "techreport":
            fields.append(f"  institution = {_bibtex_field(venue)}")
        elif entry_type == "misc":
            fields.append(f"  howpublished = {_bibtex_field(venue)}")
        else:
            fields.append(f"  journal = {_bibtex_field(venue)}")

    doi = str(paper.get("doi", "")).strip()
    if doi:
        fields.append(f"  doi = {_bibtex_field(doi)}")

    url = str(paper.get("url", "")).strip()
    if url:
        fields.append(f"  url = {_bibtex_field(url)}")

    abstract = str(paper.get("abstract", "")).strip()
    if abstract:
        fields.append(f"  abstract = {_bibtex_field(abstract)}")

    tags = paper.get("tags", [])
    if isinstance(tags, list):
        keywords = ", ".join(tags)
    else:
        keywords = str(tags or "").strip().replace(",", ", ")
    if keywords.strip(", "):
        fields.append(f"  keywords = {_bibtex_field(keywords.strip(', '))}")

    fields.append(f"  type = {entry_type}")

    body = ",\n".join(fields)
    return f"@{entry_type}{{{cite_key},\n{body}\n}}\n"

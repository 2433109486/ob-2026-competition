# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Full physical-page PDF parsing with page-level evidence retrieval."""

from __future__ import annotations

import hashlib
import io
import math
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:  # pragma: no cover - typing-only to avoid an import cycle
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"
_WORD = re.compile(r"[a-z]+|\d+")


class PDFDocumentInput(BaseModel):
    """One complete PDF document as raw bytes."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page of a PDF document."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured PDF page that keeps the file revision and physical page."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def _require_document_id(document_id: object) -> str:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")
    return document_id


def _read_pages(content: bytes) -> list[str]:
    from pypdf import PdfReader

    if not content:
        raise ValueError("PDF content must not be empty")
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            if reader.decrypt("") == 0:
                raise ValueError("encrypted PDF requires a user password")
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            pages.append(text or "")
    except ValueError:
        raise
    except Exception as error:  # noqa: BLE001 - any parser failure fails the document atomically
        raise ValueError("PDF content could not be parsed completely") from error
    if not pages:
        raise ValueError("PDF document must contain at least one page")
    return pages


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one PDF document in order."""

    document_id = _require_document_id(value.document_id)
    digest = hashlib.sha256(value.content).hexdigest()
    texts = _read_pages(value.content)
    return tuple(
        PDFPageInput(
            document_id=document_id,
            document_sha256=digest,
            page_number=index,
            text=text,
        )
        for index, text in enumerate(texts, start=1)
    )


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the stable Source identity of one PDF page revision."""

    document = _require_document_id(document_id)
    if not isinstance(document_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", document_sha256):
        raise ValueError("document_sha256 must be a lowercase SHA-256 hex digest")
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
        raise ValueError("page_number must be a positive integer")
    from urllib.parse import quote

    source_id = "pdf:{document}:{digest}:{page}".format(
        document=quote(document, safe=""),
        digest=document_sha256,
        page=page_number,
    )
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        composite = hashlib.sha256(f"{document}\x00{document_sha256}\x00{page_number}".encode()).hexdigest()
        source_id = f"pdf:{composite}"
    return source_id


class PDFPageSourceAdapter:
    """Resolve and read one PDF page Source."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            definition_version=PDF_PAGE_SOURCE_VERSION,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Project one PDF page as the standard textual evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    version=PDF_PAGE_SOURCE_VERSION,
    projections=(PDFPageTextEvidenceProjection(),),
)


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _relevance(question_terms: list[str], text: str) -> float:
    tokens = _tokens(text)
    if not tokens:
        return 0.0
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    unique = set(question_terms)
    hits = sum(counts.get(term, 0) for term in unique)
    coverage = sum(1 for term in unique if term in counts)
    length_penalty = 1.0 + math.log(1.0 + len(tokens))
    return (hits + 2.0 * coverage) / length_penalty


_STOPWORDS = frozenset(
    """
    a an the of and or to in on for by with from as at is are was were be been being that this these those it its
    what which who whom how many much does do did has have had reported report any there their they them we our us
    if then than about into over under between during within without after before above below not no can could should
    would may might will shall per each other such same also more most less least
    """.split()
)


def _query_tokens(text: str) -> list[str]:
    return [token for token in _WORD.findall(text.lower()) if token not in _STOPWORDS]


def _page_from_sources(sources: object) -> int | None:
    for source in sources:
        tail = source.source_id.rsplit(":", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


async def _search_via_listing(
    memory: Any, question: str, limit: int
) -> tuple["MemoryCitation", ...] | None:
    try:
        listing = await memory.list()
    except Exception:  # noqa: BLE001 - fall back to plain FTS when listing is unavailable
        return None
    records = list(getattr(listing, "entries", ()))
    if not records:
        return None
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

    texts = [record.entry.text for record in records]
    docs = [_query_tokens(text) for text in texts]
    pages = [_page_from_sources(record.entry.sources) for record in records]
    count = len(docs)
    document_frequency: dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            document_frequency[term] = document_frequency.get(term, 0) + 1
    terms: list[str] = []
    for token in _query_tokens(question):
        if token not in terms:
            terms.append(token)
    if not terms:
        return None
    idf = {
        term: math.log(1 + (count - document_frequency.get(term, 0) + 0.5) / (document_frequency.get(term, 0) + 0.5))
        for term in terms
    }

    def score(doc: list[str]) -> float:
        seen = set(doc)
        return sum(idf[term] for term in terms if term in seen)

    scored = sorted(range(count), key=lambda index: (-score(docs[index]), index))
    ranked_pages: list[int] = []
    seen_pages: set[int] = set()

    def add(index: int) -> None:
        page = pages[index]
        if page is not None and page not in seen_pages:
            seen_pages.add(page)
            ranked_pages.append(page)

    for index in scored[:10]:
        add(index)
    for term in sorted(terms, key=lambda item: -idf[item]):
        candidates = [index for index in range(count) if term in set(docs[index])]
        candidates.sort(key=lambda index: (-docs[index].count(term), index))
        for index in candidates[:3]:
            add(index)

    by_page: dict[int, MemoryCitation] = {}
    for index, record in enumerate(records):
        if pages[index] is not None:
            by_page.setdefault(pages[index], record.citation)
    ordered = [page for page in ranked_pages if page in by_page][:limit]
    return tuple(by_page[page] for page in ordered)


_STOPWORDS = frozenset(
    """
    a an the of and or to in on for by with from as at is are was were be been being that this these those it its
    what which who whom how many much does do did has have had reported report any there their they them we our us
    if then than about into over under between during within without after before above below not no can could should
    would may might will shall per each other such same also more most less least
    """.split()
)


def _query_tokens(text: str) -> list[str]:
    return [token for token in _WORD.findall(text.lower()) if token not in _STOPWORDS]


def _page_from_sources(sources: object) -> int | None:
    for source in sources:
        tail = source.source_id.rsplit(":", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


async def _search_via_listing(
    memory: Any, question: str, limit: int
) -> tuple["MemoryCitation", ...] | None:
    try:
        listing = await memory.list()
    except Exception:  # noqa: BLE001 - fall back to plain FTS when listing is unavailable
        return None
    records = list(getattr(listing, "entries", ()))
    if not records:
        return None
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

    texts = [record.entry.text for record in records]
    docs = [_query_tokens(text) for text in texts]
    pages = [_page_from_sources(record.entry.sources) for record in records]
    count = len(docs)
    document_frequency: dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            document_frequency[term] = document_frequency.get(term, 0) + 1
    terms: list[str] = []
    for token in _query_tokens(question):
        if token not in terms:
            terms.append(token)
    if not terms:
        return None
    idf = {
        term: math.log(1 + (count - document_frequency.get(term, 0) + 0.5) / (document_frequency.get(term, 0) + 0.5))
        for term in terms
    }

    def score(doc: list[str]) -> float:
        seen = set(doc)
        return sum(idf[term] for term in terms if term in seen)

    scored = sorted(range(count), key=lambda index: (-score(docs[index]), index))
    ranked_pages: list[int] = []
    seen_pages: set[int] = set()

    def add(index: int) -> None:
        page = pages[index]
        if page is not None and page not in seen_pages:
            seen_pages.add(page)
            ranked_pages.append(page)

    for index in scored[:10]:
        add(index)
    for term in sorted(terms, key=lambda item: -idf[item]):
        candidates = [index for index in range(count) if term in set(docs[index])]
        candidates.sort(key=lambda index: (-docs[index].count(term), index))
        for index in candidates[:3]:
            add(index)

    by_page: dict[int, MemoryCitation] = {}
    for index, record in enumerate(records):
        if pages[index] is not None:
            by_page.setdefault(pages[index], record.citation)
    ordered = [page for page in ranked_pages if page in by_page][:limit]
    return tuple(by_page[page] for page in ordered)


async def search_pdf_pages(
    memory: Any,
    question: str,
    limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` distinct page citations for one natural-language question."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    ranked = await _search_via_listing(memory, question, limit)
    if ranked is not None:
        return ranked

    pool = await memory.search(
        SearchMemoryRequest(query=question, mode="fts", limit=max(limit * 2, 40))
    )
    citations: list[MemoryCitation] = []
    seen: set[int] = set()
    for hit in pool.hits:
        entry = (
            await memory.get(
                GetMemoryEntryRequest(
                    citation=MemoryCitation(
                        memory_ref=hit.memory_ref,
                        entry_id=hit.entry_id,
                        entry_version_id=hit.entry_version_id,
                    )
                )
            )
        ).entry
        page = _page_from_sources(entry.sources)
        if page is None or page in seen:
            continue
        seen.add(page)
        citations.append(
            MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
        )
        if len(citations) >= limit:
            break
    return tuple(citations)


__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDFPageSourceAdapter",
    "PDFPageTextEvidenceProjection",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]

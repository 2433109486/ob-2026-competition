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


async def search_pdf_pages(
    memory: "Any",
    question: str,
    limit: int = 10,
) -> "tuple[MemoryCitation, ...]":
    """Return up to ``limit`` distinct page citations for one natural-language question."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime.models import SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    pool = await memory.search(
        SearchMemoryRequest(query=question, mode="fts", limit=max(limit * 10, 100))
    )
    terms = _tokens(question)
    ranked = sorted(
        pool.hits,
        key=lambda hit: (-_relevance(terms, hit.text), hit.entry_id),
    )
    citations: list[MemoryCitation] = []
    seen: set[tuple[str, str]] = set()
    for hit in ranked:
        key = (hit.memory_ref.artifact_id, hit.entry_id)
        if key in seen:
            continue
        seen.add(key)
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

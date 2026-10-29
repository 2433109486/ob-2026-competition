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

"""Row-level CSV Sources that keep the original record addressable as evidence."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

CSV_ROW_SOURCE_NAME = "csv-row"
CSV_ROW_SOURCE_VERSION = "1"
CSV_ROW_SOURCE_ID_PREFIX = "csv"


class CSVDocumentInput(BaseModel):
    """One complete offline CSV document addressed by its primary-key column."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed CSV data row with its original header order and raw values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...] = Field(default_factory=tuple)


class CSVRowSource(Source):
    """A captured CSV row that keeps identity and the exact original fields."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def _require_document_id(document_id: object) -> str:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")
    if document_id != document_id.strip():
        raise ValueError("document_id must not contain leading or trailing whitespace")
    return document_id


def _require_primary_key(primary_key: object) -> str:
    if not isinstance(primary_key, str) or not primary_key.strip():
        raise ValueError("primary_key must be a non-empty string")
    return primary_key


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the stable, delimiter-safe Source identity of one CSV row."""

    document = _require_document_id(document_id)
    if not isinstance(primary_key_value, str) or not primary_key_value.strip():
        raise ValueError("primary_key_value must be a non-empty string")
    source_id = "{prefix}:{document}:{key}".format(
        prefix=CSV_ROW_SOURCE_ID_PREFIX,
        document=quote(document, safe=""),
        key=quote(primary_key_value, safe=""),
    )
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"CSV row Source identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


def _decode_document(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error


def _validated_header(record: list[str]) -> list[str]:
    if not record:
        raise ValueError("CSV document must start with a non-empty header record")
    seen: set[str] = set()
    for column in record:
        if not column.strip():
            raise ValueError("CSV header fields must be non-empty and non-blank")
        if column in seen:
            raise ValueError("CSV header fields must be unique")
        seen.add(column)
    return record


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate one complete CSV document into row inputs."""

    document_id = _require_document_id(value.document_id)
    primary_key = _require_primary_key(value.primary_key)
    text = _decode_document(value.content)

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = _validated_header(next(reader, []))
        try:
            key_index = header.index(primary_key)
        except ValueError:
            raise ValueError(f"primary_key {primary_key!r} does not match any header column") from None
        columns = tuple(header)
        rows: list[CSVRowInput] = []
        seen_keys: set[str] = set()
        for record in reader:
            if not record:
                continue
            if len(record) != len(columns):
                raise ValueError("CSV data record width must match the header width")
            primary_key_value = record[key_index]
            if not primary_key_value.strip():
                raise ValueError("CSV primary key values must be non-empty")
            if primary_key_value in seen_keys:
                raise ValueError("CSV primary key values must be unique within one document")
            seen_keys.add(primary_key_value)
            csv_row_source_id(document_id, primary_key_value)
            rows.append(
                CSVRowInput(
                    document_id=document_id,
                    primary_key=primary_key,
                    primary_key_value=primary_key_value,
                    columns=columns,
                    values=tuple(record),
                )
            )
    except csv.Error as error:
        raise ValueError("CSV content is malformed") from error
    return tuple(rows)


class CSVRowSourceAdapter:
    """Resolve and read one row-level CSV Source."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            definition_version=CSV_ROW_SOURCE_VERSION,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Project one CSV row as the standard textual evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row: dict[str, JsonValue] = {
            column: value for column, value in zip(source.columns, source.values, strict=True)
        }
        content = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.name,
            content=content,
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_ADAPTER = CSVRowSourceAdapter()
CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSV_ROW_SOURCE_ADAPTER,
    version=CSV_ROW_SOURCE_VERSION,
    projections=(CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_ADAPTER",
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "CSVRowSourceAdapter",
    "CSVRowTextEvidenceProjection",
    "csv_row_source_id",
    "parse_csv_document",
]

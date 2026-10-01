from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path

import extract_msg
import xlrd
from bs4 import BeautifulSoup
from charset_normalizer import from_bytes
from docx import Document
from ebooklib import ITEM_DOCUMENT, epub
from odf import teletype
from odf.opendocument import load as load_odf
from odf.table import Table, TableCell, TableRow
from odf.text import H, P
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pypdf import PdfReader
from pyxlsb import open_workbook as open_xlsb
from striprtf.striprtf import rtf_to_text


@dataclass(slots=True)
class ExtractedChunk:
    label: str
    text: str
    page: int | None = None
    table: str | None = None
    cell: str | None = None
    section: str | None = None


class UnsupportedDocumentError(ValueError):
    pass


_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".log",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".conf",
    ".toml",
    ".sql",
    ".py",
    ".js",
    ".ts",
    ".css",
}

_HTML_SUFFIXES = {".html", ".htm", ".xhtml"}
_XML_SUFFIXES = {".xml"}
_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

SUPPORTED_NATIVE_SUFFIXES = {
    *_TEXT_SUFFIXES,
    *_HTML_SUFFIXES,
    *_XML_SUFFIXES,
    ".csv",
    ".tsv",
    ".pdf",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".xlsb",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".eml",
    ".msg",
    ".epub",
}

SUPPORTED_OCR_SUFFIXES = set(_IMAGE_SUFFIXES) | {".pdf"}
LEGACY_CONVERTIBLE_SUFFIXES = {".doc", ".docm", ".ppt", ".pptm", ".wps"}


def _decode_text(data: bytes) -> str:
    best = from_bytes(data).best()
    if best is not None:
        try:
            return str(best)
        except (UnicodeError, ValueError):
            pass
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "cp866", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _split_text(
    text: str,
    *,
    label: str,
    page: int | None = None,
    table: str | None = None,
    cell: str | None = None,
    section: str | None = None,
    max_chars: int = 3_500,
) -> list[ExtractedChunk]:
    cleaned = "\n".join(
        line.rstrip()
        for line in text.replace("\x00", "").splitlines()
    ).strip()
    if not cleaned:
        return []

    chunks: list[ExtractedChunk] = []
    start = 0
    part = 1
    while start < len(cleaned):
        end = min(len(cleaned), start + max_chars)
        if end < len(cleaned):
            boundary = cleaned.rfind("\n", start, end)
            if boundary <= start + max_chars // 2:
                boundary = cleaned.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        piece = cleaned[start:end].strip()
        if piece:
            suffix = f" · часть {part}" if len(cleaned) > max_chars else ""
            chunks.append(
                ExtractedChunk(
                    label=label + suffix,
                    text=piece,
                    page=page,
                    table=table,
                    cell=cell,
                    section=section,
                )
            )
            part += 1
        start = max(end, start + 1)
    return chunks


def _table_text(rows: list[list[object]]) -> str:
    rendered: list[str] = []
    for row in rows:
        values = ["" if value is None else str(value) for value in row]
        if any(value.strip() for value in values):
            rendered.append(" | ".join(values))
    return "\n".join(rendered)


def _extract_docx(path: Path) -> list[ExtractedChunk]:
    document = Document(str(path))
    chunks: list[ExtractedChunk] = []
    paragraph_text = "\n".join(
        paragraph.text
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    )
    chunks.extend(
        _split_text(
            paragraph_text,
            label="документ DOCX · текст",
            section="body",
        )
    )
    for table_no, table in enumerate(document.tables, start=1):
        rows = [
            [cell.text for cell in row.cells]
            for row in table.rows
        ]
        if not rows:
            continue
        width = max((len(row) for row in rows), default=1)
        batch_size = 20
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            row_from = start + 1
            row_to = start + len(batch)
            chunks.extend(
                _split_text(
                    _table_text(batch),
                    label=(
                        f"таблица {table_no} · строки "
                        f"{row_from}-{row_to}"
                    ),
                    table=str(table_no),
                    cell=f"R{row_from}C1:R{row_to}C{width}",
                    section="table",
                )
            )
    return chunks


def _extract_xlsx(path: Path) -> list[ExtractedChunk]:
    workbook = load_workbook(
        filename=str(path),
        read_only=True,
        data_only=True,
    )
    chunks: list[ExtractedChunk] = []
    try:
        for sheet in workbook.worksheets:
            batch: list[list[object]] = []
            batch_start = 1
            max_width = 1
            for row_no, row in enumerate(
                sheet.iter_rows(values_only=True),
                start=1,
            ):
                values = list(row)
                batch.append(values)
                max_width = max(max_width, len(values))
                if len(batch) < 25:
                    continue
                chunks.extend(
                    _split_text(
                        _table_text(batch),
                        label=(
                            f"лист {sheet.title} · строки "
                            f"{batch_start}-{row_no}"
                        ),
                        table=sheet.title,
                        cell=(
                            f"A{batch_start}:"
                            f"{get_column_letter(max_width)}{row_no}"
                        ),
                        section="worksheet",
                    )
                )
                batch = []
                batch_start = row_no + 1
            if batch:
                row_to = batch_start + len(batch) - 1
                chunks.extend(
                    _split_text(
                        _table_text(batch),
                        label=(
                            f"лист {sheet.title} · строки "
                            f"{batch_start}-{row_to}"
                        ),
                        table=sheet.title,
                        cell=(
                            f"A{batch_start}:"
                            f"{get_column_letter(max_width)}{row_to}"
                        ),
                        section="worksheet",
                    )
                )
    finally:
        workbook.close()
    return chunks


def _extract_xls(path: Path) -> list[ExtractedChunk]:
    workbook = xlrd.open_workbook(str(path), on_demand=True)
    chunks: list[ExtractedChunk] = []
    try:
        for sheet in workbook.sheets():
            rows = [
                [sheet.cell_value(row, col) for col in range(sheet.ncols)]
                for row in range(sheet.nrows)
            ]
            chunks.extend(
                _split_text(
                    _table_text(rows),
                    label=f"лист {sheet.name}",
                )
            )
    finally:
        workbook.release_resources()
    return chunks


def _extract_xlsb(path: Path) -> list[ExtractedChunk]:
    chunks: list[ExtractedChunk] = []
    with open_xlsb(str(path)) as workbook:
        for sheet_name in workbook.sheets:
            with workbook.get_sheet(sheet_name) as sheet:
                rows = [
                    [cell.v for cell in row]
                    for row in sheet.rows()
                ]
                chunks.extend(
                    _split_text(
                        _table_text(rows),
                        label=f"лист {sheet_name}",
                    )
                )
    return chunks


def _extract_pptx(path: Path) -> list[ExtractedChunk]:
    presentation = Presentation(str(path))
    chunks: list[ExtractedChunk] = []
    for number, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = str(getattr(shape, "text", "") or "").strip()
                if text:
                    parts.append(text)
            if getattr(shape, "has_table", False):
                table = shape.table
                for row in table.rows:
                    parts.append(" | ".join(cell.text for cell in row.cells))
        chunks.extend(
            _split_text(
                "\n".join(parts),
                label=f"слайд {number}",
                page=number,
            )
        )
    return chunks


def _extract_odf(path: Path, suffix: str) -> list[ExtractedChunk]:
    document = load_odf(str(path))
    if suffix == ".ods":
        chunks: list[ExtractedChunk] = []
        for table in document.getElementsByType(Table):
            table_name = str(table.getAttribute("name") or "лист")
            rows: list[list[object]] = []
            for row in table.getElementsByType(TableRow):
                values: list[str] = []
                for cell in row.getElementsByType(TableCell):
                    values.append(teletype.extractText(cell))
                if values:
                    rows.append(values)
            chunks.extend(
                _split_text(
                    _table_text(rows),
                    label=f"лист {table_name}",
                )
            )
        return chunks

    nodes = []
    for node_type in (H, P):
        nodes.extend(document.getElementsByType(node_type))
    text = "\n".join(
        teletype.extractText(node)
        for node in nodes
        if teletype.extractText(node).strip()
    )
    label = "презентация ODP" if suffix == ".odp" else "документ ODT"
    return _split_text(text, label=label)


def _extract_rtf(path: Path) -> list[ExtractedChunk]:
    source = _decode_text(path.read_bytes())
    return _split_text(rtf_to_text(source), label="документ RTF")


def _extract_markup(path: Path, *, label: str) -> list[ExtractedChunk]:
    source = _decode_text(path.read_bytes())
    soup = BeautifulSoup(source, "html.parser")
    return _split_text(
        soup.get_text("\n", strip=True),
        label=label,
    )


def _extract_eml(path: Path) -> list[ExtractedChunk]:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    parts = [
        f"Тема: {message.get('subject', '')}",
        f"От: {message.get('from', '')}",
        f"Кому: {message.get('to', '')}",
        f"Копия: {message.get('cc', '')}",
        f"Дата: {message.get('date', '')}",
    ]
    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            content = BeautifulSoup(content, "html.parser").get_text(
                "\n",
                strip=True,
            )
        parts.append(str(content))
    elif message.get_payload():
        parts.append(str(message.get_payload()))
    return _split_text("\n".join(parts), label="письмо EML")


def _extract_msg(path: Path) -> list[ExtractedChunk]:
    message = extract_msg.Message(str(path))
    try:
        parts = [
            f"Тема: {message.subject or ''}",
            f"От: {message.sender or ''}",
            f"Кому: {message.to or ''}",
            f"Копия: {message.cc or ''}",
            f"Дата: {message.date or ''}",
            str(message.body or ""),
        ]
        return _split_text("\n".join(parts), label="письмо MSG")
    finally:
        message.close()


def _extract_epub(path: Path) -> list[ExtractedChunk]:
    book = epub.read_epub(str(path))
    chunks: list[ExtractedChunk] = []
    for number, item in enumerate(
        book.get_items_of_type(ITEM_DOCUMENT),
        start=1,
    ):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        chunks.extend(
            _split_text(
                soup.get_text("\n", strip=True),
                label=f"раздел EPUB {number}",
            )
        )
    return chunks


def extract_document(
    path: Path,
    *,
    name: str,
    content_type: str,
) -> list[ExtractedChunk]:
    suffix = Path(name).suffix.lower()

    if suffix in _TEXT_SUFFIXES:
        return _split_text(
            _decode_text(path.read_bytes()),
            label="текст",
        )

    if suffix in _HTML_SUFFIXES:
        return _extract_markup(path, label="HTML")

    if suffix in _XML_SUFFIXES:
        return _extract_markup(path, label="XML")

    if suffix in {".csv", ".tsv"}:
        raw = _decode_text(path.read_bytes())
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
        text = "\n".join(" | ".join(row) for row in reader)
        return _split_text(
            text,
            label="таблица TSV" if suffix == ".tsv" else "таблица CSV",
        )

    if suffix == ".pdf" or content_type == "application/pdf":
        reader = PdfReader(str(path))
        chunks: list[ExtractedChunk] = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            chunks.extend(
                _split_text(
                    text,
                    label=f"страница {number}",
                    page=number,
                )
            )
        return chunks

    if suffix == ".docx":
        return _extract_docx(path)

    if suffix in {".xlsx", ".xlsm"}:
        return _extract_xlsx(path)

    if suffix == ".xls":
        return _extract_xls(path)

    if suffix == ".xlsb":
        return _extract_xlsb(path)

    if suffix == ".pptx":
        return _extract_pptx(path)

    if suffix in {".odt", ".ods", ".odp"}:
        return _extract_odf(path, suffix)

    if suffix == ".rtf":
        return _extract_rtf(path)

    if suffix == ".eml":
        return _extract_eml(path)

    if suffix == ".msg":
        return _extract_msg(path)

    if suffix == ".epub":
        return _extract_epub(path)

    raise UnsupportedDocumentError(
        "Этот формат пока нельзя прочитать напрямую. "
        "Поддерживаются текстовые файлы, HTML/XML, CSV/TSV, PDF, "
        "DOCX, XLSX/XLSM/XLS/XLSB, PPTX, ODT/ODS/ODP, RTF, "
        "EML/MSG и EPUB. Старые DOC/PPT обрабатываются через LibreOffice."
    )


def preview_document(
    path: Path,
    *,
    name: str,
    content_type: str,
    max_chars: int = 30_000,
) -> dict:
    chunks = extract_document(
        path,
        name=name,
        content_type=content_type,
    )
    used: list[dict] = []
    total = 0
    for chunk in chunks:
        remaining = max_chars - total
        if remaining <= 0:
            break
        text = chunk.text[:remaining]
        used.append(
            {
                "label": chunk.label,
                "page": chunk.page,
                "text": text,
            }
        )
        total += len(text)
    return {
        "chunks": used,
        "chunk_count": len(chunks),
        "preview_chars": total,
        "truncated": len(used) < len(chunks)
        or sum(len(c.text) for c in chunks) > total,
    }

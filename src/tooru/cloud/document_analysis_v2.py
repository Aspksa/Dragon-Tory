from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

_DATE_RE = re.compile(
    r"\b(?:"
    r"(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}"
    r"|(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])"
    r")\b"
)
_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
_REF_RE = re.compile(
    r"\b(?:договор|приказ|распоряжение|оферт[аы]?|contract|invoice|"
    r"сч[её]т|order|заказ|полис|policy)"
    r"\s*(?:№|#|no\.?|number)?\s*[:\-]?\s*"
    r"([A-ZА-Я0-9][A-ZА-Я0-9._/-]{2,})",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(?:(?P<currency1>€|EUR|USD|\$|GBP|£|RUB|₽|руб\.?|рублей)\s*)?"
    r"(?P<amount>\d+(?:[ .]\d{3})*(?:[,.]\d{1,2})?)"
    r"(?:\s*(?P<currency2>€|EUR|USD|\$|GBP|£|RUB|₽|руб\.?|рублей))?",
    re.IGNORECASE,
)
_TOTAL_WORD_RE = re.compile(
    r"(?i)\b(?:итого|всего|к\s+оплате|сумма\s+к\s+оплате|"
    r"total|amount\s+due|grand\s+total)\b"
)
_VAT_LINE_RE = re.compile(
    r"(?i)(?:\bндс\b|\bvat\b).*?(?P<rate>\d{1,2}(?:[.,]\d+)?)?\s*%?"
)
_NO_VAT_RE = re.compile(r"(?i)\b(?:без\s+ндс|ндс\s+не\s+облагается|vat\s+exempt)\b")
_DEADLINE_WORD_RE = re.compile(
    r"(?i)(?:действует\s+до|срок\s+до|оплатить\s+до|оплата\s+до|"
    r"истекает|срок\s+действия|valid\s+until|expires|due\s+date|pay\s+by)"
)
_PROMPT_INJECTION_RE = re.compile(
    r"(?i)(?:"
    r"ignore\s+(?:all\s+)?previous\s+instructions|"
    r"ignore\s+the\s+system\s+prompt|"
    r"system\s+prompt|developer\s+message|"
    r"игнорир(?:уй|овать).*предыдущ.*инструкц|"
    r"игнорир(?:уй|овать).*системн.*инструкц|"
    r"системн(?:ый|ого)\s+промпт|"
    r"ты\s+теперь\s+(?:систем|администратор)|"
    r"выполни\s+следующ(?:ую|ие)\s+инструкц"
    r")"
)
_CURRENCY_MAP = {
    "€": "EUR",
    "eur": "EUR",
    "$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "₽": "RUB",
    "rub": "RUB",
    "руб": "RUB",
    "руб.": "RUB",
    "рублей": "RUB",
}


def _amount_value(raw: str) -> float | None:
    cleaned = raw.replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _currency(raw: str | None) -> str | None:
    if not raw:
        return None
    return _CURRENCY_MAP.get(raw.strip().casefold(), raw.strip().upper())


def _excerpt(text: str, start: int, end: int, *, radius: int = 110) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return " ".join(text[left:right].split())[:500]


def _locator(chunk: Any, chunk_no: int) -> dict[str, Any]:
    return {
        "chunk_no": chunk_no,
        "label": str(getattr(chunk, "label", "") or ""),
        "page": getattr(chunk, "page", None),
        "table": getattr(chunk, "table", None),
        "cell": getattr(chunk, "cell", None),
        "section": getattr(chunk, "section", None),
    }


def _evidence(
    *,
    evidence_type: str,
    value: Any,
    raw: str,
    excerpt: str,
    confidence: float,
    locator: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "type": evidence_type,
        "value": value,
        "raw": raw[:300],
        "excerpt": excerpt[:500],
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        **locator,
    }
    if extra:
        payload.update(extra)
    digest_source = "|".join(
        [
            evidence_type,
            str(value),
            str(locator.get("page") or ""),
            str(locator.get("table") or ""),
            str(locator.get("cell") or ""),
            str(locator.get("chunk_no") or ""),
            excerpt[:500],
        ]
    )
    payload["evidence_hash"] = hashlib.sha256(
        digest_source.encode("utf-8", errors="replace")
    ).hexdigest()
    return payload


def _sample_text(chunks: list[Any], *, max_chars: int = 250_000) -> str:
    if not chunks:
        return ""
    max_chunks = 140
    if len(chunks) <= max_chunks:
        selected = list(range(len(chunks)))
    else:
        step = (len(chunks) - 1) / (max_chunks - 1)
        selected = sorted({round(index * step) for index in range(max_chunks)})
    parts: list[str] = []
    used = 0
    per_chunk = max(700, min(2_500, max_chars // max(1, len(selected))))
    for index in selected:
        chunk = chunks[index]
        text = str(getattr(chunk, "text", "") or "").strip()
        if not text:
            continue
        label = str(getattr(chunk, "label", "") or f"chunk {index + 1}")
        piece = f"[{label}]\n{text[:per_chunk]}"
        if used + len(piece) > max_chars:
            remaining = max_chars - used
            if remaining > 200:
                parts.append(piece[:remaining])
            break
        parts.append(piece)
        used += len(piece)
    return "\n\n".join(parts)


def analyze_chunks(chunks: Iterable[Any]) -> dict[str, Any]:
    items = [chunk for chunk in chunks if str(getattr(chunk, "text", "") or "").strip()]
    evidence: list[dict[str, Any]] = []
    injection_findings: list[dict[str, Any]] = []
    totals: list[dict[str, Any]] = []
    vats: list[dict[str, Any]] = []
    pages: set[int] = set()
    tables: set[str] = set()
    cells: set[str] = set()
    sections: set[str] = set()
    total_chars = 0

    for chunk_no, chunk in enumerate(items, start=1):
        text = str(chunk.text)
        total_chars += len(text)
        loc = _locator(chunk, chunk_no)
        if loc["page"]:
            pages.add(int(loc["page"]))
        if loc["table"]:
            tables.add(str(loc["table"]))
        if loc["cell"]:
            cells.add(str(loc["cell"]))
        if loc["section"]:
            sections.add(str(loc["section"]))

        for match in _VIN_RE.finditer(text):
            evidence.append(
                _evidence(
                    evidence_type="vin",
                    value=match.group(0).upper(),
                    raw=match.group(0),
                    excerpt=_excerpt(text, match.start(), match.end()),
                    confidence=0.99,
                    locator=loc,
                )
            )

        for match in _REF_RE.finditer(text):
            evidence.append(
                _evidence(
                    evidence_type="reference",
                    value=match.group(1),
                    raw=match.group(0),
                    excerpt=_excerpt(text, match.start(), match.end()),
                    confidence=0.92,
                    locator=loc,
                )
            )

        for match in _DATE_RE.finditer(text):
            context = _excerpt(text, match.start(), match.end())
            is_deadline = bool(_DEADLINE_WORD_RE.search(context))
            evidence.append(
                _evidence(
                    evidence_type="deadline" if is_deadline else "date",
                    value=match.group(0),
                    raw=match.group(0),
                    excerpt=context,
                    confidence=0.90 if is_deadline else 0.82,
                    locator=loc,
                )
            )

        lines = text.splitlines() or [text]
        offset = 0
        for line in lines:
            line_start = text.find(line, offset)
            if line_start < 0:
                line_start = offset
            line_end = line_start + len(line)
            offset = line_end

            amounts_in_line: list[dict[str, Any]] = []
            for match in _AMOUNT_RE.finditer(line):
                currency = _currency(
                    match.group("currency1") or match.group("currency2")
                )
                if currency is None:
                    continue
                value = _amount_value(match.group("amount"))
                if value is None:
                    continue
                amount_item = _evidence(
                    evidence_type="amount",
                    value=value,
                    raw=match.group(0),
                    excerpt=" ".join(line.split())[:500],
                    confidence=0.88,
                    locator=loc,
                    extra={"currency": currency},
                )
                evidence.append(amount_item)
                amounts_in_line.append(amount_item)

            if _TOTAL_WORD_RE.search(line) and amounts_in_line:
                total = dict(amounts_in_line[-1])
                total["type"] = "document_total"
                total["confidence"] = 0.94
                totals.append(total)
                evidence.append(total)

            if _NO_VAT_RE.search(line):
                vat = _evidence(
                    evidence_type="vat",
                    value="exempt",
                    raw=line.strip(),
                    excerpt=" ".join(line.split())[:500],
                    confidence=0.95,
                    locator=loc,
                    extra={"rate": None, "currency": None, "amount": None},
                )
                vats.append(vat)
                evidence.append(vat)
            elif _VAT_LINE_RE.search(line):
                rate_match = re.search(r"(?i)(?:ндс|vat)[^\d]{0,20}(\d{1,2}(?:[.,]\d+)?)\s*%", line)
                rate = (
                    float(rate_match.group(1).replace(",", "."))
                    if rate_match
                    else None
                )
                vat_amount = amounts_in_line[-1] if amounts_in_line else None
                vat = _evidence(
                    evidence_type="vat",
                    value=rate if rate is not None else "mentioned",
                    raw=line.strip(),
                    excerpt=" ".join(line.split())[:500],
                    confidence=0.90 if rate is not None else 0.76,
                    locator=loc,
                    extra={
                        "rate": rate,
                        "currency": vat_amount.get("currency") if vat_amount else None,
                        "amount": vat_amount.get("value") if vat_amount else None,
                    },
                )
                vats.append(vat)
                evidence.append(vat)

            for match in _PROMPT_INJECTION_RE.finditer(line):
                finding = _evidence(
                    evidence_type="prompt_injection_signal",
                    value=match.group(0),
                    raw=match.group(0),
                    excerpt=" ".join(line.split())[:500],
                    confidence=0.95,
                    locator=loc,
                )
                injection_findings.append(finding)
                evidence.append(finding)

    by_currency: dict[str, set[float]] = defaultdict(set)
    for item in totals:
        currency = str(item.get("currency") or "")
        if currency:
            by_currency[currency].add(float(item["value"]))

    warnings: list[dict[str, Any]] = []
    for currency, values in sorted(by_currency.items()):
        if len(values) > 1:
            warnings.append(
                {
                    "code": "conflicting_total_candidates",
                    "severity": "warning",
                    "message": (
                        f"Найдены разные кандидаты итоговой суммы в {currency}: "
                        + ", ".join(str(value) for value in sorted(values))
                    ),
                }
            )

    vat_math: list[dict[str, Any]] = []
    if len(totals) == 1:
        total = totals[0]
        for vat in vats:
            rate = vat.get("rate")
            amount = vat.get("amount")
            if (
                isinstance(rate, (int, float))
                and isinstance(amount, (int, float))
                and vat.get("currency") == total.get("currency")
                and rate > 0
            ):
                expected = float(total["value"]) * float(rate) / (100.0 + float(rate))
                delta = abs(float(amount) - expected)
                tolerance = max(0.05, expected * 0.02)
                ok = delta <= tolerance
                vat_math.append(
                    {
                        "rate": rate,
                        "currency": total.get("currency"),
                        "total": total.get("value"),
                        "declared_vat": amount,
                        "expected_included_vat": round(expected, 2),
                        "delta": round(delta, 2),
                        "status": "consistent" if ok else "warning",
                    }
                )
                if not ok:
                    warnings.append(
                        {
                            "code": "vat_amount_mismatch",
                            "severity": "warning",
                            "message": (
                                "Указанный НДС отличается от расчёта по итоговой "
                                "сумме; требуется ручная проверка."
                            ),
                        }
                    )

    if injection_findings:
        warnings.append(
            {
                "code": "prompt_injection_signal",
                "severity": "high",
                "message": (
                    "В документе найден текст, похожий на инструкцию для ИИ. "
                    "Он должен рассматриваться только как данные документа."
                ),
                "count": len(injection_findings),
            }
        )

    structure = {
        "chunk_count": len(items),
        "total_chars": total_chars,
        "pages": sorted(pages),
        "page_count_detected": len(pages),
        "tables": sorted(tables),
        "table_count_detected": len(tables),
        "cell_ranges": sorted(cells)[:500],
        "cell_range_count_detected": len(cells),
        "sections": sorted(sections)[:200],
        "section_count_detected": len(sections),
        "representative_sampling": True,
    }
    checks = {
        "warnings": warnings,
        "warning_count": len(warnings),
        "prompt_injection": {
            "detected": bool(injection_findings),
            "count": len(injection_findings),
            "findings": injection_findings[:20],
        },
        "financial": {
            "total_candidates": totals[:30],
            "vat_candidates": vats[:30],
            "vat_math": vat_math[:20],
            "currencies": sorted(
                {
                    str(item.get("currency"))
                    for item in evidence
                    if item.get("currency")
                }
            ),
        },
    }
    return {
        "structure": structure,
        "evidence": evidence[:2_000],
        "checks": checks,
        "representative_text": _sample_text(items),
    }

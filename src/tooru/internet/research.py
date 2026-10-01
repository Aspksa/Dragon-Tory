from __future__ import annotations

import html
import ipaddress
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup


class InternetResearchError(RuntimeError):
    pass


@dataclass(slots=True)
class WebSource:
    title: str
    url: str
    snippet: str = ""
    excerpt: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "excerpt": self.excerpt,
        }


class WebResearchService:
    """Small no-key web research layer for explicit user web requests."""

    SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"

    def __init__(
        self,
        *,
        enabled: bool = True,
        timeout_seconds: float = 12.0,
        max_results: int = 5,
        fetch_pages: int = 3,
        max_page_bytes: int = 1_500_000,
        max_excerpt_chars: int = 6_000,
    ) -> None:
        self.enabled = enabled
        self.timeout_seconds = max(2.0, float(timeout_seconds))
        self.max_results = max(1, min(int(max_results), 10))
        self.fetch_pages = max(0, min(int(fetch_pages), self.max_results))
        self.max_page_bytes = max(100_000, int(max_page_bytes))
        self.max_excerpt_chars = max(1_000, int(max_excerpt_chars))

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36 "
                "Dragon-Tory-WebResearch/1.0"
            ),
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Language": "ru,en;q=0.8",
        }

    def _read_url(
        self,
        url: str,
        *,
        trusted_search_endpoint: bool = False,
    ) -> tuple[str, str]:
        if not trusted_search_endpoint and not self._is_safe_public_url(url):
            raise InternetResearchError(
                "Заблокирован небезопасный или локальный интернет-адрес."
            )
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                content_type = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .casefold()
                )
                if content_type and not (
                    content_type.startswith("text/")
                    or content_type in {
                        "application/xhtml+xml",
                        "application/xml",
                    }
                ):
                    raise InternetResearchError(
                        f"Неподдерживаемый тип интернет-страницы: {content_type}."
                    )
                raw = response.read(self.max_page_bytes + 1)
                if len(raw) > self.max_page_bytes:
                    raw = raw[: self.max_page_bytes]
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace"), response.geturl()
        except InternetResearchError:
            raise
        except Exception as exc:
            raise InternetResearchError(
                f"Не удалось открыть интернет-страницу: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _clean_result_url(value: str) -> str:
        raw = html.unescape((value or "").strip())
        if raw.startswith("//"):
            raw = "https:" + raw
        parsed = urllib.parse.urlparse(raw)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            query = urllib.parse.parse_qs(parsed.query)
            target = query.get("uddg", [""])[0]
            if target:
                raw = urllib.parse.unquote(target)
        return raw

    @staticmethod
    def _host_is_public(hostname: str) -> bool:
        host = (hostname or "").strip().rstrip(".").casefold()
        if not host or host in {"localhost", "localhost.localdomain"}:
            return False
        if host.endswith(".local") or host.endswith(".internal"):
            return False
        try:
            literal = ipaddress.ip_address(host)
            return literal.is_global
        except ValueError:
            pass
        try:
            addresses = socket.getaddrinfo(host, None)
        except OSError:
            return False
        resolved = {
            item[4][0].split("%", 1)[0]
            for item in addresses
            if item and item[4]
        }
        if not resolved:
            return False
        try:
            return all(ipaddress.ip_address(value).is_global for value in resolved)
        except ValueError:
            return False

    @classmethod
    def _is_safe_public_url(cls, url: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.username or parsed.password:
            return False
        return cls._host_is_public(parsed.hostname or "")

    @staticmethod
    def _visible_text(markup: str) -> tuple[str, str]:
        soup = BeautifulSoup(markup, "html.parser")
        for tag in soup(
            [
                "script",
                "style",
                "noscript",
                "svg",
                "form",
                "nav",
                "header",
                "footer",
            ]
        ):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        chunks = [
            line.strip()
            for line in soup.get_text("\n").splitlines()
            if line.strip()
        ]
        text = "\n".join(chunks)
        return title, text

    def _search_results(self, query: str) -> list[WebSource]:
        encoded = urllib.parse.quote_plus(query)
        markup, _ = self._read_url(
            self.SEARCH_URL.format(query=encoded),
            trusted_search_endpoint=True,
        )
        soup = BeautifulSoup(markup, "html.parser")
        results: list[WebSource] = []
        seen: set[str] = set()

        for result in soup.select(".result"):
            anchor = result.select_one("a.result__a")
            if anchor is None:
                continue
            url = self._clean_result_url(anchor.get("href", ""))
            if not url or url in seen or not self._is_safe_public_url(url):
                continue
            seen.add(url)
            snippet_node = result.select_one(".result__snippet")
            results.append(
                WebSource(
                    title=anchor.get_text(" ", strip=True) or url,
                    url=url,
                    snippet=(
                        snippet_node.get_text(" ", strip=True)
                        if snippet_node is not None
                        else ""
                    ),
                )
            )
            if len(results) >= self.max_results:
                break

        # DuckDuckGo sometimes changes result wrappers. Fall back to public
        # outbound links rather than pretending internet is unavailable.
        if not results:
            for anchor in soup.find_all("a", href=True):
                url = self._clean_result_url(anchor.get("href", ""))
                title = anchor.get_text(" ", strip=True)
                if (
                    not title
                    or not url
                    or url in seen
                    or not self._is_safe_public_url(url)
                    or "duckduckgo.com" in urllib.parse.urlparse(url).netloc
                ):
                    continue
                seen.add(url)
                results.append(WebSource(title=title[:300], url=url))
                if len(results) >= self.max_results:
                    break

        if not results:
            raise InternetResearchError(
                "Поисковик не вернул пригодных результатов."
            )
        return results

    def research(self, query: str) -> dict[str, Any]:
        if not self.enabled:
            raise InternetResearchError("Интернет-поиск отключён в настройках.")
        cleaned = " ".join(str(query or "").split()).strip()
        if not cleaned:
            raise InternetResearchError("Пустой поисковый запрос.")
        cleaned = cleaned[:1_000]

        results = self._search_results(cleaned)
        for source in results[: self.fetch_pages]:
            try:
                markup, final_url = self._read_url(source.url)
                title, text = self._visible_text(markup)
                source.url = final_url
                if title:
                    source.title = title[:300]
                source.excerpt = text[: self.max_excerpt_chars]
            except InternetResearchError:
                # Search snippets still provide useful source provenance.
                continue

        return {
            "query": cleaned,
            "searched_at": datetime.now(UTC).isoformat(),
            "provider": "duckduckgo-html",
            "sources": [source.as_dict() for source in results],
        }

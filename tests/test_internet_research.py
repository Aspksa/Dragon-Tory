from __future__ import annotations

from tooru.internet.research import WebResearchService


def test_web_research_parses_results_and_fetches_public_page(monkeypatch):
    service = WebResearchService(
        max_results=2,
        fetch_pages=1,
    )
    search_html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="https://example.com/land-cruiser">
          Land Cruiser 80 fuel consumption
        </a>
        <div class="result__snippet">Owner and specification data.</div>
      </div>
    </body></html>
    """
    page_html = """
    <html>
      <head><title>Land Cruiser 80</title></head>
      <body><main>Fuel consumption depends on engine and use.</main></body>
    </html>
    """

    monkeypatch.setattr(
        service,
        "_is_safe_public_url",
        lambda url: True,
    )

    def fake_read(url: str, *, trusted_search_endpoint: bool = False):
        if trusted_search_endpoint:
            return search_html, url
        return page_html, url

    monkeypatch.setattr(service, "_read_url", fake_read)

    result = service.research("Land Cruiser 80 расход топлива")

    assert result["provider"] == "duckduckgo-html"
    assert len(result["sources"]) == 1
    assert result["sources"][0]["title"] == "Land Cruiser 80"
    assert "Fuel consumption" in result["sources"][0]["excerpt"]


def test_web_research_blocks_local_addresses() -> None:
    service = WebResearchService()

    assert service._is_safe_public_url("http://127.0.0.1:8787/") is False
    assert service._is_safe_public_url("http://localhost/") is False
    assert service._is_safe_public_url("file:///etc/passwd") is False

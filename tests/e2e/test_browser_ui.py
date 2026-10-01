import re

import pytest

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect
sync_playwright = playwright.sync_playwright


def test_dashboard_navigation_and_update_button_recovers() -> None:
    page_errors: list[str] = []

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        page.route(
            "**/v1/update/check",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"e2e simulated update failure"}',
            ),
        )

        page.goto("http://127.0.0.1:8787/", wait_until="networkidle")
        expect(page.locator("#home")).to_have_class(re.compile(r"\bactive\b"))
        expect(page.locator("#homeObsState")).to_be_visible()
        expect(page.locator("#homeTraceList")).to_be_visible()

        page.get_by_role(
            "button",
            name=re.compile("Центр диагностики"),
        ).click()
        expect(page.locator("#diagnostics")).to_have_class(
            re.compile(r"\bactive\b")
        )

        page.get_by_role("button", name=re.compile("Настройки")).click()
        expect(page.locator("#settings")).to_have_class(
            re.compile(r"\bactive\b")
        )

        page.get_by_role("button", name=re.compile("Мой диск")).click()
        expect(page.locator("#cloud")).to_have_class(
            re.compile(r"\bactive\b")
        )

        page.get_by_role("button", name=re.compile("Обновление")).click()
        check_button = page.locator("#checkUpdate")
        expect(check_button).to_be_enabled()
        check_button.click()
        expect(check_button).to_be_enabled(timeout=10_000)
        expect(page.locator("#updateState")).not_to_have_text("Проверка…")

        assert page_errors == []
        browser.close()

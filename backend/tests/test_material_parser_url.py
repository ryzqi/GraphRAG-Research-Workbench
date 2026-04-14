from __future__ import annotations

from typing import Any
import uuid

import pytest

from app.core.settings import Settings
from app.models.source_material import SourceMaterial, SourceType
from app.services.parsing.errors import ParseError
from app.services.parsing.types import ParsedDocument
from app.services.parsing import url_parser
from app.services.parsing import material_parser


def _settings() -> Settings:
    return Settings(_env_file=None)


def _fetch_result() -> "url_parser.UrlFetchResult":
    return url_parser.UrlFetchResult(
        requested_url="https://example.com/article",
        final_url="https://example.com/final-article",
        status_code=200,
        response_headers={"content-type": "text/html; charset=utf-8"},
        content_bytes=b"<html><body>raw body</body></html>",
        html_text="<html><head><title>Raw</title></head><body>raw body</body></html>",
        redirect_count=1,
    )


async def test_parse_url_document_prefers_crawl4ai_and_records_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        url: str, *, http_client: Any, settings: Settings
    ) -> "url_parser.UrlFetchResult":
        assert url == "https://example.com/article"
        return _fetch_result()

    async def fake_crawl4ai_extract(
        payload: "url_parser.UrlFetchResult",
        *,
        settings: Settings,
        url_crawler: Any | None = None,
    ) -> ParsedDocument:
        assert payload.final_url == "https://example.com/final-article"
        assert url_crawler is None
        return ParsedDocument(
            text="# 浏览器标题\n\n浏览器正文",
            mime_type="text/markdown",
            locator={"url": payload.final_url},
            metadata={"title": "浏览器标题"},
        )

    monkeypatch.setattr(url_parser, "_fetch_url", fake_fetch_url)
    monkeypatch.setattr(url_parser, "_extract_with_crawl4ai", fake_crawl4ai_extract)

    async def should_not_run(*args: Any, **kwargs: Any) -> ParsedDocument:
        raise AssertionError("不应进入回退策略")

    monkeypatch.setattr(url_parser, "_extract_with_trafilatura", should_not_run)
    monkeypatch.setattr(url_parser, "_extract_with_readability", should_not_run)

    doc = await url_parser.parse_url_document(
        "https://example.com/article",
        http_client=object(),
        settings=_settings(),
    )

    assert doc.text == "# 浏览器标题\n\n浏览器正文"
    assert doc.metadata is not None
    assert doc.metadata["url_extract_path"] == "crawl4ai"
    assert doc.metadata["url_extract_fallback_used"] is False
    assert doc.metadata["url_http_status"] == 200
    assert doc.metadata["url_final_url"] == "https://example.com/final-article"
    assert doc.metadata["url_title_source"] == "crawl4ai"


async def test_parse_url_document_falls_back_to_trafilatura_and_keeps_primary_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        url: str, *, http_client: Any, settings: Settings
    ) -> "url_parser.UrlFetchResult":
        return _fetch_result()

    async def fake_crawl4ai_extract(
        payload: "url_parser.UrlFetchResult",
        *,
        settings: Settings,
        url_crawler: Any | None = None,
    ) -> ParsedDocument:
        assert url_crawler is None
        raise ParseError(
            error_code="CRAWL4AI_EXTRACTION_FAILED",
            message="浏览器抓取失败",
            details={"url": payload.final_url},
        )

    async def fake_trafilatura_extract(
        payload: "url_parser.UrlFetchResult", *, settings: Settings
    ) -> ParsedDocument:
        return ParsedDocument(
            text="# 回退标题\n\n回退正文",
            mime_type="text/markdown",
            locator={"url": payload.final_url},
            metadata={"title": "回退标题"},
        )

    monkeypatch.setattr(url_parser, "_fetch_url", fake_fetch_url)
    monkeypatch.setattr(url_parser, "_extract_with_crawl4ai", fake_crawl4ai_extract)
    monkeypatch.setattr(url_parser, "_extract_with_trafilatura", fake_trafilatura_extract)

    async def should_not_run(*args: Any, **kwargs: Any) -> ParsedDocument:
        raise AssertionError("trafilatura 成功后不应继续回退")

    monkeypatch.setattr(url_parser, "_extract_with_readability", should_not_run)

    doc = await url_parser.parse_url_document(
        "https://example.com/article",
        http_client=object(),
        settings=_settings(),
    )

    assert doc.text == "# 回退标题\n\n回退正文"
    assert doc.metadata is not None
    assert doc.metadata["url_extract_path"] == "trafilatura"
    assert doc.metadata["url_extract_fallback_used"] is True
    assert doc.metadata["url_primary_error_code"] == "CRAWL4AI_EXTRACTION_FAILED"
    assert doc.metadata["url_primary_error_message"] == "浏览器抓取失败"


async def test_parse_url_document_raises_structured_error_when_all_extractors_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        url: str, *, http_client: Any, settings: Settings
    ) -> "url_parser.UrlFetchResult":
        return _fetch_result()

    async def fail_extract(
        payload: "url_parser.UrlFetchResult",
        *,
        settings: Settings,
        url_crawler: Any | None = None,
    ) -> ParsedDocument:
        assert url_crawler is None
        raise ParseError(
            error_code="EXTRACTOR_FAILED",
            message=f"failed:{payload.final_url}",
        )

    monkeypatch.setattr(url_parser, "_fetch_url", fake_fetch_url)
    monkeypatch.setattr(url_parser, "_extract_with_crawl4ai", fail_extract)
    monkeypatch.setattr(url_parser, "_extract_with_trafilatura", fail_extract)
    monkeypatch.setattr(url_parser, "_extract_with_readability", fail_extract)

    with pytest.raises(ParseError) as exc_info:
        await url_parser.parse_url_document(
            "https://example.com/article",
            http_client=object(),
            settings=_settings(),
        )

    assert exc_info.value.error_code == "URL_EXTRACT_FAILED"
    assert exc_info.value.details is not None
    assert exc_info.value.details["strategy_count"] == 3


async def test_parse_url_document_rejects_unsafe_final_url_before_browser_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        url: str, *, http_client: Any, settings: Settings
    ) -> "url_parser.UrlFetchResult":
        assert url == "https://example.com/article"
        return url_parser.UrlFetchResult(
            requested_url=url,
            final_url="http://127.0.0.1/private",
            status_code=200,
            response_headers={"content-type": "text/html; charset=utf-8"},
            content_bytes=b"<html><body>blocked</body></html>",
            html_text="<html><body>blocked</body></html>",
            redirect_count=1,
        )

    async def fake_crawl4ai_extract(
        payload: "url_parser.UrlFetchResult",
        *,
        settings: Settings,
        url_crawler: Any | None = None,
    ) -> ParsedDocument:
        return ParsedDocument(
            text="# 不应导航\n\n浏览器正文",
            mime_type="text/markdown",
            locator={"url": payload.final_url},
            metadata={"title": "不应导航"},
        )

    monkeypatch.setattr(url_parser, "_fetch_url", fake_fetch_url)
    monkeypatch.setattr(url_parser, "_extract_with_crawl4ai", fake_crawl4ai_extract)

    async def should_not_run(*args: Any, **kwargs: Any) -> ParsedDocument:
        raise AssertionError("不应进入非浏览器回退策略")

    monkeypatch.setattr(url_parser, "_extract_with_trafilatura", should_not_run)
    monkeypatch.setattr(url_parser, "_extract_with_readability", should_not_run)

    with pytest.raises(ParseError) as exc_info:
        await url_parser.parse_url_document(
            "https://example.com/article",
            http_client=object(),
            settings=_settings(),
        )

    assert exc_info.value.error_code == "URL_FINAL_URL_BLOCKED"
    assert exc_info.value.details is not None
    assert exc_info.value.details["url"] == "http://127.0.0.1/private"


async def test_parse_material_uses_unified_url_parser_and_keeps_source_type_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_parse_url_document(
        url: str,
        *,
        http_client: Any,
        settings: Settings,
        url_crawler: Any | None = None,
        allow_crawl4ai_cold_start: bool = True,
    ) -> ParsedDocument:
        assert url == "https://example.com/article"
        assert url_crawler is None
        assert allow_crawl4ai_cold_start is True
        return ParsedDocument(
            text="# 标题\n\n正文",
            mime_type="text/markdown",
            locator={"url": url},
            metadata={"title": "标题", "url_extract_path": "crawl4ai"},
        )

    monkeypatch.setattr(material_parser, "parse_url_document", fake_parse_url_document)

    material = SourceMaterial(
        kb_id=uuid.uuid4(),
        source_type=SourceType.URL,
        title="示例",
        uri="https://example.com/article",
        mime_type=None,
        content_hash=None,
        metadata_=None,
    )

    doc = await material_parser.parse_material(
        material,
        settings=_settings(),
        http_client=object(),
    )

    assert doc.text == "# 标题\n\n正文"
    assert doc.metadata is not None
    assert doc.metadata["url_extract_path"] == "crawl4ai"
    assert doc.metadata["source_type"] == "url"

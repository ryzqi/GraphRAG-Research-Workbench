from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.core.errors import AppError
from app.core.settings import Settings
from app.services.parsing.errors import ParseError
from app.services.parsing.types import ParsedDocument
from app.services.url_ingestion_guard import build_url_ingestion_guard


@dataclass(slots=True)
class UrlFetchResult:
    requested_url: str
    final_url: str
    status_code: int
    response_headers: dict[str, str]
    content_bytes: bytes
    html_text: str
    redirect_count: int


class UrlCrawler(Protocol):
    async def arun(self, *, url: str) -> object: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class _Crawl4AiCrawler:
    crawler: Any
    run_config: Any

    async def arun(self, *, url: str) -> object:
        return await self.crawler.arun(url=url, config=self.run_config)

    async def aclose(self) -> None:
        await self.crawler.__aexit__(None, None, None)


async def parse_url_document(
    url: str,
    *,
    http_client: httpx.AsyncClient,
    settings: Settings,
    url_crawler: UrlCrawler | None = None,
    allow_crawl4ai_cold_start: bool = True,
) -> ParsedDocument:
    """统一 URL 解析入口：先预取，再按多策略提取正文。"""
    payload = await _fetch_url(url, http_client=http_client, settings=settings)
    payload.final_url = await _ensure_final_url_safe(payload=payload, settings=settings)

    strategies = ("crawl4ai", "trafilatura", "readability")
    failures: list[tuple[str, ParseError]] = []

    for strategy_name in strategies:
        try:
            if strategy_name == "crawl4ai":
                if url_crawler is None and not allow_crawl4ai_cold_start:
                    raise ParseError(
                        error_code="CRAWL4AI_UNAVAILABLE",
                        message="URL crawler 不可用，跳过浏览器抽取",
                        details={"url": payload.final_url},
                    )
                doc = await _extract_with_crawl4ai(
                    payload,
                    settings=settings,
                    url_crawler=url_crawler,
                )
            elif strategy_name == "trafilatura":
                doc = await _extract_with_trafilatura(payload, settings=settings)
            else:
                doc = await _extract_with_readability(payload, settings=settings)
            _ensure_document_has_content(doc, empty_error_code=f"{strategy_name.upper()}_EMPTY_RESULT")
            return _finalize_document(
                doc,
                payload=payload,
                strategy_name=strategy_name,
                failures=failures,
            )
        except ParseError as exc:
            failures.append((strategy_name, exc))
            continue

    raise ParseError(
        error_code="URL_EXTRACT_FAILED",
        message="URL 正文抽取失败",
        details={
            "url": payload.final_url,
            "strategy_count": len(strategies),
            "failures": [
                {
                    "strategy": strategy_name,
                    "error_code": exc.error_code,
                    "message": exc.message,
                }
                for strategy_name, exc in failures
            ],
        },
    )


async def _fetch_url(
    url: str,
    *,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> UrlFetchResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ParseError(
            error_code="INVALID_URL_SCHEME",
            message=f"不支持的 URL scheme: {parsed.scheme!r}",
        )

    max_redirects = getattr(settings, "ingestion_url_max_redirects", 3)
    max_bytes = getattr(settings, "ingestion_url_max_bytes", 20 * 1024 * 1024)
    timeout_seconds = max(
        float(getattr(settings, "ingestion_url_timeout_seconds", 25.0)),
        1.0,
    )
    user_agent = getattr(
        settings, "ingestion_url_user_agent", "multi-kb-agent/ingestion"
    )

    headers = {"User-Agent": user_agent}

    try:
        async with http_client.stream(
            "GET",
            url,
            follow_redirects=True,
            headers=headers,
            timeout=timeout_seconds,
        ) as resp:
            redirect_count = len(resp.history)
            if redirect_count > max_redirects:
                raise ParseError(
                    error_code="URL_TOO_MANY_REDIRECTS",
                    message=f"URL 重定向次数过多（>{max_redirects}）",
                    details={"max_redirects": max_redirects, "url": url},
                )

            if resp.status_code >= 400:
                raise ParseError(
                    error_code="URL_FETCH_FAILED",
                    message=f"URL 抓取失败：HTTP {resp.status_code}",
                    details={"status_code": resp.status_code, "url": url},
                )

            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ParseError(
                        error_code="URL_RESPONSE_TOO_LARGE",
                        message=f"URL 响应体超过限制（>{max_bytes} bytes）",
                        details={"max_bytes": max_bytes, "url": url},
                    )

            content_bytes = bytes(buf)
            status_code = resp.status_code
            final_url = str(resp.url)
            response_headers = dict(resp.headers)
    except ParseError:
        raise
    except httpx.TooManyRedirects as exc:
        raise ParseError(
            error_code="URL_TOO_MANY_REDIRECTS",
            message=f"URL 重定向次数过多（>{max_redirects}）",
            details={"max_redirects": max_redirects, "url": url},
        ) from exc
    except Exception as exc:
        raise ParseError(
            error_code="URL_FETCH_EXCEPTION",
            message=f"URL 抓取异常：{exc}",
            details={"url": url},
        ) from exc

    return UrlFetchResult(
        requested_url=url,
        final_url=final_url,
        status_code=status_code,
        response_headers=response_headers,
        content_bytes=content_bytes,
        html_text=_decode_html_text(content_bytes),
        redirect_count=redirect_count,
    )


async def _extract_with_crawl4ai(
    payload: UrlFetchResult,
    *,
    settings: Settings,
    url_crawler: UrlCrawler | None = None,
) -> ParsedDocument:
    crawler = url_crawler
    owns_crawler = False
    try:
        if crawler is None:
            crawler = await create_url_crawler(settings=settings)
            owns_crawler = True
        result = await crawler.arun(url=payload.final_url)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(
            error_code="CRAWL4AI_RUNTIME_ERROR",
            message=f"Crawl4AI 抓取失败：{exc}",
            details={"url": payload.final_url},
        ) from exc
    finally:
        if owns_crawler:
            await close_url_crawler(crawler)

    if not getattr(result, "success", False):
        raise ParseError(
            error_code="CRAWL4AI_EXTRACTION_FAILED",
            message=(getattr(result, "error_message", None) or "Crawl4AI 未返回成功结果"),
            details={
                "url": payload.final_url,
                "status_code": getattr(result, "status_code", None),
            },
        )

    markdown_obj = getattr(result, "markdown", None)
    markdown_text = ""
    if markdown_obj is not None:
        fit_markdown = getattr(markdown_obj, "fit_markdown", None)
        markdown_text = str(fit_markdown or markdown_obj).strip()
    if not markdown_text:
        extracted_content = getattr(result, "extracted_content", None)
        if isinstance(extracted_content, str):
            markdown_text = extracted_content.strip()
    if not markdown_text:
        raise ParseError(
            error_code="CRAWL4AI_EMPTY_RESULT",
            message="Crawl4AI 未返回可用正文",
            details={"url": payload.final_url},
        )

    title = _extract_title_from_metadata(getattr(result, "metadata", None))
    return ParsedDocument(
        text=markdown_text,
        mime_type="text/markdown",
        locator={"url": payload.final_url},
        metadata={"title": title} if title else None,
        chunks=None,
    )


async def _extract_with_trafilatura(
    payload: UrlFetchResult,
    *,
    settings: Settings,
) -> ParsedDocument:
    def _extract_sync() -> tuple[str, str | None]:
        try:
            import trafilatura  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover
            raise ParseError(
                error_code="TRAFILATURA_NOT_INSTALLED",
                message="未安装 trafilatura，无法进行 URL 正文抽取",
                details={"error": str(exc)},
            ) from exc

        markdown = trafilatura.extract(
            payload.html_text,
            url=payload.final_url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_formatting=True,
        )
        if not isinstance(markdown, str) or not markdown.strip():
            raise ParseError(
                error_code="TRAFILATURA_EMPTY_RESULT",
                message="Trafilatura 未提取到有效正文",
                details={"url": payload.final_url},
            )
        return markdown.strip(), _extract_html_title(payload.html_text)

    markdown_text, title = await asyncio.to_thread(_extract_sync)
    return ParsedDocument(
        text=markdown_text,
        mime_type="text/markdown",
        locator={"url": payload.final_url},
        metadata={"title": title} if title else None,
        chunks=None,
    )


async def _extract_with_readability(
    payload: UrlFetchResult,
    *,
    settings: Settings,
) -> ParsedDocument:
    try:
        from readability import Document  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise ParseError(
            error_code="READABILITY_NOT_INSTALLED",
            message="未安装 readability-lxml，无法进行 URL 正文抽取",
            details={"error": str(exc)},
        ) from exc

    readability_doc = Document(payload.html_text)
    title = (readability_doc.title() or "").strip() or None
    main_html = readability_doc.summary()

    try:
        from lxml import html as lxml_html  # type: ignore[import-not-found]

        root = lxml_html.fromstring(main_html)
        text = (root.text_content() or "").strip()
    except Exception as exc:
        raise ParseError(
            error_code="URL_EXTRACT_FAILED",
            message=f"URL 正文抽取失败：{exc}",
            details={"url": payload.final_url},
        ) from exc

    body_text = _normalize_text_content(text)
    markdown_text = body_text
    if title:
        markdown_text = f"# {title}\n\n{body_text}".strip()

    return ParsedDocument(
        text=markdown_text,
        mime_type="text/markdown",
        locator={"url": payload.final_url},
        metadata={"title": title} if title else None,
        chunks=None,
    )


def _decode_html_text(content_bytes: bytes) -> str:
    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return content_bytes.decode("gb18030", errors="replace")


def _normalize_text_content(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def _extract_title_from_metadata(metadata: object) -> str | None:
    if not isinstance(metadata, dict):
        return None
    title = metadata.get("title")
    if isinstance(title, str):
        normalized = title.strip()
        if normalized:
            return normalized
    return None


def _extract_html_title(html_text: str) -> str | None:
    try:
        from lxml import html as lxml_html  # type: ignore[import-not-found]

        root = lxml_html.fromstring(html_text)
        title_nodes = root.xpath("//title/text()")
    except Exception:
        return None

    if not title_nodes:
        return None
    title = str(title_nodes[0]).strip()
    return title or None


def _ensure_document_has_content(
    doc: ParsedDocument,
    *,
    empty_error_code: str,
) -> None:
    text_ok = bool(doc.text and doc.text.strip())
    chunk_ok = any(
        bool(chunk.text and chunk.text.strip()) for chunk in (doc.chunks or [])
    )
    if text_ok or chunk_ok:
        return
    raise ParseError(error_code=empty_error_code, message="解析结果为空")


def _finalize_document(
    doc: ParsedDocument,
    *,
    payload: UrlFetchResult,
    strategy_name: str,
    failures: list[tuple[str, ParseError]],
) -> ParsedDocument:
    metadata = dict(doc.metadata) if isinstance(doc.metadata, dict) else {}
    title = _extract_title_from_metadata(metadata)
    title_source = strategy_name if title is not None else "none"
    if title is None:
        html_title = _extract_html_title(payload.html_text)
        if html_title:
            metadata["title"] = html_title
            title = html_title
            title_source = "html_title"

    metadata["url_extract_path"] = strategy_name
    metadata["url_extract_fallback_used"] = bool(failures)
    metadata["url_http_status"] = payload.status_code
    metadata["url_final_url"] = payload.final_url
    metadata["url_title_source"] = title_source
    if failures:
        first_failure = failures[0][1]
        metadata["url_primary_error_code"] = first_failure.error_code
        metadata["url_primary_error_message"] = first_failure.message

    locator = dict(doc.locator) if isinstance(doc.locator, dict) else {}
    locator.setdefault("url", payload.final_url)

    doc.locator = locator
    doc.metadata = metadata
    return doc


async def create_url_crawler(*, settings: Settings) -> UrlCrawler:
    try:
        from crawl4ai import (  # type: ignore[import-not-found]
            AsyncWebCrawler,
            BrowserConfig,
            CacheMode,
            CrawlerRunConfig,
            DefaultMarkdownGenerator,
            PruningContentFilter,
        )
    except Exception as exc:  # pragma: no cover
        raise ParseError(
            error_code="CRAWL4AI_NOT_INSTALLED",
            message="未安装 crawl4ai，无法进行浏览器 URL 抓取",
            details={"error": str(exc)},
        ) from exc

    timeout_ms = max(
        int(getattr(settings, "ingestion_url_timeout_seconds", 25.0) * 1000),
        1000,
    )
    user_agent = getattr(
        settings, "ingestion_url_user_agent", "multi-kb-agent/ingestion"
    )
    browser_config = BrowserConfig(headless=True, user_agent=user_agent)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        page_timeout=timeout_ms,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilter()
        ),
    )
    crawler = AsyncWebCrawler(config=browser_config)
    await crawler.__aenter__()
    return _Crawl4AiCrawler(crawler=crawler, run_config=run_config)


async def close_url_crawler(crawler: UrlCrawler | None) -> None:
    if crawler is None:
        return
    try:
        await crawler.aclose()
    except Exception:  # pragma: no cover - best effort
        return


async def _ensure_final_url_safe(
    *,
    payload: UrlFetchResult,
    settings: Settings,
) -> str:
    guard = build_url_ingestion_guard(settings)
    try:
        return await guard.validate_navigation_url(payload.final_url)
    except AppError as exc:
        details = dict(exc.details or {})
        details.setdefault("url", payload.final_url)
        details.setdefault("requested_url", payload.requested_url)
        details.setdefault("reason_code", exc.code)
        raise ParseError(
            error_code="URL_FINAL_URL_BLOCKED",
            message="最终 URL 被安全策略拦截",
            details=details or None,
        ) from exc

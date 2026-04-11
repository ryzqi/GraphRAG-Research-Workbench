"""网页搜索工具参数契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WebSearchArgs(BaseModel):
    """网页搜索参数。"""

    query: str = Field(..., description="搜索查询")
    max_results: int | None = Field(
        default=None, ge=1, le=20, description="最大结果数（默认走配置）"
    )
    search_type: Literal["general", "news", "finance", "academic"] = Field(
        default="general", description="搜索类型（general/news/finance/academic）"
    )
    search_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="搜索深度（basic/advanced）"
    )
    time_range: str | None = Field(
        default=None, description="时间范围（day/week/month/year）"
    )
    include_domains: list[str] | None = Field(
        default=None, description="仅包含域名列表"
    )
    exclude_domains: list[str] | None = Field(default=None, description="排除域名列表")
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_answer: bool | Literal["basic", "advanced"] | None = Field(
        default=None, description="是否返回答案（可选 basic/advanced）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_image_descriptions: bool | None = Field(
        default=None, description="是否返回图片描述"
    )
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")
    auto_parameters: bool | None = Field(
        default=None, description="是否启用自动参数优化"
    )


class JinaReadArgs(BaseModel):
    """Jina 页面读取参数。"""

    url: str = Field(..., description="要读取的绝对 URL")


class WebExtractArgs(BaseModel):
    """网页抽取参数。"""

    urls: list[str] = Field(..., description="目标 URL 列表")
    extract_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="抽取深度（basic/advanced）"
    )
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")


class WebCrawlArgs(BaseModel):
    """网页爬取参数。"""

    url: str = Field(..., description="起始 URL")
    limit: int | None = Field(default=None, ge=1, le=100, description="最大抓取数量")
    max_depth: int | None = Field(default=None, ge=1, le=10, description="最大深度")
    max_breadth: int | None = Field(default=None, ge=1, le=100, description="最大广度")
    select_paths: list[str] | None = Field(default=None, description="包含路径前缀")
    exclude_paths: list[str] | None = Field(default=None, description="排除路径前缀")
    select_domains: list[str] | None = Field(default=None, description="包含域名列表")
    exclude_domains: list[str] | None = Field(default=None, description="排除域名列表")
    extract_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="抽取深度（basic/advanced）"
    )
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")


class WebResearchArgs(BaseModel):
    """网页研究参数。"""

    query: str = Field(..., description="研究问题")
    search_depth: Literal["basic", "advanced"] | None = Field(
        default=None, description="搜索深度（basic/advanced）"
    )
    max_results: int | None = Field(default=None, ge=1, le=50, description="最大结果数")
    time_range: str | None = Field(
        default=None, description="时间范围（day/week/month/year）"
    )
    topic: Literal["general", "news", "finance"] | None = Field(
        default=None, description="研究主题（general/news/finance）"
    )
    include_domains: list[str] | None = Field(
        default=None, description="仅包含域名列表"
    )
    exclude_domains: list[str] | None = Field(default=None, description="排除域名列表")
    include_raw_content: bool | Literal["markdown", "text"] | None = Field(
        default=None, description="是否返回原文（可选 markdown/text）"
    )
    include_answer: bool | Literal["basic", "advanced"] | None = Field(
        default=None, description="是否返回答案（可选 basic/advanced）"
    )
    include_images: bool | None = Field(default=None, description="是否返回图片")
    include_image_descriptions: bool | None = Field(
        default=None, description="是否返回图片描述"
    )
    include_favicon: bool | None = Field(
        default=None, description="是否返回站点 favicon"
    )
    include_usage: bool | None = Field(default=None, description="是否返回用量")
    auto_parameters: bool | None = Field(
        default=None, description="是否启用自动参数优化"
    )
    output_format: Literal["report", "structured"] | None = Field(
        default=None, description="输出格式（report/structured）"
    )
    output_schema: dict | str | None = Field(
        default=None, description="结构化输出 schema（JSON）"
    )
    citation_format: Literal["numbered", "mla", "apa", "chicago"] | None = Field(
        default=None, description="引用格式（numbered/mla/apa/chicago）"
    )
    model: str | None = Field(default=None, description="研究模型")
    stream: bool | None = Field(default=None, description="是否启用流式输出")
    poll_interval_seconds: float | None = Field(
        default=None, ge=0, description="轮询间隔（秒）"
    )

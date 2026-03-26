"""网页搜索 provider 适配层。"""

from .base import (
    NormalizedSearchResult,
    ProviderSearchReport,
    ProviderSearchResponse,
    SearchProviderName,
    build_provider_error,
    canonicalize_url,
    extract_domain,
)

__all__ = [
    "SearchProviderName",
    "NormalizedSearchResult",
    "ProviderSearchReport",
    "ProviderSearchResponse",
    "build_provider_error",
    "canonicalize_url",
    "extract_domain",
]

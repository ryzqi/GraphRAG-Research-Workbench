"""Helpers for contextual generation with retry/fallback semantics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.services.contextual_embedding_service import ContextualEmbeddingService


@dataclass(slots=True)
class ContextGenerationResult:
    context: str
    status: str
    error: str | None
    attempts: int


async def _generate_context_with_retry(
    *,
    full_text: str,
    chunk_text: str,
    context_service: ContextualEmbeddingService,
    enabled: bool,
    max_tokens: int,
    max_attempts: int,
) -> ContextGenerationResult:
    if not enabled:
        return ContextGenerationResult(
            context="",
            status="not_enabled",
            error=None,
            attempts=0,
        )

    last_error: str | None = None
    attempts = 0
    for attempt in range(1, max(max_attempts, 1) + 1):
        attempts = attempt
        try:
            result = await context_service.generate(
                full_text=full_text,
                chunk=chunk_text,
                enabled=enabled,
                max_tokens=max_tokens,
            )
            if result.success and result.context.strip():
                return ContextGenerationResult(
                    context=result.context,
                    status="success",
                    error=None,
                    attempts=attempt,
                )
            last_error = result.reason or "empty_output"
        except Exception as exc:  # pragma: no cover - defensive
            last_error = str(exc)

        if attempt < max_attempts:
            await asyncio.sleep(min(0.15 * attempt, 0.5))

    error = last_error or "context_generation_failed"
    return ContextGenerationResult(
        context="",
        status="fallback",
        error=error,
        attempts=attempts,
    )


async def generate_contexts_for_chunks(
    *,
    full_text: str,
    chunk_texts: list[str],
    context_service: ContextualEmbeddingService,
    enabled: bool,
    max_tokens: int,
    concurrency: int,
    max_attempts: int = 3,
) -> list[ContextGenerationResult]:
    if not chunk_texts:
        return []

    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _worker(text: str) -> ContextGenerationResult:
        async with semaphore:
            return await _generate_context_with_retry(
                full_text=full_text,
                chunk_text=text,
                context_service=context_service,
                enabled=enabled,
                max_tokens=max_tokens,
                max_attempts=max_attempts,
            )

    return await asyncio.gather(*[_worker(text) for text in chunk_texts])

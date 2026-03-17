from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import StrEnum
import random
import time

import httpx

from app.core.settings import get_settings

_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_OPTIONAL_STAGES = {
    "semantic_cache_lookup",
    "semantic_cache_write",
    "hyde",
    "dedupe",
    "diversity",
}
_BATCH_STAGES = {
    "ingestion",
    "index_rebuild",
    "research",
    "chunking",
}


class EmbeddingDimensionMismatchError(RuntimeError):
    """Raised when the provider returns a vector size that does not match config."""


class EmbeddingCallStage(StrEnum):
    DEFAULT = "default"
    QUERY_MAIN = "query_main"
    QUERY_VARIANT = "query_variant"
    SEMANTIC_CACHE_LOOKUP = "semantic_cache_lookup"
    SEMANTIC_CACHE_WRITE = "semantic_cache_write"
    HYDE = "hyde"
    DEDUPE = "dedupe"
    DIVERSITY = "diversity"
    INGESTION = "ingestion"
    INDEX_REBUILD = "index_rebuild"
    RESEARCH = "research"
    CHUNKING = "chunking"


@dataclass(slots=True, frozen=True)
class EmbeddingCallPolicy:
    stage: EmbeddingCallStage
    timeout_seconds: float
    max_retries: int
    retryable_status_codes: frozenset[int]
    breaker_bucket: str
    breaker_failure_threshold: int
    breaker_open_seconds: float
    retry_base_delay_seconds: float
    retry_jitter_ratio: float
    allow_short_circuit_when_open: bool


class EmbeddingCallError(RuntimeError):
    def __init__(
        self,
        *,
        stage: EmbeddingCallStage,
        status_code: int | None,
        retryable: bool,
        attempts: int,
        batch_size: int,
        input_chars: int,
        breaker_state: str,
        message: str | None = None,
        short_circuited: bool = False,
    ) -> None:
        self.stage = stage
        self.status_code = status_code
        self.retryable = retryable
        self.attempts = attempts
        self.batch_size = batch_size
        self.input_chars = input_chars
        self.breaker_state = breaker_state
        self.short_circuited = short_circuited
        default_message = (
            "Embedding 调用失败: "
            f"stage={stage}, status_code={status_code}, retryable={retryable}, "
            f"attempts={attempts}, breaker_state={breaker_state}"
        )
        super().__init__(message or default_message)


@dataclass(slots=True)
class _CircuitBreakerState:
    failure_count: int = 0
    opened_until_monotonic: float | None = None

    def current_state(self, *, now: float) -> str:
        opened_until = self.opened_until_monotonic
        if opened_until is None:
            return "closed"
        if now < opened_until:
            return "open"
        return "half_open"

    def on_success(self) -> None:
        self.failure_count = 0
        self.opened_until_monotonic = None

    def on_failure(
        self,
        *,
        now: float,
        failure_threshold: int,
        open_seconds: float,
    ) -> None:
        if self.current_state(now=now) == "half_open":
            self.failure_count = max(1, failure_threshold)
            self.opened_until_monotonic = now + max(0.0, open_seconds)
            return
        self.failure_count += 1
        if self.failure_count >= max(1, failure_threshold):
            self.opened_until_monotonic = now + max(0.0, open_seconds)


class EmbeddingClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        settings=None,
    ) -> None:
        settings = settings or get_settings()
        self._settings = settings
        self._http_client = http_client
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._expected_dim = settings.embedding_dim
        self._breaker_states: dict[str, _CircuitBreakerState] = {}

    def _validate_embedding_dimensions(self, embeddings: list[list[float]]) -> None:
        expected_dim = self._expected_dim
        if expected_dim is None:
            return
        for embedding in embeddings:
            actual_dim = len(embedding)
            if actual_dim != expected_dim:
                raise EmbeddingDimensionMismatchError(
                    "Embedding 维度与配置不一致: "
                    f"model={self._model}, expected={expected_dim}, actual={actual_dim}. "
                    "请检查 EMBEDDING_DIM、EMBEDDING_MODEL 与向量库 schema 是否一致。"
                )

    def _coerce_stage(
        self, stage: EmbeddingCallStage | str | None
    ) -> EmbeddingCallStage:
        if isinstance(stage, EmbeddingCallStage):
            return stage
        if stage is None:
            return EmbeddingCallStage.DEFAULT
        normalized = str(stage).strip().lower()
        try:
            return EmbeddingCallStage(normalized)
        except ValueError:
            return EmbeddingCallStage.DEFAULT

    def _policy_for_stage(
        self,
        *,
        stage: EmbeddingCallStage,
        timeout_seconds: float | None,
        policy: EmbeddingCallPolicy | None,
    ) -> EmbeddingCallPolicy:
        if policy is not None:
            if timeout_seconds is None:
                return policy
            return replace(policy, timeout_seconds=float(timeout_seconds))

        stage_value = str(stage)
        breaker_bucket = "realtime_query"
        allow_short_circuit_when_open = False
        if stage_value in _OPTIONAL_STAGES:
            breaker_bucket = "online_optional"
            allow_short_circuit_when_open = True
        elif stage_value in _BATCH_STAGES:
            breaker_bucket = "batch_offline"

        timeout_value = (
            float(self._settings.embedding_timeout_seconds)
            if timeout_seconds is None
            else float(timeout_seconds)
        )

        return EmbeddingCallPolicy(
            stage=stage,
            timeout_seconds=timeout_value,
            max_retries=max(0, int(self._settings.embedding_retry_max_retries)),
            retryable_status_codes=_RETRYABLE_STATUS_CODES,
            breaker_bucket=breaker_bucket,
            breaker_failure_threshold=max(
                1, int(self._settings.embedding_breaker_failure_threshold)
            ),
            breaker_open_seconds=max(
                0.0, float(self._settings.embedding_breaker_open_seconds)
            ),
            retry_base_delay_seconds=max(
                0.0, float(self._settings.embedding_retry_base_delay_seconds)
            ),
            retry_jitter_ratio=max(
                0.0, float(self._settings.embedding_retry_jitter_ratio)
            ),
            allow_short_circuit_when_open=allow_short_circuit_when_open,
        )

    def _breaker_state_for_policy(
        self, policy: EmbeddingCallPolicy
    ) -> _CircuitBreakerState:
        bucket = policy.breaker_bucket
        if bucket not in self._breaker_states:
            self._breaker_states[bucket] = _CircuitBreakerState()
        return self._breaker_states[bucket]

    @staticmethod
    def _status_code_from_exc(exc: Exception) -> int | None:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            return int(exc.response.status_code)
        return None

    def _is_retryable_exc(
        self, exc: Exception, *, policy: EmbeddingCallPolicy
    ) -> bool:
        if isinstance(exc, EmbeddingDimensionMismatchError):
            return False
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = self._status_code_from_exc(exc)
            return status_code in policy.retryable_status_codes
        return isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.ProtocolError,
                httpx.TransportError,
            ),
        )

    def _build_call_error(
        self,
        *,
        policy: EmbeddingCallPolicy,
        attempts: int,
        texts: list[str],
        status_code: int | None,
        retryable: bool,
        breaker_state: str,
        short_circuited: bool = False,
    ) -> EmbeddingCallError:
        return EmbeddingCallError(
            stage=policy.stage,
            status_code=status_code,
            retryable=retryable,
            attempts=attempts,
            batch_size=len(texts),
            input_chars=sum(len(text) for text in texts),
            breaker_state=breaker_state,
            short_circuited=short_circuited,
        )

    def _retry_delay_seconds(self, *, attempt: int, policy: EmbeddingCallPolicy) -> float:
        delay = policy.retry_base_delay_seconds * (2 ** max(0, attempt - 1))
        jitter_ratio = policy.retry_jitter_ratio
        if delay <= 0 or jitter_ratio <= 0:
            return delay
        return delay * (1 + random.random() * jitter_ratio)

    async def _call_with_policy(
        self,
        *,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        texts: list[str],
        policy: EmbeddingCallPolicy,
    ) -> list[list[float]]:
        breaker = self._breaker_state_for_policy(policy)
        now = time.monotonic()
        breaker_state = breaker.current_state(now=now)
        if breaker_state == "open" and policy.allow_short_circuit_when_open:
            raise self._build_call_error(
                policy=policy,
                attempts=0,
                texts=texts,
                status_code=None,
                retryable=True,
                breaker_state="open",
                short_circuited=True,
            )

        max_attempts = max(1, policy.max_retries + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=policy.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                embeddings = [item["embedding"] for item in data["data"]]
                self._validate_embedding_dimensions(embeddings)
                breaker.on_success()
                return embeddings
            except EmbeddingDimensionMismatchError:
                raise
            except Exception as exc:
                retryable = self._is_retryable_exc(exc, policy=policy)
                if retryable:
                    breaker.on_failure(
                        now=time.monotonic(),
                        failure_threshold=policy.breaker_failure_threshold,
                        open_seconds=policy.breaker_open_seconds,
                    )
                error = self._build_call_error(
                    policy=policy,
                    attempts=attempt,
                    texts=texts,
                    status_code=self._status_code_from_exc(exc),
                    retryable=retryable,
                    breaker_state=breaker.current_state(now=time.monotonic()),
                )
                if (not retryable) or attempt >= max_attempts:
                    raise error from exc
                delay = self._retry_delay_seconds(attempt=attempt, policy=policy)
                await asyncio.sleep(delay)

        raise RuntimeError("unreachable")  # pragma: no cover

    async def embed(
        self,
        *,
        texts: list[str],
        timeout_seconds: float | None = None,
        stage: EmbeddingCallStage | str | None = None,
        policy: EmbeddingCallPolicy | None = None,
    ) -> list[list[float]]:
        normalized_stage = self._coerce_stage(stage)
        call_policy = self._policy_for_stage(
            stage=normalized_stage,
            timeout_seconds=timeout_seconds,
            policy=policy,
        )
        url = f"{self._base_url}/embeddings"
        payload: dict[str, object] = {"model": self._model, "input": texts}
        if self._expected_dim is not None:
            payload["dimensions"] = self._expected_dim
        headers = {"Authorization": f"Bearer {self._api_key}"}

        if self._http_client is not None:
            return await self._call_with_policy(
                client=self._http_client,
                url=url,
                payload=payload,
                headers=headers,
                texts=texts,
                policy=call_policy,
            )

        async with httpx.AsyncClient(timeout=call_policy.timeout_seconds) as client:
            return await self._call_with_policy(
                client=client,
                url=url,
                payload=payload,
                headers=headers,
                texts=texts,
                policy=call_policy,
            )

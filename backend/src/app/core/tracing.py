"""OpenTelemetry 追踪模块。

提供分布式追踪功能，支持 Agent 执行、LLM 调用和节点追踪。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# 延迟导入 OpenTelemetry，避免未安装时报错
_tracer = None
_initialized = False


def init_tracing() -> None:
    """初始化 OpenTelemetry 追踪。"""
    global _tracer, _initialized

    if _initialized:
        return

    settings = get_settings()
    if not getattr(settings, "otel_enabled", False):
        logger.info("OpenTelemetry 追踪未启用")
        _initialized = True
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": getattr(
                    settings, "otel_service_name", "multi-kb-agent"
                ),
                "service.version": "0.1.0",
            }
        )

        provider = TracerProvider(resource=resource)

        endpoint = getattr(settings, "otel_endpoint", None)
        if endpoint:
            exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(__name__)
        _initialized = True
        logger.info("OpenTelemetry 追踪已初始化")

    except ImportError:
        logger.warning("OpenTelemetry 未安装，追踪功能不可用")
        _initialized = True


def get_tracer():
    """获取 Tracer（如果可用）。"""
    global _tracer
    if _tracer is None and not _initialized:
        init_tracing()
    return _tracer


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[Any]:
    """同步追踪 span。"""
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry import trace

    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, str(value))
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise


@asynccontextmanager
async def trace_node(name: str, **attributes: Any) -> AsyncIterator[Any]:
    """追踪节点执行。"""
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry import trace

    with tracer.start_as_current_span(f"node.{name}") as span:
        for key, value in attributes.items():
            span.set_attribute(key, str(value))
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise


@asynccontextmanager
async def trace_llm_call(
    model: str,
    prompt_tokens: int = 0,
    **attributes: Any,
) -> AsyncIterator[Any]:
    """追踪 LLM 调用。"""
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry import trace

    with tracer.start_as_current_span("llm.chat") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.prompt_tokens", prompt_tokens)
        for key, value in attributes.items():
            span.set_attribute(key, str(value))
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise


@asynccontextmanager
async def trace_agent(
    agent_type: str,
    thread_id: str | None = None,
    **attributes: Any,
) -> AsyncIterator[Any]:
    """追踪 Agent 执行。"""
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry import trace

    with tracer.start_as_current_span(f"agent.{agent_type}") as span:
        span.set_attribute("agent.type", agent_type)
        if thread_id:
            span.set_attribute("agent.thread_id", thread_id)
        for key, value in attributes.items():
            span.set_attribute(key, str(value))
        try:
            yield span
            span.set_status(trace.Status(trace.StatusCode.OK))
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise

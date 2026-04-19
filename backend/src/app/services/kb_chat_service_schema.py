from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, cast


from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.integrations.chat_model_factory import get_active_model_identity
from app.schemas.chats import (
    KbChatConfig,
    resolve_kb_chat_config,
)

from app.services.kb_chat_service_contracts import _as_str_dict

logger = logging.getLogger(__name__)
def _build_terminal_event_payload(self, 
    *,
    status: str,
    run_payload: dict[str, Any],
    assistant_message: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    stage_summaries: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    message: str | None = None,
    pending_clarification: dict[str, Any] | None = None,
    source: str = "live",
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "assistant_message": assistant_message,
        "evidence": evidence or [],
        "source": source,
        "cache": cache,
        "stage_summaries": stage_summaries,
        "metrics": metrics,
        "run": run_payload,
    }
    if message is not None:
        payload["message"] = message
    if pending_clarification is not None:
        payload["pending_clarification"] = pending_clarification
    return payload

def _build_graph_schema_payload(self, 
    graph_json: dict[str, Any], config: KbChatConfig
) -> dict[str, Any]:
    del config  # graph schema strictly reflects LangGraph topology + node metadata
    raw_nodes = graph_json.get("nodes") if isinstance(graph_json, dict) else None
    raw_edges = graph_json.get("edges") if isinstance(graph_json, dict) else None

    def _node_order(node: dict[str, Any]) -> int:
        order = node.get("order")
        if isinstance(order, int):
            return order
        return 10_000

    nodes: list[dict[str, Any]] = []
    if isinstance(raw_nodes, list):
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                continue
            node_id = raw_node.get("id")
            if not isinstance(node_id, str):
                continue
            if node_id in {"__start__", "__end__"}:
                continue
            metadata = (
                raw_node.get("metadata")
                if isinstance(raw_node.get("metadata"), dict)
                else {}
            )
            normalized_metadata = _as_str_dict(metadata)
            label = normalized_metadata.get("label")
            phase = normalized_metadata.get("phase")
            order = normalized_metadata.get("order")
            nodes.append(
                {
                    "id": node_id,
                    "label": label
                    if isinstance(label, str) and label.strip()
                    else node_id,
                    "phase": phase if isinstance(phase, str) else None,
                    "order": order if isinstance(order, int) else None,
                    "metadata": normalized_metadata,
                }
            )

    nodes.sort(key=lambda node: (_node_order(node), str(node.get("id") or "")))

    edges: list[dict[str, Any]] = []
    if isinstance(raw_edges, list):
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            source = raw_edge.get("source")
            target = raw_edge.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            if source in {"__start__", "__end__"} or target in {
                "__start__",
                "__end__",
            }:
                continue
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "conditional": bool(raw_edge.get("conditional", False)),
                }
            )

    node_order_index = {
        node["id"]: idx
        for idx, node in enumerate(nodes)
        if isinstance(node.get("id"), str)
    }
    edges.sort(
        key=lambda edge: (
            node_order_index.get(edge["source"], 10_000),
            node_order_index.get(edge["target"], 10_000),
            edge["source"],
            edge["target"],
            edge["conditional"],
        )
    )

    hash_source = {
        "version": "1.1",
        "nodes": nodes,
        "edges": edges,
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            hash_source, ensure_ascii=False, sort_keys=True, default=str
        ).encode("utf-8")
    ).hexdigest()

    return {"version": "1.1", "hash": payload_hash, "nodes": nodes, "edges": edges}

def _build_drawable_graph_from_builder(self, graph: object) -> dict[str, Any]:
    builder = getattr(graph, "_graph_builder", None)
    if builder is None:
        raise RuntimeError("KB Chat graph builder is unavailable")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, bool]] = set()
    seen_builders: set[int] = set()

    def append_edge(source: Any, target: Any, *, conditional: bool) -> None:
        if not isinstance(source, str) or not isinstance(target, str):
            return
        if source in {"__start__", "__end__"} or target in {"__start__", "__end__"}:
            return
        identity = (source, target, conditional)
        if identity in seen_edges:
            return
        seen_edges.add(identity)
        edges.append(
            {
                "source": source,
                "target": target,
                "conditional": conditional,
            }
        )

    def collect_from_builder(current_builder: object) -> None:
        builder_id = id(current_builder)
        if builder_id in seen_builders:
            return
        seen_builders.add(builder_id)

        for node_id, node_spec in getattr(current_builder, "nodes", {}).items():
            if not isinstance(node_id, str) or node_id in {"__start__", "__end__"}:
                continue
            if node_id not in seen_nodes:
                metadata = getattr(node_spec, "metadata", None)
                nodes.append(
                    {
                        "id": node_id,
                        "metadata": metadata if isinstance(metadata, dict) else {},
                    }
                )
                seen_nodes.add(node_id)

        for source, target in getattr(current_builder, "edges", set()):
            append_edge(source, target, conditional=False)

        for source, branch_map in getattr(current_builder, "branches", {}).items():
            if not isinstance(branch_map, dict):
                continue
            for branch_spec in branch_map.values():
                ends = getattr(branch_spec, "ends", None)
                if isinstance(ends, dict):
                    for target in ends.values():
                        append_edge(source, target, conditional=True)

        for node_spec in getattr(current_builder, "nodes", {}).values():
            runnable = getattr(node_spec, "runnable", None)
            nested_builder = getattr(runnable, "builder", None)
            if nested_builder is not None:
                collect_from_builder(nested_builder)

    collect_from_builder(builder)
    nodes.sort(
        key=lambda node: (
            int(node.get("metadata", {}).get("order"))
            if isinstance(node.get("metadata"), dict)
            and isinstance(node["metadata"].get("order"), int)
            else 10_000,
            str(node.get("id") or ""),
        )
    )
    node_order_index = {
        str(node.get("id")): index
        for index, node in enumerate(nodes)
        if isinstance(node.get("id"), str)
    }
    edges.sort(
        key=lambda edge: (
            node_order_index.get(edge["source"], 10_000),
            node_order_index.get(edge["target"], 10_000),
            edge["source"],
            edge["target"],
            edge["conditional"],
        )
    )
    return {"nodes": nodes, "edges": edges}

def _build_drawable_graph_from_compiled_xray(self, 
    graph: object, compiled_graph: dict[str, Any]
) -> dict[str, Any]:
    root_builder = getattr(graph, "_graph_builder", None)
    root_metadata_by_node: dict[str, dict[str, Any]] = {}
    if root_builder is not None:
        for node_id, node_spec in getattr(root_builder, "nodes", {}).items():
            if not isinstance(node_id, str) or node_id in {"__start__", "__end__"}:
                continue
            metadata = getattr(node_spec, "metadata", None)
            root_metadata_by_node[node_id] = (
                dict(metadata) if isinstance(metadata, dict) else {}
            )

    wrapper_node_ids = {
        "preprocess_subgraph",
        "retrieval_subgraph",
        "answer_subgraph",
    }
    nodes_by_id: dict[str, dict[str, Any]] = {}
    seen_edges: set[tuple[str, str, bool]] = set()
    edges: list[dict[str, Any]] = []

    def split_node_id(node_id: str) -> tuple[str | None, str]:
        prefix, separator, suffix = node_id.partition(":")
        if separator and prefix in wrapper_node_ids and suffix:
            return prefix, suffix
        return None, node_id

    def append_node(node_id: str, metadata: dict[str, Any] | None) -> None:
        if not node_id or node_id in {"__start__", "__end__"}:
            return
        normalized_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        existing = nodes_by_id.get(node_id)
        if existing is None:
            nodes_by_id[node_id] = {"id": node_id, "metadata": normalized_metadata}
            return
        existing_metadata = _as_str_dict(existing.get("metadata"))
        for key, value in normalized_metadata.items():
            if key not in existing_metadata:
                existing_metadata[key] = value
        existing["metadata"] = existing_metadata

    def append_edge(source: str, target: str, *, conditional: bool) -> None:
        if (
            not source
            or not target
            or source in {"__start__", "__end__"}
            or target in {"__start__", "__end__"}
            or source == target
            or source not in nodes_by_id
            or target not in nodes_by_id
        ):
            return
        identity = (source, target, conditional)
        if identity in seen_edges:
            return
        seen_edges.add(identity)
        edges.append(
            {
                "source": source,
                "target": target,
                "conditional": conditional,
            }
        )

    raw_nodes = (
        compiled_graph.get("nodes") if isinstance(compiled_graph, dict) else None
    )
    if isinstance(raw_nodes, list):
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                continue
            raw_node_id = raw_node.get("id")
            if not isinstance(raw_node_id, str):
                continue
            _, node_id = split_node_id(raw_node_id)
            metadata = (
                raw_node.get("metadata")
                if isinstance(raw_node.get("metadata"), dict)
                else None
            )
            append_node(node_id, metadata)

    for node_id, metadata in root_metadata_by_node.items():
        if node_id in wrapper_node_ids or node_id in nodes_by_id:
            append_node(node_id, metadata)

    raw_edges = (
        compiled_graph.get("edges") if isinstance(compiled_graph, dict) else None
    )
    if isinstance(raw_edges, list):
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            raw_source = raw_edge.get("source")
            raw_target = raw_edge.get("target")
            if not isinstance(raw_source, str) or not isinstance(raw_target, str):
                continue
            if raw_source == "__start__" or raw_target == "__end__":
                continue
            source_wrapper, source_node_id = split_node_id(raw_source)
            target_wrapper, target_node_id = split_node_id(raw_target)
            if (
                source_wrapper
                and target_wrapper
                and source_wrapper == target_wrapper
            ):
                source = source_node_id
                target = target_node_id
            elif source_wrapper is None and target_wrapper is None:
                source = source_node_id
                target = target_node_id
            else:
                source = source_wrapper or source_node_id
                target = target_wrapper or target_node_id
            append_edge(
                source,
                target,
                conditional=bool(raw_edge.get("conditional", False)),
            )

    nodes = sorted(
        nodes_by_id.values(),
        key=lambda node: (
            int(node.get("metadata", {}).get("order"))
            if isinstance(node.get("metadata"), dict)
            and isinstance(node["metadata"].get("order"), int)
            else 10_000,
            str(node.get("id") or ""),
        ),
    )
    node_order_index = {
        str(node.get("id")): index
        for index, node in enumerate(nodes)
        if isinstance(node.get("id"), str)
    }
    edges.sort(
        key=lambda edge: (
            node_order_index.get(edge["source"], 10_000),
            node_order_index.get(edge["target"], 10_000),
            edge["source"],
            edge["target"],
            edge["conditional"],
        )
    )
    return {"nodes": nodes, "edges": edges}

def _build_schema_drawable_graph(self, graph: object) -> dict[str, Any]:
    try:
        graph_builder = cast(KbChatAgenticGraph, graph)
        compiled_graph = graph_builder.compile().get_graph(xray=True).to_json()
        return self._build_drawable_graph_from_compiled_xray(
            graph_builder, compiled_graph
        )
    except TypeError as exc:
        logger.warning(
            "LangGraph drawable export failed; fallback to builder topology: %s",
            exc,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning(
            "LangGraph drawable export errored; fallback to builder topology: %s",
            exc,
        )

    return self._build_drawable_graph_from_builder(graph)

async def get_graph_schema(
    self,
    *,
    kb_chat_config: KbChatConfig | None = None,
    selected_kb_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    config = resolve_kb_chat_config(raw=kb_chat_config, settings=self._settings)
    default_kb_ids = selected_kb_ids or []
    retrieval_overrides = self._to_retrieval_overrides(config)

    kb_tool = build_kb_retrieve_tool(
        retrieval=self._retrieval,
        default_kb_ids=default_kb_ids,
        retrieval_overrides=retrieval_overrides,
        context_builder=self._context_builder,
        on_results=lambda _included, _meta: None,
    )
    tools, tool_meta_by_name = await build_tool_registry(
        settings=self._settings,
        extensions=None,
        extra_tools=[kb_tool],
        include_web_search=False,
        include_mcp=False,
    )
    chat_model = create_chat_model(
        settings=self._settings,
        use_previous_response_id=False,
    )
    graph = self._build_graph(
        chat_model=chat_model,
        tools=tools,
        tool_meta_by_name=tool_meta_by_name,
        kb_chat_config=config,
    )
    drawable_graph = self._build_schema_drawable_graph(graph)
    return self._build_graph_schema_payload(drawable_graph, config)

def _build_trace_snapshot(
    self,
    *,
    layer_stats: dict[str, Any],
    kb_chat_config: KbChatConfig,
) -> dict[str, Any]:
    """为生产可观测性构建最小且不含敏感信息的快照。"""
    prompt_version = None
    try:
        prompt_version = self._prompts.get("kb_chat/system").version
    except Exception:
        prompt_version = None
    llm_model_identity = None
    try:
        provider, model = get_active_model_identity(settings=self._settings)
        llm_model_identity = f"{provider}/{model}"
    except Exception:
        llm_model_identity = None

    return {
        "config": {
            "graph_recursion_limit": int(
                self._settings.kb_chat_graph_recursion_limit
            ),
            "max_total_rounds": int(self._settings.kb_chat_max_total_rounds),
            "max_retrieval_retries": int(
                self._settings.kb_chat_max_retrieval_retries
            ),
            "max_generation_retries": int(
                self._settings.kb_chat_max_generation_retries
            ),
            "complexity_cache_enabled": bool(
                self._settings.kb_chat_complexity_cache_enabled
            ),
            "complexity_cache_ttl_seconds": int(
                self._settings.kb_chat_complexity_cache_ttl_seconds
            ),
            "retrieval_top_k": int(kb_chat_config.retrieval_top_k),
            "retrieval_rerank_top_k": int(kb_chat_config.retrieval_rerank_top_k),
            "retrieval_hybrid_rrf_k": int(kb_chat_config.retrieval_hybrid_rrf_k),
            "retrieval_parent_max_parents": int(
                kb_chat_config.retrieval_parent_max_parents
            ),
            "retrieval_parent_max_children_per_parent": int(
                kb_chat_config.retrieval_parent_max_children_per_parent
            ),
            "retrieval_multiscale_per_window_top_k": int(
                kb_chat_config.retrieval_multiscale_per_window_top_k
            ),
            "retrieval_multiscale_rrf_k": int(
                kb_chat_config.retrieval_multiscale_rrf_k
            ),
            "retrieval_multiscale_max_documents": int(
                kb_chat_config.retrieval_multiscale_max_documents
            ),
            "retrieval_multiscale_max_chunks_per_document": int(
                kb_chat_config.retrieval_multiscale_max_chunks_per_document
            ),
        },
        "versions": {
            "llm_model": llm_model_identity,
            "embedding_model": self._settings.embedding_model,
            "rerank_model": self._settings.retrieval_rerank_model,
            "kb_chat_system_prompt": prompt_version,
        },
        "retrieval_layer_stats": layer_stats,
    }

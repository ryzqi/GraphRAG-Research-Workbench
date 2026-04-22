"""Deep Research runtime workspace overlay backend。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import RLock

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import (
    _glob_search_files,
    create_file_data,
    grep_matches_from_files,
)
from langgraph.runtime import get_runtime

from app.services.research_workspace_files import build_research_workspace_layout


class WorkspaceSeedRegistry:
    """按 session_id 暴露本轮 Deep Research 的静态 workspace 视图。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._seed_files_by_session: dict[str, dict[str, str]] = {}

    def set(self, *, session_id: str, seed_files: Mapping[str, str]) -> None:
        with self._lock:
            self._seed_files_by_session[session_id] = dict(seed_files)

    def clear(self, *, session_id: str) -> None:
        with self._lock:
            self._seed_files_by_session.pop(session_id, None)

    def get(self, *, session_id: str | None) -> dict[str, str]:
        if not session_id:
            return {}
        with self._lock:
            return dict(self._seed_files_by_session.get(session_id, {}))


def _runtime_session_id() -> str | None:
    try:
        runtime = get_runtime()
    except RuntimeError:
        return None
    context = getattr(runtime, "context", None)
    value = getattr(context, "session_id", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _canonicalize_runtime_path(file_path: str) -> str:
    normalized = str(file_path or "").strip()
    if not normalized:
        return normalized

    session_id = _runtime_session_id()
    if not session_id:
        return normalized

    layout = build_research_workspace_layout(session_id)
    normalized = normalized.replace(
        "/workspace/research/<session>",
        layout.workspace_root,
    )
    normalized = normalized.replace(
        "/scratch/research/<session>",
        layout.scratch_root,
    )

    alias_to_path: dict[str, str] = {}

    def _register_aliases(
        canonical_path: str,
        *,
        session_root: str,
        names: tuple[str, ...],
    ) -> None:
        for name in names:
            alias_to_path[name] = canonical_path
            alias_to_path[f"/{name}"] = canonical_path
            alias_to_path[f"{session_root}/{name}"] = canonical_path

    _register_aliases(
        layout.claim_map_json_path,
        session_root=layout.workspace_root,
        names=(
            "claim-map.json",
            "claim_map.json",
            "04-claim-map.json",
            "04-claim_map.json",
        ),
    )
    _register_aliases(
        layout.evidence_ledger_json_path,
        session_root=layout.workspace_root,
        names=(
            "evidence-ledger.json",
            "evidence_ledger.json",
            "05-evidence-ledger.json",
            "05-evidence_ledger.json",
        ),
    )
    _register_aliases(
        layout.claim_bundles_path,
        session_root=layout.workspace_root,
        names=(
            "claim-bundles.json",
            "claim_bundles.json",
            "07-claim-bundles.json",
            "07-claim_bundles.json",
        ),
    )
    _register_aliases(
        layout.section_briefs_path,
        session_root=layout.workspace_root,
        names=(
            "section-briefs.json",
            "section_briefs.json",
            "08-section-briefs.json",
            "08-section_briefs.json",
        ),
    )
    _register_aliases(
        layout.task_graph_path,
        session_root=layout.workspace_root,
        names=(
            "task-graph.json",
            "task_graph.json",
            "06-task-graph.json",
            "06-task_graph.json",
        ),
    )
    _register_aliases(
        layout.live_board_path,
        session_root=layout.workspace_root,
        names=(
            "live-board.json",
            "live_board.json",
            "09-live-board.json",
            "09-live_board.json",
        ),
    )
    _register_aliases(
        layout.report_outline_path,
        session_root=layout.workspace_root,
        names=(
            "report-outline.md",
            "report_outline.md",
            "03-report-outline.md",
            "03-report_outline.md",
        ),
    )
    _register_aliases(
        layout.report_draft_path,
        session_root=layout.workspace_root,
        names=(
            "report-draft.md",
            "report_draft.md",
            "02-report-draft.md",
            "02-report_draft.md",
        ),
    )
    _register_aliases(
        layout.report_context_json_path,
        session_root=f"{layout.scratch_root}/report",
        names=(
            "report-context.json",
            "report_context.json",
        ),
    )
    _register_aliases(
        layout.evidence_critique_json_path,
        session_root=f"{layout.scratch_root}/critique",
        names=(
            "evidence-critique.json",
            "evidence_critique.json",
        ),
    )
    alias_to_path[f"{layout.scratch_root}/evidence-critique.json"] = (
        layout.evidence_critique_json_path
    )
    alias_to_path[f"{layout.scratch_root}/evidence_critique.json"] = (
        layout.evidence_critique_json_path
    )
    _register_aliases(
        layout.coverage_critique_json_path,
        session_root=f"{layout.scratch_root}/critique",
        names=(
            "coverage-critique.json",
            "coverage_critique.json",
        ),
    )
    alias_to_path[f"{layout.scratch_root}/coverage-critique.json"] = (
        layout.coverage_critique_json_path
    )
    alias_to_path[f"{layout.scratch_root}/coverage_critique.json"] = (
        layout.coverage_critique_json_path
    )
    return alias_to_path.get(normalized, normalized)


@dataclass(slots=True, eq=False)
class WorkspaceSeedBackend(BackendProtocol):
    """为 Deep Research 暴露静态 workspace 文件，并让 runtime 写入覆盖静态底座。"""

    runtime_backend: BackendProtocol
    registry: WorkspaceSeedRegistry = field(default_factory=WorkspaceSeedRegistry)

    def _seed_files(self) -> dict[str, str]:
        return self.registry.get(session_id=_runtime_session_id())

    def ls(self, path: str) -> LsResult:
        path = _canonicalize_runtime_path(path)
        try:
            runtime_result = self.runtime_backend.ls(path)
        except RuntimeError:
            runtime_result = LsResult(entries=[])

        runtime_entries = list(runtime_result.entries or [])
        seen_paths = {entry.get("path", "") for entry in runtime_entries}
        seed_entries: list[FileInfo] = []
        seed_directories: set[str] = set()
        directory = path.rstrip("/")
        prefix = "/" if not directory else directory + "/"
        for seed_path, seed_content in sorted(self._seed_files().items()):
            if seed_path in seen_paths:
                continue
            if directory:
                if not seed_path.startswith(prefix):
                    continue
                remainder = seed_path[len(prefix) :]
            else:
                remainder = seed_path.lstrip("/")
            if not remainder or "/" in remainder:
                child_name = remainder.split("/", 1)[0]
                if child_name:
                    child_path = f"{prefix}{child_name}/"
                    if child_path not in seen_paths:
                        seed_directories.add(child_path)
                continue
            seed_entries.append(
                FileInfo(
                    path=seed_path,
                    is_dir=False,
                    size=len(seed_content),
                    modified_at="",
                )
            )
        directory_entries = [
            FileInfo(path=directory_path, is_dir=True, size=0, modified_at="")
            for directory_path in sorted(seed_directories)
        ]
        return LsResult(entries=[*runtime_entries, *seed_entries, *directory_entries])

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        file_path = _canonicalize_runtime_path(file_path)
        try:
            runtime_result = self.runtime_backend.read(
                file_path,
                offset=offset,
                limit=limit,
            )
        except RuntimeError:
            runtime_result = ReadResult(error="runtime_backend_unavailable")
        if runtime_result.error is None and runtime_result.file_data is not None:
            return runtime_result

        seed_content = self._seed_files().get(file_path)
        if seed_content is None:
            return runtime_result
        return ReadResult(file_data=create_file_data(seed_content))

    def write(self, file_path: str, content: str) -> WriteResult:
        file_path = _canonicalize_runtime_path(file_path)
        return self.runtime_backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        file_path = _canonicalize_runtime_path(file_path)
        return self.runtime_backend.edit(
            file_path,
            old_string,
            new_string,
            replace_all=replace_all,
        )

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        path = _canonicalize_runtime_path(path) if isinstance(path, str) else path
        try:
            runtime_result = self.runtime_backend.grep(pattern, path=path, glob=glob)
        except RuntimeError:
            runtime_result = GrepResult(matches=[])

        runtime_matches = list(runtime_result.matches or [])
        runtime_paths = {match.get("path", "") for match in runtime_matches}
        seed_match_map = grep_matches_from_files(
            {
                path_key: create_file_data(content)
                for path_key, content in self._seed_files().items()
                if path_key not in runtime_paths
            },
            pattern,
            path if path is not None else "/",
            glob,
        )
        seed_matches: list[GrepMatch] = list(seed_match_map.matches or [])
        return GrepResult(matches=[*runtime_matches, *seed_matches])

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        path = _canonicalize_runtime_path(path)
        try:
            runtime_result = self.runtime_backend.glob(pattern, path=path)
        except RuntimeError:
            runtime_result = GlobResult(matches=[])

        runtime_matches = list(runtime_result.matches or [])
        runtime_paths = {entry.get("path", "") for entry in runtime_matches}
        seed_match_text = _glob_search_files(
            {
                path_key: create_file_data(content)
                for path_key, content in self._seed_files().items()
                if path_key not in runtime_paths
            },
            pattern,
            path,
        )
        seed_matches: list[FileInfo] = []
        if seed_match_text != "No files found":
            for seed_path in seed_match_text.splitlines():
                seed_matches.append(
                    FileInfo(
                        path=seed_path,
                        is_dir=False,
                        size=len(self._seed_files()[seed_path]),
                        modified_at="",
                    )
                )
        return GlobResult(matches=[*runtime_matches, *seed_matches])

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return self.runtime_backend.upload_files(files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        canonical_paths = [_canonicalize_runtime_path(path) for path in paths]
        try:
            responses = self.runtime_backend.download_files(canonical_paths)
        except RuntimeError:
            responses = [
                FileDownloadResponse(path=path, content=None, error="file_not_found")
                for path in canonical_paths
            ]
        patched: list[FileDownloadResponse] = []
        seed_files = self._seed_files()
        for requested_path, response in zip(canonical_paths, responses, strict=True):
            if response.error is None or response.content is not None:
                patched.append(response)
                continue
            seed_content = seed_files.get(requested_path)
            if seed_content is None:
                patched.append(response)
                continue
            patched.append(
                FileDownloadResponse(
                    path=requested_path,
                    content=seed_content.encode("utf-8"),
                    error=None,
                )
            )
        return patched


def build_workspace_seed_backend(
    *,
    runtime_backend: BackendProtocol,
    registry: WorkspaceSeedRegistry | None = None,
) -> WorkspaceSeedBackend:
    """构建带静态 seed 文件视图的 backend。"""

    return WorkspaceSeedBackend(
        runtime_backend=runtime_backend,
        registry=registry or WorkspaceSeedRegistry(),
    )

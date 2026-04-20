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


@dataclass(slots=True, eq=False)
class WorkspaceSeedBackend(BackendProtocol):
    """为 Deep Research 暴露静态 workspace 文件，并让 runtime 写入覆盖静态底座。"""

    runtime_backend: BackendProtocol
    registry: WorkspaceSeedRegistry = field(default_factory=WorkspaceSeedRegistry)

    def _seed_files(self) -> dict[str, str]:
        return self.registry.get(session_id=_runtime_session_id())

    def ls(self, path: str) -> LsResult:
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
        return self.runtime_backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
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
        try:
            responses = self.runtime_backend.download_files(paths)
        except RuntimeError:
            responses = [
                FileDownloadResponse(path=path, content=None, error="file_not_found")
                for path in paths
            ]
        patched: list[FileDownloadResponse] = []
        seed_files = self._seed_files()
        for requested_path, response in zip(paths, responses, strict=True):
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

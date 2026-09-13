from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lingshu.errors import ToolExecutionError, WorkspaceSecurityError
from lingshu.observability.redaction import redact_secrets
from lingshu.settings import AppConfig

_IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyright",
    "node_modules",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".codex",
}
_SENSITIVE_FILE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "service-account.json",
    "id_rsa",
    "id_ed25519",
}
_SENSITIVE_FILE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class WorkspaceTools:
    """向模型暴露只读工作区和任务产物写入能力。"""

    def __init__(self, config: AppConfig, workspace: Path, artifact_root: Path) -> None:
        self.config = config
        self.workspace = workspace.expanduser().resolve()
        self.artifact_root = artifact_root.resolve()
        self._ensure_allowed(self.workspace)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [
            self._schema(
                "list_files",
                "列出工作区中的文件，不读取文件内容。",
                {
                    "path": {"type": "string", "description": "相对工作区的目录，默认为 ."},
                },
            ),
            self._schema(
                "read_file",
                "读取工作区内指定文本文件。",
                {
                    "path": {"type": "string", "description": "相对工作区的文件路径"},
                },
                required=["path"],
            ),
            self._schema(
                "search_text",
                "在工作区文本文件中搜索固定文本。",
                {
                    "query": {"type": "string", "description": "要搜索的文本"},
                    "path": {"type": "string", "description": "相对工作区的目录，默认为 ."},
                },
                required=["query"],
            ),
            self._schema(
                "write_artifact",
                "把分析或草稿写入当前任务产物目录，不修改主仓库。",
                {
                    "name": {"type": "string", "description": "不含目录的文件名"},
                    "content": {"type": "string", "description": "产物内容"},
                },
                required=["name", "content"],
            ),
            self._schema(
                "propose_patch",
                "把统一 diff 格式的补丁建议写入任务产物目录，不应用补丁。",
                {
                    "name": {"type": "string", "description": "补丁名称"},
                    "diff": {"type": "string", "description": "统一 diff 内容"},
                },
                required=["name", "diff"],
            ),
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        handlers = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "search_text": self.search_text,
            "write_artifact": self.write_artifact,
            "propose_patch": self.propose_patch,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolExecutionError(f"不允许调用工具：{name}")
        try:
            result = handler(**arguments)
        except TypeError as exc:
            raise ToolExecutionError(f"工具 {name} 的参数不正确") from exc
        return json.dumps(result, ensure_ascii=False)

    def list_files(self, path: str = ".") -> dict[str, Any]:
        root = self._workspace_path(path)
        self._ensure_visible(root, path)
        if not root.is_dir():
            raise ToolExecutionError(f"目录不存在：{path}")
        files: list[str] = []
        truncated = False
        for candidate in root.rglob("*"):
            if self._is_ignored(candidate) or self._is_sensitive(candidate):
                continue
            try:
                if not candidate.is_file() or not self._is_within_workspace(candidate):
                    continue
            except OSError:
                continue
            if len(files) >= self.config.policies.max_listed_files:
                truncated = True
                break
            files.append(candidate.relative_to(self.workspace).as_posix())
        return {"files": files, "truncated": truncated}

    def read_file(self, path: str) -> dict[str, Any]:
        candidate = self._workspace_path(path)
        self._ensure_visible(candidate, path)
        if not candidate.is_file():
            raise ToolExecutionError(f"文件不存在：{path}")
        try:
            content = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError(f"文件不是 UTF-8 文本：{path}") from exc
        except OSError as exc:
            raise ToolExecutionError(f"无法读取文件：{path}") from exc
        maximum = self.config.policies.max_file_chars
        safe_content = redact_secrets(content)
        return {
            "path": candidate.relative_to(self.workspace).as_posix(),
            "content": safe_content[:maximum],
            "truncated": len(safe_content) > maximum,
        }

    def search_text(self, query: str, path: str = ".") -> dict[str, Any]:
        if not query:
            raise ToolExecutionError("搜索文本不能为空")
        root = self._workspace_path(path)
        self._ensure_visible(root, path)
        if not root.exists():
            raise ToolExecutionError(f"搜索路径不存在：{path}")
        candidates = [root] if root.is_file() else root.rglob("*")
        results: list[dict[str, Any]] = []
        scanned = 0
        for candidate in candidates:
            if self._is_ignored(candidate) or self._is_sensitive(candidate):
                continue
            try:
                if not candidate.is_file() or not self._is_within_workspace(candidate):
                    continue
            except OSError:
                continue
            scanned += 1
            if scanned > self.config.policies.max_listed_files:
                return {"results": results, "truncated": True}
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(lines, start=1):
                if query.casefold() in line.casefold():
                    results.append(
                        {
                            "path": candidate.relative_to(self.workspace).as_posix(),
                            "line": line_number,
                            "text": redact_secrets(line)[:500],
                        }
                    )
                    if len(results) >= self.config.policies.max_search_results:
                        return {"results": results, "truncated": True}
        return {"results": results, "truncated": False}

    def write_artifact(self, name: str, content: str) -> dict[str, Any]:
        if len(content) > self.config.policies.max_artifact_chars:
            raise ToolExecutionError(
                f"产物内容超过 {self.config.policies.max_artifact_chars} 字符限制"
            )
        target = self._artifact_path(name)
        try:
            target.write_text(content, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise ToolExecutionError(f"无法写入任务产物：{name}") from exc
        return {"path": str(target), "chars": len(content)}

    def propose_patch(self, name: str, diff: str) -> dict[str, Any]:
        safe_name = name if name.casefold().endswith(".diff") else f"{name}.diff"
        return self.write_artifact(safe_name, diff)

    def _workspace_path(self, relative: str) -> Path:
        candidate = (self.workspace / relative).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise WorkspaceSecurityError(f"路径超出当前工作区：{relative}") from exc
        return candidate

    def _artifact_path(self, name: str) -> Path:
        device_name = name.split(".", maxsplit=1)[0].upper()
        if (
            not name
            or Path(name).name != name
            or name.endswith((".", " "))
            or device_name in _WINDOWS_RESERVED_NAMES
            or len(name) > self.config.policies.artifact_name_max_length
            or not re.fullmatch(r"[\w.\-\u4e00-\u9fff]+", name)
        ):
            raise ToolExecutionError("产物名称不安全或过长")
        target = (self.artifact_root / name).resolve()
        try:
            target.relative_to(self.artifact_root)
        except ValueError as exc:
            raise WorkspaceSecurityError("产物路径超出任务目录") from exc
        return target

    def _ensure_allowed(self, workspace: Path) -> None:
        if not workspace.is_dir():
            raise WorkspaceSecurityError(f"工作区不存在：{workspace}")
        runtime_root = (self.config.project_root / "data").resolve()
        try:
            workspace.relative_to(runtime_root)
        except ValueError:
            pass
        else:
            raise WorkspaceSecurityError("工作区不能位于灵枢运行时数据目录")
        for root in self.config.allowed_workspaces:
            try:
                workspace.relative_to(root)
                return
            except ValueError:
                continue
        allowed = "；".join(str(path) for path in self.config.allowed_workspaces)
        raise WorkspaceSecurityError(f"工作区不在允许范围内：{workspace}；允许范围：{allowed}")

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative_parts = path.relative_to(self.workspace).parts
        except ValueError:
            return True
        if any(part.casefold() in _IGNORED_DIRECTORY_NAMES for part in relative_parts):
            return True

        runtime_root = (self.config.project_root / "data").resolve()
        try:
            runtime_root.relative_to(self.workspace)
            path.resolve().relative_to(runtime_root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_sensitive(path: Path) -> bool:
        name = path.name.casefold()
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            return True
        return name in _SENSITIVE_FILE_NAMES or path.suffix.casefold() in _SENSITIVE_FILE_SUFFIXES

    def _ensure_visible(self, path: Path, display_path: str) -> None:
        if self._is_ignored(path) or self._is_sensitive(path):
            raise WorkspaceSecurityError(f"不允许读取敏感或忽略路径：{display_path}")

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.workspace)
            return True
        except ValueError:
            return False

    @staticmethod
    def _schema(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                    "additionalProperties": False,
                },
            },
        }

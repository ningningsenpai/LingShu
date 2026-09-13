from pathlib import Path

import pytest

from lingshu.errors import ToolExecutionError, WorkspaceSecurityError
from lingshu.settings import load_config
from lingshu.tools import WorkspaceTools


def _tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceTools:
    monkeypatch.delenv("LINGSHU_ALLOWED_WORKSPACES", raising=False)
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root).model_copy(update={"allowed_workspaces": [tmp_path]})
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return WorkspaceTools(config, workspace, tmp_path / "artifacts")


def test_read_and_search_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    (tools.workspace / "hello.py").write_text("print('你好')\n", encoding="utf-8")

    assert "hello.py" in tools.list_files()["files"]
    assert tools.read_file("hello.py")["content"] == "print('你好')\n"
    assert tools.search_text("你好")["results"][0]["line"] == 1


def test_workspace_path_cannot_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path, monkeypatch)

    with pytest.raises(WorkspaceSecurityError, match="超出当前工作区"):
        tools.read_file("../secret.txt")


def test_artifact_name_rejects_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path, monkeypatch)

    with pytest.raises(ToolExecutionError, match="不安全"):
        tools.write_artifact("../result.md", "内容")


def test_patch_is_written_only_to_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = _tools(tmp_path, monkeypatch)
    result = tools.propose_patch("change", "--- a/a.py\n+++ b/a.py\n")

    target = Path(result["path"])
    assert target.parent == tools.artifact_root
    assert target.name == "change.diff"


def test_artifact_size_is_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    tools.config.policies.max_artifact_chars = 3

    with pytest.raises(ToolExecutionError, match="超过"):
        tools.write_artifact("large.md", "1234")


def test_sensitive_files_are_hidden_and_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = _tools(tmp_path, monkeypatch)
    (tools.workspace / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
    (tools.workspace / ".env.example").write_text(
        "API_KEY=accidentally-filled-key\n", encoding="utf-8"
    )

    assert ".env" not in tools.list_files()["files"]
    assert ".env.example" in tools.list_files()["files"]
    assert tools.search_text("secret")["results"] == []
    assert "accidentally-filled-key" not in tools.read_file(".env.example")["content"]
    with pytest.raises(WorkspaceSecurityError, match="敏感"):
        tools.read_file(".env")


def test_sensitive_values_in_source_are_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = _tools(tmp_path, monkeypatch)
    source = tools.workspace / "settings.py"
    source.write_text('API_TOKEN="production-token-value"\n', encoding="utf-8")

    content = tools.read_file("settings.py")["content"]
    result = tools.search_text("production-token-value", "settings.py")["results"][0]

    assert "production-token-value" not in content
    assert "production-token-value" not in result["text"]
    assert "[已隐藏]" in content


def test_project_runtime_data_is_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    tools.config.project_root = tools.workspace
    runtime = tools.workspace / "data" / "tasks" / "old-task"
    runtime.mkdir(parents=True)
    (runtime / "result.md").write_text("历史内容", encoding="utf-8")

    assert "data/tasks/old-task/result.md" not in tools.list_files()["files"]
    with pytest.raises(WorkspaceSecurityError, match="忽略路径"):
        tools.read_file("data/tasks/old-task/result.md")


@pytest.mark.parametrize("name", ["CON", "nul.txt", "LPT1.diff", "result."])
def test_artifact_name_rejects_windows_reserved_names(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = _tools(tmp_path, monkeypatch)

    with pytest.raises(ToolExecutionError, match="不安全"):
        tools.write_artifact(name, "内容")


def test_patch_uses_lf_line_endings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    result = tools.propose_patch("change", "--- a/a.py\n+++ b/a.py\n")

    assert b"\r\n" not in Path(result["path"]).read_bytes()

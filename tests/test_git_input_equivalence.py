from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

from thebigdiffer.context import ApplicationContext, render_application_context
from thebigdiffer.investigator import ClaudeInvestigator, load_primary_prompt
from thebigdiffer.patch import build_patch_presentation, render_primary_input
from thebigdiffer.repository import GitRepositoryPreparer
from thebigdiffer.source import TOOL_CONFIG, SourceRepository


class _ScriptedProvider:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = copy.deepcopy(responses)
        self.requests: list[dict[str, Any]] = []

    def converse(self, **request: Any) -> dict[str, Any]:
        self.requests.append(copy.deepcopy(request))
        return copy.deepcopy(self.responses[len(self.requests) - 1])


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _write_tree(root: Path, *, token: str, added: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    root.joinpath("pkg").mkdir()
    root.joinpath("pkg/module.py").write_text(
        f"TOKEN = {token!r}\n\ndef render(value):\n    return TOKEN + value\n",
        encoding="utf-8",
    )
    root.joinpath("payload.bin").write_bytes(b"\x00exact-binary\xff")
    if added:
        root.joinpath("added.txt").write_text("after only\n", encoding="utf-8")


def _store(before: Path, after: Path) -> SourceRepository:
    return SourceRepository(
        before,
        after,
        max_lines_per_response=200,
        max_retrieved_bytes=128 * 1024,
        search_max_matches=20,
        search_context_lines=2,
    )


def _responses() -> list[dict[str, Any]]:
    return [
        {
            "stopReason": "tool_use",
            "usage": {"inputTokens": 1000, "outputTokens": 100},
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "read-1",
                                "name": "read_source",
                                "input": {
                                    "version": "before",
                                    "path": "pkg/module.py",
                                    "start_line": 1,
                                    "end_line": 4,
                                },
                            }
                        },
                        {
                            "toolUse": {
                                "toolUseId": "search-1",
                                "name": "search_source",
                                "input": {"version": "after", "query": "render"},
                            }
                        },
                        {
                            "toolUse": {
                                "toolUseId": "definition-1",
                                "name": "find_definition",
                                "input": {"version": "before", "identifier": "TOKEN"},
                            }
                        },
                        {
                            "toolUse": {
                                "toolUseId": "references-1",
                                "name": "find_references",
                                "input": {"version": "after", "identifier": "TOKEN"},
                            }
                        },
                    ],
                }
            },
        },
        {
            "stopReason": "end_turn",
            "usage": {"inputTokens": 1800, "outputTokens": 300},
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Equivalent source-grounded report."}],
                }
            },
        },
    ]


def test_git_and_directory_modes_are_model_visible_equivalent(tmp_path: Path) -> None:
    directory_before = tmp_path / "directory-before"
    directory_after = tmp_path / "directory-after"
    _write_tree(directory_before, token="before", added=False)
    _write_tree(directory_after, token="after", added=True)

    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Equivalence Tests")
    _git(repository, "config", "user.email", "equivalence@example.invalid")
    _write_tree(repository, token="before", added=False)
    before_commit = _commit(repository, "before")
    repository.joinpath("pkg/module.py").write_text(
        "TOKEN = 'after'\n\ndef render(value):\n    return TOKEN + value\n",
        encoding="utf-8",
    )
    repository.joinpath("added.txt").write_text("after only\n", encoding="utf-8")
    after_commit = _commit(repository, "after")
    repository.joinpath("pkg/module.py").write_text(
        "TOKEN = 'dirty-working-tree'\n",
        encoding="utf-8",
    )
    repository.joinpath("untracked.txt").write_text("ignored\n", encoding="utf-8")

    context = ApplicationContext(
        repository_type="Python package",
        application_context="This repository implements a Python package.",
        deployment_context="Unknown.",
        provenance="explicitly supplied by the user",
    )

    with GitRepositoryPreparer(repository, before_commit, after_commit).prepare() as prepared:
        directory_store = _store(directory_before, directory_after)
        git_store = _store(prepared.before_directory, prepared.after_directory)
        directory_patch = build_patch_presentation(directory_store, 256 * 1024)
        git_patch = build_patch_presentation(git_store, 256 * 1024)

        assert directory_store.inventory_record() == git_store.inventory_record()
        assert directory_patch == git_patch
        assert render_primary_input(context, directory_patch) == render_primary_input(
            context, git_patch
        )

        calls = [
            (
                "read_source",
                {
                    "version": "before",
                    "path": "pkg/module.py",
                    "start_line": 1,
                    "end_line": 4,
                },
            ),
            ("search_source", {"version": "after", "query": "render"}),
            ("find_definition", {"version": "before", "identifier": "TOKEN"}),
            ("find_references", {"version": "after", "identifier": "TOKEN"}),
        ]
        for name, arguments in calls:
            assert directory_store.execute(name, arguments) == git_store.execute(name, arguments)

        directory_provider = _ScriptedProvider(_responses())
        git_provider = _ScriptedProvider(_responses())
        directory_report = ClaudeInvestigator(
            before_root=directory_before,
            after_root=directory_after,
            output_dir=tmp_path / "directory-output",
            application_context=context,
            provider=directory_provider,
        ).investigate()
        git_report = ClaudeInvestigator(
            before_root=prepared.before_directory,
            after_root=prepared.after_directory,
            output_dir=tmp_path / "git-output",
            application_context=context,
            provider=git_provider,
            source_preparation=prepared.preparation,
        ).investigate()

        assert directory_provider.requests == git_provider.requests
        prompt = load_primary_prompt()
        assert directory_provider.requests[0]["system"] == [{"text": prompt.text}]
        assert directory_provider.requests[0]["toolConfig"] == TOOL_CONFIG
        assert directory_provider.requests[0]["messages"][0]["content"][0]["text"] == (
            render_primary_input(context, directory_patch)
        )
        assert render_application_context(context) in (
            directory_provider.requests[0]["messages"][0]["content"][0]["text"]
        )
        assert directory_report.text == git_report.text
        assert directory_report.patch == git_report.patch
        assert directory_report.tool_config == git_report.tool_config
        assert directory_report.source_inventory == git_report.source_inventory
        assert directory_report.transcript.events == git_report.transcript.events
        assert directory_report.transcript.conversation == git_report.transcript.conversation
        assert directory_report.source_preparation["mode"] == "directory"
        assert git_report.source_preparation["mode"] == "git"

    directory_artifact = json.loads(
        (tmp_path / "directory-output/source-preparation.json").read_text(encoding="utf-8")
    )
    git_artifact = json.loads(
        (tmp_path / "git-output/source-preparation.json").read_text(encoding="utf-8")
    )
    assert directory_artifact["mode"] == "directory"
    assert git_artifact["mode"] == "git"

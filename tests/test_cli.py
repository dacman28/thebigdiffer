from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from thebigdiffer.cli import build_parser, main


class _CliInvestigatorProvider:
    def __init__(self, *, stop_reason: str = "end_turn") -> None:
        self.stop_reason = stop_reason

    def converse(self, **request: Any) -> dict[str, Any]:
        del request
        return {
            "stopReason": self.stop_reason,
            "usage": {"inputTokens": 100, "outputTokens": 20},
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Qualified autonomous research report."}],
                }
            },
        }


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before.joinpath("app.py").write_text("value = 1\n", encoding="utf-8")
    after.joinpath("app.py").write_text("value = 2\n", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "repository_type": "Python package",
                "application_context": "This repository implements a Python package.",
                "deployment_context": "Unknown.",
                "provenance": "explicitly supplied by the user",
            }
        ),
        encoding="utf-8",
    )
    return before, after, context, tmp_path / "investigation"


def _git_inputs(tmp_path: Path) -> tuple[Path, str, str, Path, Path]:
    before, after, context, output = _inputs(tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "-C", str(repository), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "CLI Tests"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "cli@example.invalid"],
        check=True,
    )
    repository.joinpath("app.py").write_bytes(before.joinpath("app.py").read_bytes())
    subprocess.run(["git", "-C", str(repository), "add", "app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "before"],
        check=True,
        capture_output=True,
    )
    before_ref = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    repository.joinpath("app.py").write_bytes(after.joinpath("app.py").read_bytes())
    subprocess.run(["git", "-C", str(repository), "add", "app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "after"],
        check=True,
        capture_output=True,
    )
    after_ref = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repository, before_ref, after_ref, context, output


def test_cli_exposes_only_investigate_command() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert set(subparsers.choices) == {"investigate"}


def test_investigate_cli_writes_production_artifact_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before, after, context, output = _inputs(tmp_path)
    monkeypatch.setattr(
        "thebigdiffer.cli.BedrockClaudeProvider",
        lambda **kwargs: _CliInvestigatorProvider(),
    )

    status = main(
        [
            "investigate",
            "--before",
            str(before),
            "--after",
            str(after),
            "--context",
            str(context),
            "--output",
            str(output),
        ]
    )

    assert status == 0
    assert output.joinpath("research-report.md").read_text(encoding="utf-8") == (
        "Qualified autonomous research report.\n"
    )
    transcript = json.loads(output.joinpath("transcript.json").read_text(encoding="utf-8"))
    assert transcript["identity"]["model_id"] == "us.anthropic.claude-opus-4-6-v1"
    assert transcript["final"]["stop_reason"] == "model_end_turn"
    assert transcript["source_preparation"]["mode"] == "directory"


def test_git_ref_cli_writes_provenance_and_uses_existing_investigator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, before_ref, after_ref, context, output = _git_inputs(tmp_path)
    monkeypatch.setattr(
        "thebigdiffer.cli.BedrockClaudeProvider",
        lambda **kwargs: _CliInvestigatorProvider(),
    )

    status = main(
        [
            "investigate",
            "--repo",
            str(repository),
            "--before-ref",
            before_ref,
            "--after-ref",
            after_ref,
            "--context",
            str(context),
            "--output",
            str(output),
        ]
    )

    assert status == 0
    preparation = json.loads(output.joinpath("source-preparation.json").read_text(encoding="utf-8"))
    assert preparation["mode"] == "git"
    assert preparation["before"]["supplied_ref"] == before_ref
    assert preparation["before"]["resolved_commit_sha"] == before_ref
    assert preparation["after"]["resolved_commit_sha"] == after_ref
    assert preparation["before"]["tree_sha"]
    assert preparation["after"]["tree_sha"]
    assert output.joinpath("research-report.md").is_file()


def test_investigate_cli_rejects_output_inside_source_tree(tmp_path: Path) -> None:
    before, after, context, _ = _inputs(tmp_path)

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "investigate",
                "--before",
                str(before),
                "--after",
                str(after),
                "--context",
                str(context),
                "--output",
                str(before / "output"),
            ]
        )

    assert raised.value.code == 2


def test_investigate_cli_rejects_output_inside_git_repository(tmp_path: Path) -> None:
    repository, before_ref, after_ref, context, _ = _git_inputs(tmp_path)

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "investigate",
                "--repo",
                str(repository),
                "--before-ref",
                before_ref,
                "--after-ref",
                after_ref,
                "--context",
                str(context),
                "--output",
                str(repository / "result"),
            ]
        )

    assert raised.value.code == 2


@pytest.mark.parametrize(
    "source_arguments,error",
    [
        ([], "source input is required"),
        (["--before", "before"], "directory mode requires both"),
        (["--after", "after"], "directory mode requires both"),
        (["--repo", "repo"], "Git mode requires"),
        (["--before-ref", "HEAD^", "--after-ref", "HEAD"], "Git mode requires"),
        (
            ["--repo", "repo", "--before-ref", "HEAD^"],
            "Git mode requires",
        ),
        (
            [
                "--before",
                "before",
                "--after",
                "after",
                "--repo",
                "repo",
                "--before-ref",
                "HEAD^",
                "--after-ref",
                "HEAD",
            ],
            "choose exactly one source-input mode",
        ),
    ],
)
def test_investigate_cli_rejects_incomplete_or_mixed_input_modes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source_arguments: list[str],
    error: str,
) -> None:
    _, _, context, output = _inputs(tmp_path)
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "investigate",
                *source_arguments,
                "--context",
                str(context),
                "--output",
                str(output),
            ]
        )
    assert raised.value.code == 2
    assert error in capsys.readouterr().err


def test_investigate_cli_reports_git_preparation_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, context, output = _inputs(tmp_path)
    not_repository = tmp_path / "not-repository"
    not_repository.mkdir()

    status = main(
        [
            "investigate",
            "--repo",
            str(not_repository),
            "--before-ref",
            "HEAD^",
            "--after-ref",
            "HEAD",
            "--context",
            str(context),
            "--output",
            str(output),
        ]
    )

    assert status == 2
    assert "Git preparation failed" in capsys.readouterr().err


def test_investigate_cli_reports_incomplete_provider_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before, after, context, output = _inputs(tmp_path)
    monkeypatch.setattr(
        "thebigdiffer.cli.BedrockClaudeProvider",
        lambda **kwargs: _CliInvestigatorProvider(stop_reason="max_tokens"),
    )

    status = main(
        [
            "investigate",
            "--before",
            str(before),
            "--after",
            str(after),
            "--context",
            str(context),
            "--output",
            str(output),
        ]
    )

    assert status == 2
    assert "investigation incomplete: model_max_tokens" in capsys.readouterr().err
    assert output.joinpath("transcript.json").is_file()

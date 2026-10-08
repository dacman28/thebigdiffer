from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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


@pytest.mark.parametrize(
    "configuration,error",
    [
        ({"AWS_PROFILE": "nonexistent-audit-profile"}, "nonexistent-audit-profile"),
        ({"AWS_ACCESS_KEY_ID": "fictitious-test-key"}, "AWS_SECRET_ACCESS_KEY"),
    ],
)
def test_cli_sdk_startup_errors_are_actionable_without_tracebacks(
    tmp_path: Path,
    configuration: dict[str, str],
    error: str,
) -> None:
    before, after, context, output = _inputs(tmp_path)
    environment = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "AWS_CONFIG_FILE": str(tmp_path / "absent-config"),
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "absent-credentials"),
        "BOTO_CONFIG": str(tmp_path / "absent-boto-config"),
        "AWS_EC2_METADATA_DISABLED": "true",
        **configuration,
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "thebigdiffer",
            "investigate",
            "--before",
            str(before),
            "--after",
            str(after),
            "--context",
            str(context),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 2
    assert "AWS provider setup failed" in completed.stderr
    assert "AWS SDK credentials/profile configuration" in completed.stderr
    assert error in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "problem,message",
    [
        ("missing-source", "--before"),
        ("file-source", "directory"),
        ("symlink-source", "symlink"),
        ("existing-output", "already exists"),
        ("dangling-output", "already exists"),
        ("file-output-parent", "Not a directory"),
        ("invalid-context", "application context"),
    ],
)
def test_local_errors_are_reported_before_provider_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    problem: str,
    message: str,
) -> None:
    before, after, context, output = _inputs(tmp_path)
    if problem == "missing-source":
        before = tmp_path / "missing"
    elif problem == "file-source":
        before = before / "app.py"
    elif problem == "symlink-source":
        link = tmp_path / "source-link"
        link.symlink_to(before, target_is_directory=True)
        before = link
    elif problem == "existing-output":
        output.mkdir()
    elif problem == "dangling-output":
        output.symlink_to(tmp_path / "absent-output-target")
    elif problem == "file-output-parent":
        parent = tmp_path / "file"
        parent.write_text("file", encoding="utf-8")
        output = parent / "output"
    else:
        context.write_text("{}", encoding="utf-8")

    def unexpected_provider(**kwargs: object) -> None:
        pytest.fail("invalid local inputs must not construct an AWS provider")

    monkeypatch.setattr("thebigdiffer.cli.BedrockClaudeProvider", unexpected_provider)
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
    stderr = capsys.readouterr().err
    assert message in stderr
    assert "Traceback" not in stderr


def test_invalid_context_is_reported_before_git_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before, _, context, output = _inputs(tmp_path)
    context.write_text("{}", encoding="utf-8")

    def unexpected_preparation(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid context must not prepare snapshots")

    monkeypatch.setattr("thebigdiffer.cli.GitRepositoryPreparer", unexpected_preparation)
    status = main(
        [
            "investigate",
            "--repo",
            str(before),
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
    assert "application context" in capsys.readouterr().err


def test_git_workspace_os_error_is_reported_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before, _, context, output = _inputs(tmp_path)

    def fail_preparation(*args: object, **kwargs: object) -> None:
        raise OSError("Cannot create temporary snapshot workspace")

    monkeypatch.setattr("thebigdiffer.cli.GitRepositoryPreparer", fail_preparation)
    status = main(
        [
            "investigate",
            "--repo",
            str(before),
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
    stderr = capsys.readouterr().err
    assert "Git preparation failed: Cannot create temporary snapshot workspace" in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize(
    "provider_stop,expected_stop,expected_status",
    [
        ("end_turn", "model_end_turn", 0),
        ("max_tokens", "model_max_tokens", 2),
        ("transport_error", "model_transport_error_no_retry", 2),
    ],
)
def test_cli_completion_messages_point_to_persisted_status_and_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider_stop: str,
    expected_stop: str,
    expected_status: int,
) -> None:
    before, after, context, output = _inputs(tmp_path)
    calls = 0

    class Provider:
        def converse(self, **request: Any) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if provider_stop == "transport_error":
                raise RuntimeError("Synthetic provider failure")
            return _CliInvestigatorProvider(stop_reason=provider_stop).converse(**request)

    monkeypatch.setattr("thebigdiffer.cli.BedrockClaudeProvider", lambda **kwargs: Provider())
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
    captured = capsys.readouterr()
    assert status == expected_status
    assert calls == 1
    messages = captured.out if status == 0 else captured.err
    assert (captured.err if status == 0 else captured.out) == ""
    assert f"Report: {output / 'research-report.md'}" in messages
    assert f"Status: {expected_stop}" in messages
    assert f"Metrics: {output / 'metrics.json'}" in messages
    if status == 0:
        assert messages.startswith("Investigation complete.\n")
    else:
        assert "investigation incomplete" in messages
        assert f"Transcript/error detail: {output / 'transcript.json'}" in messages
    metrics = json.loads(output.joinpath("metrics.json").read_text(encoding="utf-8"))
    transcript = json.loads(output.joinpath("transcript.json").read_text(encoding="utf-8"))
    assert metrics["stop_reason"] == transcript["final"]["stop_reason"] == expected_stop
    if provider_stop == "transport_error":
        errors = [
            event for event in transcript["events"] if event["type"] == "model_transport_error"
        ]
        assert len(errors) == 1
        assert errors[0]["error"] == "Synthetic provider failure"
        assert errors[0]["retry_attempted"] is False

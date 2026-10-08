"""Command-line entry point for autonomous patch investigation."""

from __future__ import annotations

import argparse
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from thebigdiffer.context import ApplicationContext
from thebigdiffer.ingest import IngestionError
from thebigdiffer.investigator import ClaudeInvestigator, InvestigationConfig
from thebigdiffer.providers import BedrockClaudeProvider
from thebigdiffer.repository import (
    GitPreparationError,
    GitRepositoryPreparer,
    SourcePreparation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thebigdiffer",
        description="Investigate exact source patches with Claude and safe raw-source tools.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    investigate = commands.add_parser(
        "investigate", help="investigate an exact BEFORE/AFTER source patch"
    )
    investigate.add_argument("--before", type=Path, help="prepared BEFORE source directory")
    investigate.add_argument("--after", type=Path, help="prepared AFTER source directory")
    investigate.add_argument("--repo", type=Path, help="local Git repository")
    investigate.add_argument("--before-ref", help="explicit Git ref for the BEFORE snapshot")
    investigate.add_argument("--after-ref", help="explicit Git ref for the AFTER snapshot")
    investigate.add_argument(
        "--context", required=True, type=Path, help="factual application-context JSON"
    )
    investigate.add_argument(
        "--output", required=True, type=Path, help="new investigation artifact directory"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    output: Path = arguments.output
    mode = _source_mode(parser, arguments)
    try:
        context = ApplicationContext.load(arguments.context)
        _validate_output(output)
    except (OSError, ValueError) as error:
        print(f"thebigdiffer: {error}", file=sys.stderr)
        return 2

    if mode == "directory":
        before: Path = arguments.before
        after: Path = arguments.after
        if _overlaps(output, before) or _overlaps(output, after):
            parser.error("--output must not overlap either investigated source tree")
        return _investigate(
            before=before,
            after=after,
            context=context,
            output=output,
            source_preparation=SourcePreparation.directory(),
        )

    repository: Path = arguments.repo
    if _overlaps(output, repository):
        parser.error("--output must not overlap the local Git repository")
    try:
        prepared_repository = GitRepositoryPreparer(
            repository,
            arguments.before_ref,
            arguments.after_ref,
        ).prepare()
        with prepared_repository as prepared:
            if _overlaps(output, prepared.snapshot_root):
                parser.error("--output must not overlap the temporary snapshot workspace")
            return _investigate(
                before=prepared.before_directory,
                after=prepared.after_directory,
                context=context,
                output=output,
                source_preparation=prepared.preparation,
            )
    except (GitPreparationError, OSError) as error:
        print(f"thebigdiffer: Git preparation failed: {error}", file=sys.stderr)
        return 2


def _investigate(
    *,
    before: Path,
    after: Path,
    context: ApplicationContext,
    output: Path,
    source_preparation: SourcePreparation,
) -> int:

    try:
        config = InvestigationConfig()
        _validate_source_directory(before, "--before")
        _validate_source_directory(after, "--after")
        try:
            provider = BedrockClaudeProvider(region_name=config.region_name)
        except (BotoCoreError, ClientError) as error:
            print(
                f"thebigdiffer: AWS provider setup failed: {error}. "
                "Check your AWS SDK credentials/profile configuration and "
                f"Bedrock access in {config.region_name}.",
                file=sys.stderr,
            )
            return 2
        report = ClaudeInvestigator(
            before_root=before,
            after_root=after,
            output_dir=output,
            application_context=context,
            provider=provider,
            config=config,
            source_preparation=source_preparation,
        ).investigate()
    except (IngestionError, OSError, ValueError) as error:
        print(f"thebigdiffer: {error}", file=sys.stderr)
        return 2
    if report.stop_reason != "model_end_turn":
        print(
            f"thebigdiffer: investigation incomplete: {report.stop_reason}",
            file=sys.stderr,
        )
        return 2
    return 0


def _validate_output(output: Path) -> None:
    """Reject obvious output mistakes before preparing sources or AWS state."""
    try:
        output.lstat()
    except FileNotFoundError:
        return
    raise ValueError(f"--output already exists: {output}; choose a new directory")


def _validate_source_directory(root: Path, label: str) -> None:
    """Preflight the root only; safe ingest still performs all authoritative checks."""
    try:
        metadata = root.expanduser().lstat()
    except OSError as error:
        raise IngestionError(f"{label}: cannot inspect source directory {root}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise IngestionError(f"{label}: input root must not be a symlink: {root}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise IngestionError(f"{label}: input root must be a directory: {root}")


def _source_mode(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> str:
    directory_values = (arguments.before, arguments.after)
    git_values = (arguments.repo, arguments.before_ref, arguments.after_ref)
    has_directory = any(value is not None for value in directory_values)
    has_git = any(value is not None for value in git_values)
    if has_directory and has_git:
        parser.error(
            "choose exactly one source-input mode: --before/--after or "
            "--repo/--before-ref/--after-ref"
        )
    if has_directory:
        if any(value is None for value in directory_values):
            parser.error("directory mode requires both --before and --after")
        return "directory"
    if has_git:
        if any(value is None for value in git_values):
            parser.error("Git mode requires --repo, --before-ref, and --after-ref")
        return "git"
    parser.error(
        "source input is required: supply --before/--after or "
        "--repo/--before-ref/--after-ref"
    )


def _overlaps(first: Path, second: Path) -> bool:
    return _inside(first, second) or _inside(second, first)


def _inside(candidate: Path, root: Path) -> bool:
    try:
        candidate.expanduser().resolve(strict=False).relative_to(
            root.expanduser().resolve(strict=False)
        )
    except ValueError:
        return False
    return True

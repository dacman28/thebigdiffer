from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from thebigdiffer import __version__


def test_release_version_matches_project_runtime_and_installed_metadata() -> None:
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    metadata = tomllib.loads(project.read_text(encoding="utf-8"))

    assert metadata["project"]["version"] == __version__ == "2.0.0"
    assert version("thebigdiffer") == __version__

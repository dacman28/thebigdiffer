from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
CURRENT_PACKAGES = {
    "context",
    "ingest",
    "investigator",
    "patch",
    "provenance",
    "providers",
    "repository",
    "reporting",
    "source",
}
ALLOWED_PACKAGE_MODULES = CURRENT_PACKAGES | {"cli"}


def _isolated_import(script: str) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SOURCE_ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def test_package_root_exposes_only_current_metadata() -> None:
    result = _isolated_import(
        "import json; import thebigdiffer; "
        "print(json.dumps({'exports': sorted(thebigdiffer.__all__)}))"
    )

    assert result == {"exports": ["__version__"]}


def test_current_production_imports_load_only_current_package_namespaces() -> None:
    result = _isolated_import(
        "import json, sys; "
        "from thebigdiffer.cli import main; "
        "from thebigdiffer.investigator import ClaudeInvestigator; "
        "from thebigdiffer.source import SourceRepository; "
        "from thebigdiffer.context import ApplicationContext; "
        "loaded = sorted({name.split('.')[1] for name in sys.modules "
        "if name.startswith('thebigdiffer.')}); "
        "print(json.dumps({'loaded': loaded, 'symbols': [main.__name__, "
        "ClaudeInvestigator.__name__, SourceRepository.__name__, "
        "ApplicationContext.__name__]}))"
    )

    assert set(result["loaded"]) <= ALLOWED_PACKAGE_MODULES
    assert result["symbols"] == [
        "main",
        "ClaudeInvestigator",
        "SourceRepository",
        "ApplicationContext",
    ]


def test_current_packages_have_no_imports_outside_current_product() -> None:
    violations: list[str] = []
    package_root = SOURCE_ROOT / "thebigdiffer"
    for package in CURRENT_PACKAGES:
        for path in sorted(package_root.joinpath(package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: tuple[str, ...]
                if isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported = (node.module,)
                elif isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                else:
                    continue
                for name in imported:
                    if not name.startswith("thebigdiffer."):
                        continue
                    namespace = name.split(".")[1]
                    if namespace not in ALLOWED_PACKAGE_MODULES:
                        violations.append(
                            f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}:{name}"
                        )

    assert violations == []


def test_ingest_provenance_type_is_owned_by_neutral_package() -> None:
    result = _isolated_import(
        "import json, typing; "
        "from thebigdiffer.ingest import FileRecord, IngestDiagnostic; "
        "from thebigdiffer.provenance import EvidenceProvenance; "
        "file_type = typing.get_type_hints(FileRecord)['provenance']; "
        "diagnostic_type = typing.get_type_hints(IngestDiagnostic)['provenance']; "
        "print(json.dumps({'file_module': file_type.__module__, "
        "'diagnostic_module': diagnostic_type.__module__, "
        "'same': file_type is EvidenceProvenance and diagnostic_type is EvidenceProvenance}))"
    )

    assert result == {
        "file_module": "thebigdiffer.provenance.model",
        "diagnostic_module": "thebigdiffer.provenance.model",
        "same": True,
    }

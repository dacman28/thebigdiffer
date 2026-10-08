"""Exact patch presentation for autonomous investigation."""

from thebigdiffer.patch.model import PatchPresentation
from thebigdiffer.patch.presentation import (
    build_patch_presentation,
    exact_unified_diff,
    render_primary_input,
)

__all__ = [
    "PatchPresentation",
    "build_patch_presentation",
    "exact_unified_diff",
    "render_primary_input",
]

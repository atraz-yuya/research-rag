"""Nuitka user plugin that adds the build version before bundle signing."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nuitka.freezer import MacOSApp
from nuitka.plugins.PluginBase import NuitkaPluginBase


_VERSION_ENVIRONMENT_VARIABLE = "RESEARCH_RAG_BUNDLE_VERSION"
_BUNDLE_VERSION = os.environ.get(_VERSION_ENVIRONMENT_VARIABLE)
if not _BUNDLE_VERSION:
    raise RuntimeError(
        f"{_VERSION_ENVIRONMENT_VARIABLE} must be set for the macOS build"
    )

_original_write_plist = MacOSApp._writePlist


def _write_plist_with_bundle_version(
    filename: str,
    values: dict[str, Any],
) -> None:
    if Path(filename).name == "Info.plist":
        values = values.copy()
        short_version = values.get("CFBundleShortVersionString")
        if short_version != _BUNDLE_VERSION:
            raise RuntimeError(
                "Nuitka bundle version does not match pyproject.toml: "
                f"{short_version!r} != {_BUNDLE_VERSION!r}"
            )
        values["CFBundleVersion"] = _BUNDLE_VERSION
    _original_write_plist(filename, values)


MacOSApp._writePlist = _write_plist_with_bundle_version


class ResearchRagBundleMetadataPlugin(NuitkaPluginBase):
    """Inject release metadata before Nuitka applies its macOS signature."""

    plugin_name = "research-rag-bundle-metadata"

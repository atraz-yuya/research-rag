#!/usr/bin/env python3
"""Prepare and validate macOS packaging metadata from project configuration."""

from __future__ import annotations

import argparse
import configparser
import json
import plistlib
import re
import shlex
import sys
import tomllib
from pathlib import Path


APP_NAME = "Research RAG"
BUNDLE_IDENTIFIER = "io.github.atraz-yuya.research-rag"
_SUPPORTED_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,2}$")
_MANAGED_NUITKA_OPTIONS = (
    "--macos-app-name",
    "--macos-signed-app-name",
    "--macos-app-version",
    "--macos-sign-identity",
    "--macos-sign-notarization",
)


class MetadataError(ValueError):
    """Raised when packaging metadata is missing or inconsistent."""


def read_project_version(pyproject_path: Path) -> str:
    """Return the release version whose sole source is ``pyproject.toml``."""

    try:
        with pyproject_path.open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file)["project"]
        version = project["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as error:
        raise MetadataError(
            f"Could not read [project].version from {pyproject_path}: {error}"
        ) from error

    if not isinstance(version, str) or not _SUPPORTED_VERSION.fullmatch(version):
        raise MetadataError(
            "[project].version must contain two or three dot-separated "
            "numeric components for the macOS bundle"
        )
    return version


def _is_managed_nuitka_option(argument: str) -> bool:
    return any(
        argument == option or argument.startswith(f"{option}=")
        for option in _MANAGED_NUITKA_OPTIONS
    )


def prepare_deploy_spec(
    source: Path,
    destination: Path,
    *,
    pyproject_path: Path,
    signing_identity: str | None = None,
    exec_directory: str | None = None,
    bundle_metadata_plugin: Path | None = None,
) -> None:
    """Write a disposable deploy spec with authoritative release metadata."""

    config = configparser.ConfigParser()
    if config.read(source) != [str(source)]:
        raise MetadataError(f"Could not read deployment specification: {source}")

    version = read_project_version(pyproject_path)
    arguments = [
        argument
        for argument in shlex.split(config["nuitka"].get("extra_args", ""))
        if not _is_managed_nuitka_option(argument)
    ]
    arguments.extend(
        (
            f"--macos-app-name={APP_NAME}",
            f"--macos-signed-app-name={BUNDLE_IDENTIFIER}",
            f"--macos-app-version={version}",
        )
    )
    if bundle_metadata_plugin is not None:
        arguments.append(f"--user-plugin={bundle_metadata_plugin.resolve()}")
    if signing_identity is not None:
        arguments.extend(
            (
                f"--macos-sign-identity={signing_identity}",
                "--macos-sign-notarization",
            )
        )

    config["nuitka"]["extra_args"] = shlex.join(arguments)
    if exec_directory is not None:
        config["app"]["exec_directory"] = exec_directory

    with destination.open("w", encoding="utf-8") as destination_file:
        config.write(destination_file)


def verify_bundle_info(info_plist: Path, *, pyproject_path: Path) -> None:
    """Validate the bundle identifier and both macOS version fields."""

    version = read_project_version(pyproject_path)
    try:
        with info_plist.open("rb") as plist_file:
            values = plistlib.load(plist_file)
    except (OSError, plistlib.InvalidFileException) as error:
        raise MetadataError(f"Could not read bundle metadata from {info_plist}") from error

    expected = {
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
    }
    mismatches = [
        f"{key}={values.get(key)!r} (expected {value!r})"
        for key, value in expected.items()
        if values.get(key) != value
    ]
    if mismatches:
        raise MetadataError("Invalid macOS bundle metadata: " + "; ".join(mismatches))


def parse_notary_result(result_path: Path) -> tuple[str | None, str | None]:
    """Return the submission ID and status from notarytool JSON output."""

    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MetadataError(f"Could not read notarytool result: {result_path}") from error
    if not isinstance(result, dict):
        raise MetadataError("notarytool result must be a JSON object")

    submission_id = result.get("id")
    status = result.get("status")
    return (
        submission_id if isinstance(submission_id, str) else None,
        status if isinstance(status, str) else None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyproject", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version")
    subparsers.add_parser("bundle-identifier")

    prepare_parser = subparsers.add_parser("prepare-spec")
    prepare_parser.add_argument("--source", type=Path, required=True)
    prepare_parser.add_argument("--destination", type=Path, required=True)
    prepare_parser.add_argument("--signing-identity")
    prepare_parser.add_argument("--exec-directory")
    prepare_parser.add_argument("--bundle-metadata-plugin", type=Path)

    verify_parser = subparsers.add_parser("verify-bundle")
    verify_parser.add_argument("--info-plist", type=Path, required=True)

    notary_parser = subparsers.add_parser("notary-result")
    notary_parser.add_argument("--result", type=Path, required=True)
    notary_parser.add_argument("--field", choices=("id", "status"), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "version":
            print(read_project_version(arguments.pyproject))
        elif arguments.command == "bundle-identifier":
            print(BUNDLE_IDENTIFIER)
        elif arguments.command == "prepare-spec":
            prepare_deploy_spec(
                arguments.source,
                arguments.destination,
                pyproject_path=arguments.pyproject,
                signing_identity=arguments.signing_identity,
                exec_directory=arguments.exec_directory,
                bundle_metadata_plugin=arguments.bundle_metadata_plugin,
            )
        elif arguments.command == "verify-bundle":
            verify_bundle_info(
                arguments.info_plist,
                pyproject_path=arguments.pyproject,
            )
        else:
            submission_id, status = parse_notary_result(arguments.result)
            value = submission_id if arguments.field == "id" else status
            if value is None:
                raise MetadataError(
                    f"notarytool result does not contain a string {arguments.field!r}"
                )
            print(value)
    except MetadataError as error:
        parser.exit(1, f"Error: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

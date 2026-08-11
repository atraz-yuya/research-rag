from __future__ import annotations

import configparser
import os
import runpy
import subprocess
from pathlib import Path

import pytest

from research_rag import gui_app
from research_rag.index_store import SCHEMA_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPOSITORY_ROOT / "run_gui.py"
DEPLOY_SPEC = REPOSITORY_ROOT / "pysidedeploy.spec"
BUILD_HELPER = REPOSITORY_ROOT / "scripts" / "build_macos_app.sh"


def _read_deploy_spec() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    assert config.read(DEPLOY_SPEC) == [str(DEPLOY_SPEC)]
    return config


def test_top_level_launcher_only_delegates_to_gui_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[None] = []

    def fake_main() -> int:
        calls.append(None)
        return 17

    monkeypatch.setattr(gui_app, "main", fake_main)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(LAUNCHER), run_name="__main__")

    assert exit_info.value.code == 17
    assert calls == [None]
    assert "research_rag.gui_app import main" in LAUNCHER.read_text()


def test_deploy_spec_builds_standalone_macos_application_in_ignored_directory(
) -> None:
    config = _read_deploy_spec()

    assert config["app"]["title"] == "Research RAG"
    assert config["app"]["project_dir"] == "."
    assert config["app"]["input_file"] == "run_gui.py"
    assert config["app"]["exec_directory"] == "build/deploy"
    assert config["nuitka"]["mode"] == "standalone"
    assert config["python"]["packages"] == "Nuitka==4.1.3"
    assert config["qt"]["modules"] == "Core,Gui,Widgets"
    assert "PyInstaller" not in DEPLOY_SPEC.read_text()

    ignore_rules = (REPOSITORY_ROOT / ".gitignore").read_text().splitlines()
    assert "build/" in ignore_rules
    assert "deployment/" in ignore_rules
    assert "*.app/" in ignore_rules
    assert "/.pysidedeploy.build.*" in ignore_rules


def test_deploy_spec_does_not_bundle_runtime_or_user_data() -> None:
    config = _read_deploy_spec()
    configured_values = "\n".join(
        value
        for section in config.values()
        for value in section.values()
    ).lower()

    for excluded_name in (
        "indexes.sqlite3",
        "settings.ini",
        ".pdf",
        "ollama",
        "qwen3",
    ):
        assert excluded_name not in configured_values

    assert gui_app.default_settings_path().name == "settings.ini"
    assert gui_app.default_database_path().name == "indexes.sqlite3"
    assert SCHEMA_VERSION == 3


def test_build_helper_rejects_non_macos() -> None:
    environment = os.environ.copy()
    environment["RESEARCH_RAG_BUILD_SYSTEM_NAME"] = "Linux"

    completed = subprocess.run(
        [str(BUILD_HELPER)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "only be built on macOS" in completed.stderr


def test_build_helper_reports_missing_pyside6_deploy() -> None:
    environment = os.environ.copy()
    environment["RESEARCH_RAG_BUILD_SYSTEM_NAME"] = "Darwin"
    environment["PYSIDE6_DEPLOY"] = "missing-pyside6-deploy-for-test"

    completed = subprocess.run(
        [str(BUILD_HELPER)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "pyside6-deploy was not found" in completed.stderr


def test_build_helper_dry_run_uses_disposable_spec(tmp_path: Path) -> None:
    recorded_arguments = tmp_path / "arguments.txt"
    fake_deploy = tmp_path / "pyside6-deploy"
    fake_deploy.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {recorded_arguments!s}\n"
    )
    fake_deploy.chmod(0o755)
    environment = os.environ.copy()
    environment["RESEARCH_RAG_BUILD_SYSTEM_NAME"] = "Darwin"
    environment["PYSIDE6_DEPLOY"] = str(fake_deploy)

    completed = subprocess.run(
        [str(BUILD_HELPER), "--dry-run"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    arguments = recorded_arguments.read_text().splitlines()
    assert "-c" in arguments
    build_spec = Path(arguments[arguments.index("-c") + 1])
    assert build_spec.parent == REPOSITORY_ROOT
    assert build_spec.name.startswith(".pysidedeploy.build.")
    assert not build_spec.exists()
    assert "--mode" in arguments
    assert "standalone" in arguments
    assert "--nuitka-version" in arguments
    assert arguments[arguments.index("--nuitka-version") + 1] == "4.1.3"
    assert "--dry-run" in arguments
    assert DEPLOY_SPEC.read_text().startswith("[app]\n")


def test_build_helper_validates_executable_and_ad_hoc_signature() -> None:
    helper_source = BUILD_HELPER.read_text()

    assert 'EXPECTED_EXECUTABLE="$EXPECTED_APP/Contents/MacOS/run_gui"' in (
        helper_source
    )
    signing_commands = (
        '"$XATTR_COMMAND" -cr "$EXPECTED_APP"',
        '"$CODESIGN_COMMAND" --force --deep --sign - "$EXPECTED_APP"',
        '"$CODESIGN_COMMAND" --verify --deep --strict "$EXPECTED_APP"',
    )
    command_offsets = [helper_source.index(command) for command in signing_commands]
    assert command_offsets == sorted(command_offsets)
    assert "&& \\" in helper_source
    assert "-name QtCore" in helper_source
    assert "-name libqcocoa.dylib" in helper_source


def test_build_helper_rejects_partial_bundle_without_qt_runtime(
    tmp_path: Path,
) -> None:
    fake_deploy = tmp_path / "pyside6-deploy"
    fake_app = tmp_path / "output" / "Research RAG.app"
    fake_deploy.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$FAKE_APP/Contents/MacOS\" \"$FAKE_APP/Contents/Resources\"\n"
        ": > \"$FAKE_APP/Contents/MacOS/run_gui\"\n"
        "chmod +x \"$FAKE_APP/Contents/MacOS/run_gui\"\n"
        "cp \"$FAKE_ICON\" \"$FAKE_APP/Contents/Resources/ResearchRAG.icns\"\n"
    )
    fake_deploy.chmod(0o755)
    fake_icon = tmp_path / "ResearchRAG.icns"
    fake_icon_generator = tmp_path / "fake_icon_generator.py"
    fake_icon_generator.write_text(
        "import argparse\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--output', type=Path, required=True)\n"
        "parser.add_argument('--dry-run', action='store_true')\n"
        "args = parser.parse_args()\n"
        "if not args.dry_run:\n"
        "    args.output.write_bytes(b'fake icon')\n"
    )
    environment = os.environ.copy()
    environment.update(
        {
            "RESEARCH_RAG_BUILD_SYSTEM_NAME": "Darwin",
            "RESEARCH_RAG_PYTHON": os.fspath(Path(os.sys.executable)),
            "RESEARCH_RAG_BUILD_DIRECTORY": os.fspath(fake_app.parent),
            "RESEARCH_RAG_ICON_GENERATOR": os.fspath(fake_icon_generator),
            "RESEARCH_RAG_ICON_OUTPUT": os.fspath(fake_icon),
            "PYSIDE6_DEPLOY": os.fspath(fake_deploy),
            "FAKE_APP": os.fspath(fake_app),
            "FAKE_ICON": os.fspath(fake_icon),
        }
    )

    completed = subprocess.run(
        [BUILD_HELPER],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "incomplete bundle without the required Qt runtime" in completed.stderr

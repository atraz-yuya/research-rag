from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DMG_HELPER = REPOSITORY_ROOT / "scripts" / "package_macos_dmg.sh"


def _fake_app(tmp_path: Path) -> Path:
    app = tmp_path / "Research RAG.app"
    executable = app / "Contents" / "MacOS" / "run_gui"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    return app


def _fake_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    commands = tmp_path / "commands"
    commands.mkdir()
    command_log = tmp_path / "commands.log"
    staging_record = tmp_path / "staging.txt"

    fake_lipo = commands / "lipo"
    fake_lipo.write_text("#!/bin/sh\nprintf 'arm64\\n'\n")
    fake_lipo.chmod(0o755)

    fake_ditto = commands / "ditto"
    fake_ditto.write_text(
        "#!/bin/sh\n"
        "printf 'ditto %s %s\\n' \"$1\" \"$2\" >> \"$FAKE_COMMAND_LOG\"\n"
        "cp -R \"$1\" \"$2\"\n"
    )
    fake_ditto.chmod(0o755)

    fake_hdiutil = commands / "hdiutil"
    fake_hdiutil.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "printf 'hdiutil %s\\n' \"$*\" >> \"$FAKE_COMMAND_LOG\"\n"
        "if [ \"$1\" = 'create' ]; then\n"
        "  staging=''\n"
        "  output=''\n"
        "  while [ $# -gt 0 ]; do\n"
        "    if [ \"$1\" = '-srcfolder' ]; then shift; staging=$1; fi\n"
        "    output=$1\n"
        "    shift\n"
        "  done\n"
        "  printf '%s\\n' \"$staging\" > \"$FAKE_STAGING_RECORD\"\n"
        "  test -d \"$staging/Research RAG.app\"\n"
        "  test \"$(readlink \"$staging/Applications\")\" = '/Applications'\n"
        "  test \"$(find \"$staging\" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')\" = '2'\n"
        "  mkdir -p \"$(dirname \"$output\")\"\n"
        "  : > \"$output\"\n"
        "fi\n"
    )
    fake_hdiutil.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "RESEARCH_RAG_BUILD_SYSTEM_NAME": "Darwin",
            "RESEARCH_RAG_PYTHON": sys.executable,
            "RESEARCH_RAG_HDIUTIL_COMMAND": os.fspath(fake_hdiutil),
            "RESEARCH_RAG_DITTO_COMMAND": os.fspath(fake_ditto),
            "RESEARCH_RAG_LIPO_COMMAND": os.fspath(fake_lipo),
            "FAKE_COMMAND_LOG": os.fspath(command_log),
            "FAKE_STAGING_RECORD": os.fspath(staging_record),
        }
    )
    return environment, command_log, staging_record


def test_dmg_helper_rejects_non_macos(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["RESEARCH_RAG_BUILD_SYSTEM_NAME"] = "Linux"

    completed = subprocess.run(
        [DMG_HELPER, tmp_path / "Research RAG.app"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "requires macOS" in completed.stderr


def test_dmg_helper_stages_only_app_and_applications_symlink_then_verifies(
    tmp_path: Path,
) -> None:
    app = _fake_app(tmp_path)
    environment, command_log, staging_record = _fake_environment(tmp_path)
    output = tmp_path / "output" / "Research-RAG-0.1.0-macos-arm64.dmg"

    completed = subprocess.run(
        [DMG_HELPER, app, output],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.is_file()
    calls = command_log.read_text().splitlines()
    create_index = next(
        index for index, call in enumerate(calls) if call.startswith("hdiutil create ")
    )
    verify_index = next(
        index for index, call in enumerate(calls) if call.startswith("hdiutil verify ")
    )
    assert "-format UDZO" in calls[create_index]
    assert "-volname Research RAG" in calls[create_index]
    assert create_index < verify_index
    assert not Path(staging_record.read_text().strip()).exists()


def test_dmg_helper_requires_versioned_actual_architecture_filename(
    tmp_path: Path,
) -> None:
    app = _fake_app(tmp_path)
    environment, _, _ = _fake_environment(tmp_path)

    completed = subprocess.run(
        [DMG_HELPER, app, tmp_path / "wrong-name.dmg"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Research-RAG-0.1.0-macos-arm64.dmg" in completed.stderr

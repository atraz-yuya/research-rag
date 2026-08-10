from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEASE_HELPER = REPOSITORY_ROOT / "scripts" / "prepare_github_release.sh"


def _release_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    release_directory = tmp_path / "release"
    release_directory.mkdir()
    dmg = release_directory / "Research-RAG-0.1.0-macos-arm64.dmg"
    dmg.write_bytes(b"fake dmg")
    checksum = dmg.with_name(f"{dmg.name}.sha256")
    checksum.write_text(f"fake  {dmg.name}\n")
    app = release_directory / "Research RAG.app"
    executable = app / "Contents" / "MacOS" / "run_gui"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    return dmg, checksum, app


def _fake_environment(tmp_path: Path, app: Path) -> tuple[dict[str, str], Path]:
    commands = tmp_path / "commands"
    commands.mkdir()
    command_log = tmp_path / "commands.log"
    fake_command = commands / "fake-command"
    fake_command.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "name=$(basename \"$0\")\n"
        "printf '%s %s\\n' \"$name\" \"$*\" >> \"$FAKE_COMMAND_LOG\"\n"
        "case \"$name\" in\n"
        "  lipo) printf 'arm64\\n' ;;\n"
        "  shasum) exit 0 ;;\n"
        "  gh) exit 0 ;;\n"
        "  git)\n"
        "    case \"${1:-}\" in\n"
        "      show-ref) test \"${FAKE_TAG_AVAILABLE:-1}\" = '1' ;;\n"
        "      rev-parse)\n"
        "        case \"${2:-}\" in\n"
        "          HEAD|'v0.1.0^{commit}') printf 'commit-123\\n' ;;\n"
        "          v0.1.0) printf 'tag-object-123\\n' ;;\n"
        "          *) exit 1 ;;\n"
        "        esac\n"
        "        ;;\n"
        "      ls-remote) printf 'tag-object-123\\trefs/tags/v0.1.0\\n' ;;\n"
        "    esac\n"
        "    ;;\n"
        "esac\n"
    )
    fake_command.chmod(0o755)

    command_paths: dict[str, str] = {}
    for name, variable in (
        ("gh", "RESEARCH_RAG_GH_COMMAND"),
        ("git", "RESEARCH_RAG_GIT_COMMAND"),
        ("shasum", "RESEARCH_RAG_SHASUM_COMMAND"),
        ("lipo", "RESEARCH_RAG_LIPO_COMMAND"),
    ):
        command_path = commands / name
        command_path.symlink_to(fake_command)
        command_paths[variable] = os.fspath(command_path)

    environment = os.environ.copy()
    environment.update(command_paths)
    environment.update(
        {
            "RESEARCH_RAG_PYTHON": sys.executable,
            "RESEARCH_RAG_RELEASE_DIR": os.fspath(app.parent),
            "RESEARCH_RAG_RELEASE_APP": os.fspath(app),
            "FAKE_COMMAND_LOG": os.fspath(command_log),
        }
    )
    return environment, command_log


def test_github_release_dry_run_is_read_only(tmp_path: Path) -> None:
    command_log = tmp_path / "must-not-exist.log"
    environment = os.environ.copy()
    environment.update(
        {
            "RESEARCH_RAG_PYTHON": sys.executable,
            "RESEARCH_RAG_RELEASE_DIR": os.fspath(tmp_path / "release"),
            "RESEARCH_RAG_GH_COMMAND": os.fspath(command_log),
            "RESEARCH_RAG_GIT_COMMAND": os.fspath(command_log),
        }
    )

    completed = subprocess.run(
        [RELEASE_HELPER, "--dry-run"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Expected existing tag: v0.1.0" in completed.stdout
    assert "Release state: draft" in completed.stdout
    assert "--verify-tag --draft" in completed.stdout
    assert "creates no tag, push, GitHub Release, or asset upload" in completed.stdout
    assert not command_log.exists()
    assert not Path(environment["RESEARCH_RAG_RELEASE_DIR"]).exists()


def test_real_github_release_path_requires_tag_and_creates_draft_with_assets(
    tmp_path: Path,
) -> None:
    dmg, checksum, app = _release_artifacts(tmp_path)
    environment, command_log = _fake_environment(tmp_path, app)

    completed = subprocess.run(
        [RELEASE_HELPER, dmg],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    calls = command_log.read_text().splitlines()
    create_call = next(call for call in calls if call.startswith("gh release create "))
    assert "release create v0.1.0" in create_call
    assert "--verify-tag" in create_call
    assert "--draft" in create_call
    assert os.fspath(dmg) in create_call
    assert os.fspath(checksum) in create_call
    assert not any(" tag " in call or " push " in call for call in calls)


def test_real_github_release_path_rejects_missing_existing_tag(
    tmp_path: Path,
) -> None:
    dmg, _, app = _release_artifacts(tmp_path)
    environment, command_log = _fake_environment(tmp_path, app)
    environment["FAKE_TAG_AVAILABLE"] = "0"

    completed = subprocess.run(
        [RELEASE_HELPER, dmg],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "required existing local tag was not found: v0.1.0" in completed.stderr
    assert not any(
        call.startswith("gh release create ")
        for call in command_log.read_text().splitlines()
    )


def test_github_release_helper_never_creates_or_pushes_tags() -> None:
    source = RELEASE_HELPER.read_text()

    assert "git tag" not in source
    assert "git push" not in source
    assert '"$GIT_COMMAND" tag' not in source
    assert '"$GIT_COMMAND" push' not in source
    assert "--verify-tag" in source
    assert "--draft" in source

from __future__ import annotations

import configparser
import os
import plistlib
import shlex
import subprocess
from pathlib import Path

import pytest

from scripts import release_metadata


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
DEPLOY_SPEC = REPOSITORY_ROOT / "pysidedeploy.spec"
LOCAL_HELPER = REPOSITORY_ROOT / "scripts" / "build_macos_app.sh"
RELEASE_HELPER = REPOSITORY_ROOT / "scripts" / "release_macos_app.sh"
TEST_IDENTITY = "Developer ID Application: Test Developer (TESTTEAM1)"


def _prepared_arguments(
    tmp_path: Path,
    *,
    signing_identity: str | None = None,
) -> tuple[configparser.ConfigParser, list[str]]:
    destination = tmp_path / "prepared.spec"
    release_metadata.prepare_deploy_spec(
        DEPLOY_SPEC,
        destination,
        pyproject_path=PYPROJECT,
        signing_identity=signing_identity,
        exec_directory="build/release" if signing_identity else None,
    )
    config = configparser.ConfigParser()
    assert config.read(destination) == [str(destination)]
    return config, shlex.split(config["nuitka"]["extra_args"])


def _base_release_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "RESEARCH_RAG_BUILD_SYSTEM_NAME": "Darwin",
            "RESEARCH_RAG_PYTHON": os.fspath(Path(os.sys.executable)),
            "RESEARCH_RAG_RELEASE_DIR": os.fspath(tmp_path / "release"),
        }
    )
    return environment


def _install_fake_release_commands(
    tmp_path: Path,
    environment: dict[str, str],
    *,
    notary_status: str = "Accepted",
) -> tuple[Path, Path]:
    commands = tmp_path / "commands"
    commands.mkdir()
    command_log = tmp_path / "commands.log"
    fake_info = tmp_path / "source-info.plist"
    with fake_info.open("wb") as plist_file:
        plistlib.dump(
            {
                "CFBundleIdentifier": "placeholder",
                "CFBundleShortVersionString": "1.0",
            },
            plist_file,
        )

    fake_command_source = commands / "fake-command"
    fake_command_source.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "name=$(basename \"$0\")\n"
        "printf '%s %s\\n' \"$name\" \"$*\" >> \"$FAKE_COMMAND_LOG\"\n"
        "case \"$name\" in\n"
        "  pyside6-deploy)\n"
        "    mkdir -p \"$FAKE_APP/Contents/MacOS\"\n"
        "    cp \"$FAKE_INFO_PLIST\" \"$FAKE_APP/Contents/Info.plist\"\n"
        "    : > \"$FAKE_APP/Contents/MacOS/run_gui\"\n"
        "    chmod +x \"$FAKE_APP/Contents/MacOS/run_gui\"\n"
        "    ;;\n"
        "  security)\n"
        f"    printf '  1) HASH \\\"{TEST_IDENTITY}\\\"\\n'\n"
        "    ;;\n"
        "  codesign)\n"
        "    case \" $* \" in\n"
        f"      *' -dvvv '*) printf 'Authority={TEST_IDENTITY}\\nflags=0x10000(runtime)\\nTimestamp=Aug 10, 2026\\n' >&2 ;;\n"
        "      *' --entitlements '*) printf '<?xml version=\"1.0\"?><plist><dict/></plist>\\n' >&2 ;;\n"
        "    esac\n"
        "    ;;\n"
        "  xcrun)\n"
        "    if [ \"${1:-}\" = '--find' ]; then printf '/fake/%s\\n' \"${2:-tool}\";\n"
        "    elif [ \"${1:-}\" = 'notarytool' ] && [ \"${2:-}\" = 'submit' ]; then\n"
        f"      printf '{{\"id\":\"submission-123\",\"status\":\"{notary_status}\"}}\\n'\n"
        "    fi\n"
        "    ;;\n"
        "  ditto)\n"
        "    for output_path do :; done\n"
        "    mkdir -p \"$(dirname \"$output_path\")\"\n"
        "    : > \"$output_path\"\n"
        "    ;;\n"
        "  lipo) printf 'arm64\\n' ;;\n"
        "  spctl) : ;;\n"
        "esac\n"
    )
    fake_command_source.chmod(0o755)

    command_paths: dict[str, str] = {}
    for command_name, environment_name in (
        ("pyside6-deploy", "PYSIDE6_DEPLOY"),
        ("security", "RESEARCH_RAG_SECURITY_COMMAND"),
        ("codesign", "RESEARCH_RAG_CODESIGN_COMMAND"),
        ("xcrun", "RESEARCH_RAG_XCRUN_COMMAND"),
        ("ditto", "RESEARCH_RAG_DITTO_COMMAND"),
        ("lipo", "RESEARCH_RAG_LIPO_COMMAND"),
        ("spctl", "RESEARCH_RAG_SPCTL_COMMAND"),
    ):
        command_path = commands / command_name
        command_path.symlink_to(fake_command_source)
        command_paths[environment_name] = os.fspath(command_path)

    fake_app = Path(environment["RESEARCH_RAG_RELEASE_DIR"]) / "Research RAG.app"
    environment.update(command_paths)
    environment.update(
        {
            "FAKE_COMMAND_LOG": os.fspath(command_log),
            "FAKE_INFO_PLIST": os.fspath(fake_info),
            "FAKE_APP": os.fspath(fake_app),
            "RESEARCH_RAG_DEVELOPER_ID_APPLICATION": TEST_IDENTITY,
            "RESEARCH_RAG_NOTARY_PROFILE": "test-notary-profile",
        }
    )
    return command_log, fake_app


def test_project_version_is_the_single_source_for_bundle_metadata(
    tmp_path: Path,
) -> None:
    assert release_metadata.read_project_version(PYPROJECT) == "0.1.0"
    config, arguments = _prepared_arguments(tmp_path)

    assert config["app"]["exec_directory"] == "build/deploy"
    assert "--macos-app-version=0.1.0" in arguments
    assert (
        "--macos-signed-app-name=io.github.atraz-yuya.research-rag" in arguments
    )


def test_changed_pyproject_version_propagates_without_python_version_constant(
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "7.8.9"\n')
    destination = tmp_path / "prepared.spec"
    release_metadata.prepare_deploy_spec(
        DEPLOY_SPEC,
        destination,
        pyproject_path=pyproject,
    )
    config = configparser.ConfigParser()
    config.read(destination)
    assert "--macos-app-version=7.8.9" in shlex.split(
        config["nuitka"]["extra_args"]
    )

    info_plist = tmp_path / "Info.plist"
    with info_plist.open("wb") as plist_file:
        plistlib.dump({}, plist_file)
    release_metadata.update_bundle_info(info_plist, pyproject_path=pyproject)
    with info_plist.open("rb") as plist_file:
        values = plistlib.load(plist_file)
    assert values["CFBundleShortVersionString"] == "7.8.9"
    assert values["CFBundleVersion"] == "7.8.9"
    assert '"0.1.0"' not in (
        REPOSITORY_ROOT / "scripts" / "release_metadata.py"
    ).read_text()


def test_release_spec_uses_native_developer_id_and_hardened_runtime(
    tmp_path: Path,
) -> None:
    config, arguments = _prepared_arguments(
        tmp_path,
        signing_identity=TEST_IDENTITY,
    )

    assert config["app"]["exec_directory"] == "build/release"
    assert f"--macos-sign-identity={TEST_IDENTITY}" in arguments
    assert "--macos-sign-notarization" in arguments


def test_bundle_metadata_is_updated_and_verified_before_signing(
    tmp_path: Path,
) -> None:
    info_plist = tmp_path / "Info.plist"
    with info_plist.open("wb") as plist_file:
        plistlib.dump({"CFBundleIdentifier": "old"}, plist_file)

    release_metadata.update_bundle_info(info_plist, pyproject_path=PYPROJECT)
    release_metadata.verify_bundle_info(info_plist, pyproject_path=PYPROJECT)

    with info_plist.open("rb") as plist_file:
        values = plistlib.load(plist_file)
    assert values["CFBundleIdentifier"] == "io.github.atraz-yuya.research-rag"
    assert values["CFBundleShortVersionString"] == "0.1.0"
    assert values["CFBundleVersion"] == "0.1.0"


def test_local_build_dry_run_injects_metadata_without_credentials(
    tmp_path: Path,
) -> None:
    copied_spec = tmp_path / "local.spec"
    fake_deploy = tmp_path / "pyside6-deploy"
    fake_deploy.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = '-c' ]; then cp \"$2\" \"$COPIED_SPEC\"; exit 0; fi\n"
        "  shift\n"
        "done\n"
        "exit 1\n"
    )
    fake_deploy.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "RESEARCH_RAG_BUILD_SYSTEM_NAME": "Darwin",
            "RESEARCH_RAG_PYTHON": os.fspath(Path(os.sys.executable)),
            "PYSIDE6_DEPLOY": os.fspath(fake_deploy),
            "COPIED_SPEC": os.fspath(copied_spec),
        }
    )

    completed = subprocess.run(
        [LOCAL_HELPER, "--dry-run"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    config = configparser.ConfigParser()
    config.read(copied_spec)
    arguments = shlex.split(config["nuitka"]["extra_args"])
    assert "--macos-app-version=0.1.0" in arguments
    assert not any(argument.startswith("--macos-sign-identity") for argument in arguments)


def test_release_helper_rejects_non_macos_and_missing_credentials(
    tmp_path: Path,
) -> None:
    environment = _base_release_environment(tmp_path)
    environment["RESEARCH_RAG_BUILD_SYSTEM_NAME"] = "Linux"
    non_macos = subprocess.run(
        [RELEASE_HELPER], env=environment, capture_output=True, text=True, check=False
    )
    assert non_macos.returncode != 0
    assert "only be prepared on macOS" in non_macos.stderr

    environment["RESEARCH_RAG_BUILD_SYSTEM_NAME"] = "Darwin"
    no_identity = subprocess.run(
        [RELEASE_HELPER], env=environment, capture_output=True, text=True, check=False
    )
    assert no_identity.returncode != 0
    assert "RESEARCH_RAG_DEVELOPER_ID_APPLICATION is required" in no_identity.stderr

    environment["RESEARCH_RAG_DEVELOPER_ID_APPLICATION"] = TEST_IDENTITY
    no_profile = subprocess.run(
        [RELEASE_HELPER], env=environment, capture_output=True, text=True, check=False
    )
    assert no_profile.returncode != 0
    assert "RESEARCH_RAG_NOTARY_PROFILE is required" in no_profile.stderr


def test_release_dry_run_never_uses_credentials_commands_or_network(
    tmp_path: Path,
) -> None:
    environment = _base_release_environment(tmp_path)
    command_log = tmp_path / "must-not-exist.log"
    environment.update(
        {
            "RESEARCH_RAG_SECURITY_COMMAND": os.fspath(command_log),
            "RESEARCH_RAG_XCRUN_COMMAND": os.fspath(command_log),
            "RESEARCH_RAG_CODESIGN_COMMAND": os.fspath(command_log),
        }
    )

    completed = subprocess.run(
        [RELEASE_HELPER, "--dry-run"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Version: 0.1.0" in completed.stdout
    assert "Bundle identifier: io.github.atraz-yuya.research-rag" in completed.stdout
    assert "no build, signing, Keychain mutation, or Apple network request" in completed.stdout
    assert not command_log.exists()
    assert not Path(environment["RESEARCH_RAG_RELEASE_DIR"]).exists()


def test_release_workflow_uses_zip_notarytool_stapling_and_actual_architecture(
    tmp_path: Path,
) -> None:
    environment = _base_release_environment(tmp_path)
    command_log, fake_app = _install_fake_release_commands(tmp_path, environment)

    completed = subprocess.run(
        [RELEASE_HELPER],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    final_zip = (
        Path(environment["RESEARCH_RAG_RELEASE_DIR"])
        / "Research-RAG-0.1.0-macos-arm64.zip"
    )
    assert final_zip.is_file()
    release_metadata.verify_bundle_info(
        fake_app / "Contents" / "Info.plist",
        pyproject_path=PYPROJECT,
    )

    calls = command_log.read_text().splitlines()
    submit_index = next(
        index for index, call in enumerate(calls) if "notarytool submit" in call
    )
    staple_index = next(
        index for index, call in enumerate(calls) if "stapler staple" in call
    )
    ditto_calls = [
        (index, call) for index, call in enumerate(calls) if call.startswith("ditto ")
    ]
    assert len(ditto_calls) == 2
    assert ditto_calls[0][0] < submit_index < staple_index < ditto_calls[1][0]
    assert "Research-RAG-0.1.0-notarization.zip" in calls[submit_index]
    assert "Research RAG.app --keychain-profile" not in calls[submit_index]
    assert "--wait --output-format json" in calls[submit_index]
    assert any("stapler validate" in call for call in calls)
    assert any("--options runtime --timestamp" in call for call in calls)


def test_notarization_rejection_reports_submission_id_and_fetches_log(
    tmp_path: Path,
) -> None:
    environment = _base_release_environment(tmp_path)
    command_log, _ = _install_fake_release_commands(
        tmp_path,
        environment,
        notary_status="Invalid",
    )

    completed = subprocess.run(
        [RELEASE_HELPER],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Notarization submission ID: submission-123" in completed.stdout
    assert "notarization status was Invalid" in completed.stderr
    assert "notarytool log submission-123" in command_log.read_text()


def test_release_helper_has_no_legacy_or_plaintext_credential_fallbacks() -> None:
    source = RELEASE_HELPER.read_text()

    assert "altool" not in source
    assert "--password" not in source
    assert "get-task-allow=true" not in source
    assert "--keychain-profile" in source
    assert "--sign -" not in source
    assert "--options runtime --timestamp" in source
    assert "--wait --output-format json" in source

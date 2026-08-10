from __future__ import annotations

import configparser
import os
import plistlib
import runpy
import shlex
import subprocess
import sys
import types
from pathlib import Path

import pytest

from scripts import release_metadata


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
DEPLOY_SPEC = REPOSITORY_ROOT / "pysidedeploy.spec"
LOCAL_HELPER = REPOSITORY_ROOT / "scripts" / "build_macos_app.sh"
RELEASE_HELPER = REPOSITORY_ROOT / "scripts" / "release_macos_app.sh"
NUITKA_METADATA_PLUGIN = (
    REPOSITORY_ROOT / "scripts" / "nuitka_bundle_metadata_plugin.py"
)
GENERATED_ICON = REPOSITORY_ROOT / "build" / "generated" / "ResearchRAG.icns"
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
        bundle_metadata_plugin=NUITKA_METADATA_PLUGIN,
        icon_path=GENERATED_ICON,
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
                "CFBundleIdentifier": "io.github.atraz-yuya.research-rag",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleVersion": "0.1.0",
                "CFBundleIconFile": "ResearchRAG.icns",
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
        "    mkdir -p \"$FAKE_APP/Contents/MacOS\" \"$FAKE_APP/Contents/Resources\"\n"
        "    cp \"$FAKE_INFO_PLIST\" \"$FAKE_APP/Contents/Info.plist\"\n"
        "    cp \"$FAKE_ICON\" \"$FAKE_APP/Contents/Resources/ResearchRAG.icns\"\n"
        "    : > \"$FAKE_APP/Contents/MacOS/run_gui\"\n"
        "    chmod +x \"$FAKE_APP/Contents/MacOS/run_gui\"\n"
        "    ;;\n"
        "  security)\n"
        f"    printf '  1) HASH \\\"{TEST_IDENTITY}\\\"\\n'\n"
        "    ;;\n"
        "  codesign)\n"
        "    case \" $* \" in\n"
        "      *' -dvvv '*)\n"
        "        for signed_path do :; done\n"
        "        case \"$signed_path\" in\n"
        f"          *.dmg) printf 'Authority={TEST_IDENTITY}\\nIdentifier=io.github.atraz-yuya.research-rag.dmg\\nTimestamp=Aug 10, 2026\\n' >&2 ;;\n"
        f"          *) printf 'Authority={TEST_IDENTITY}\\nflags=0x10000(runtime)\\nTimestamp=Aug 10, 2026\\n' >&2 ;;\n"
        "        esac\n"
        "        ;;\n"
        "      *' --entitlements '*) printf '<?xml version=\"1.0\"?><plist><dict/></plist>\\n' >&2 ;;\n"
        "    esac\n"
        "    ;;\n"
        "  xcrun)\n"
        "    if [ \"${1:-}\" = '--find' ]; then printf '/fake/%s\\n' \"${2:-tool}\";\n"
        "    elif [ \"${1:-}\" = 'notarytool' ] && [ \"${2:-}\" = 'submit' ]; then\n"
        f"      printf '{{\"id\":\"submission-123\",\"status\":\"{notary_status}\"}}\\n'\n"
        "    fi\n"
        "    ;;\n"
        "  ditto) cp -R \"$1\" \"$2\" ;;\n"
        "  hdiutil)\n"
        "    if [ \"${1:-}\" = 'create' ]; then\n"
        "      for output_path do :; done\n"
        "      mkdir -p \"$(dirname \"$output_path\")\"\n"
        "      : > \"$output_path\"\n"
        "    fi\n"
        "    ;;\n"
        "  lipo) printf 'arm64\\n' ;;\n"
        "  spctl) : ;;\n"
        "  shasum)\n"
        "    for input_path do :; done\n"
        "    printf '0123456789abcdef  %s\\n' \"$(basename \"$input_path\")\"\n"
        "    ;;\n"
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
        ("hdiutil", "RESEARCH_RAG_HDIUTIL_COMMAND"),
        ("lipo", "RESEARCH_RAG_LIPO_COMMAND"),
        ("spctl", "RESEARCH_RAG_SPCTL_COMMAND"),
        ("shasum", "RESEARCH_RAG_SHASUM_COMMAND"),
    ):
        command_path = commands / command_name
        command_path.symlink_to(fake_command_source)
        command_paths[environment_name] = os.fspath(command_path)

    fake_app = Path(environment["RESEARCH_RAG_RELEASE_DIR"]) / "Research RAG.app"
    fake_icon = tmp_path / "ResearchRAG.icns"
    fake_icon.write_bytes(b"fake icon")
    fake_icon_generator = tmp_path / "fake_icon_generator.py"
    fake_icon_generator.write_text(
        "import argparse\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--output', type=Path, required=True)\n"
        "args = parser.parse_args()\n"
        "args.output.parent.mkdir(parents=True, exist_ok=True)\n"
        "args.output.write_bytes(b'fake icon')\n"
    )
    environment.update(command_paths)
    environment.update(
        {
            "FAKE_COMMAND_LOG": os.fspath(command_log),
            "FAKE_INFO_PLIST": os.fspath(fake_info),
            "FAKE_APP": os.fspath(fake_app),
            "FAKE_ICON": os.fspath(fake_icon),
            "RESEARCH_RAG_ICON_GENERATOR": os.fspath(fake_icon_generator),
            "RESEARCH_RAG_ICON_OUTPUT": os.fspath(fake_icon),
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
    assert f"--user-plugin={NUITKA_METADATA_PLUGIN}" in arguments
    assert config["app"]["icon"] == os.fspath(GENERATED_ICON.resolve())


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
        bundle_metadata_plugin=NUITKA_METADATA_PLUGIN,
    )
    config = configparser.ConfigParser()
    config.read(destination)
    assert "--macos-app-version=7.8.9" in shlex.split(
        config["nuitka"]["extra_args"]
    )

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


def test_nuitka_plugin_adds_bundle_version_before_original_plist_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[tuple[str, dict[str, object]]] = []
    macos_app = types.ModuleType("nuitka.freezer.MacOSApp")
    macos_app._writePlist = lambda filename, values: written.append(
        (filename, values)
    )
    freezer = types.ModuleType("nuitka.freezer")
    freezer.MacOSApp = macos_app
    plugin_base = types.ModuleType("nuitka.plugins.PluginBase")
    plugin_base.NuitkaPluginBase = type("NuitkaPluginBase", (), {})
    nuitka = types.ModuleType("nuitka")
    plugins = types.ModuleType("nuitka.plugins")
    monkeypatch.setitem(sys.modules, "nuitka", nuitka)
    monkeypatch.setitem(sys.modules, "nuitka.freezer", freezer)
    monkeypatch.setitem(sys.modules, "nuitka.freezer.MacOSApp", macos_app)
    monkeypatch.setitem(sys.modules, "nuitka.plugins", plugins)
    monkeypatch.setitem(sys.modules, "nuitka.plugins.PluginBase", plugin_base)
    monkeypatch.setenv("RESEARCH_RAG_BUNDLE_VERSION", "7.8.9")

    runpy.run_path(os.fspath(NUITKA_METADATA_PLUGIN))
    macos_app._writePlist(
        os.fspath(tmp_path / "Info.plist"),
        {"CFBundleShortVersionString": "7.8.9"},
    )

    assert written == [
        (
            os.fspath(tmp_path / "Info.plist"),
            {
                "CFBundleShortVersionString": "7.8.9",
                "CFBundleVersion": "7.8.9",
            },
        )
    ]


def test_bundle_metadata_verifier_rejects_unsigned_build_metadata_mismatch(
    tmp_path: Path,
) -> None:
    info_plist = tmp_path / "Info.plist"
    with info_plist.open("wb") as plist_file:
        plistlib.dump(
            {
                "CFBundleIdentifier": "wrong",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleVersion": "0.1.0",
            },
            plist_file,
        )

    with pytest.raises(release_metadata.MetadataError, match="CFBundleIdentifier"):
        release_metadata.verify_bundle_info(info_plist, pyproject_path=PYPROJECT)


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
    assert f"--user-plugin={NUITKA_METADATA_PLUGIN}" in arguments
    assert config["app"]["icon"] == os.fspath(GENERATED_ICON.resolve())
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


def test_release_workflow_signs_submits_staples_dmg_and_checksums_last(
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
    final_dmg = (
        Path(environment["RESEARCH_RAG_RELEASE_DIR"])
        / "Research-RAG-0.1.0-macos-arm64.dmg"
    )
    checksum = final_dmg.with_name(f"{final_dmg.name}.sha256")
    assert final_dmg.is_file()
    assert checksum.is_file()
    assert final_dmg.name in checksum.read_text()
    assert os.fspath(final_dmg.parent) not in checksum.read_text()
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
    checksum_index = next(
        index for index, call in enumerate(calls) if call.startswith("shasum ")
    )
    dmg_sign_call = next(
        call
        for call in calls
        if call.startswith("codesign --sign ") and ".dmg" in call
    )
    assert "--identifier io.github.atraz-yuya.research-rag.dmg" in dmg_sign_call
    assert "--deep" not in dmg_sign_call
    assert "Research-RAG-0.1.0-macos-arm64.dmg" in calls[submit_index]
    assert ".zip" not in calls[submit_index]
    assert "--wait --output-format json" in calls[submit_index]
    assert submit_index < staple_index < checksum_index
    assert any("stapler validate" in call and ".dmg" in call for call in calls)
    assert sum(call.startswith("hdiutil verify ") for call in calls) >= 3


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
    assert "codesign --force --deep" not in source
    assert "codesign --deep --force" not in source
    assert "--force --deep" not in source
    assert "--deep --force" not in source
    assert '--sign "$IDENTITY"' in source
    assert '--identifier "$DMG_IDENTIFIER"' in source
    assert "notarytool submit \"$FINAL_DMG\"" in source
    assert ".zip" not in source
    assert "--wait --output-format json" in source

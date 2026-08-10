#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SYSTEM_NAME=${RESEARCH_RAG_BUILD_SYSTEM_NAME:-$(uname -s)}
PYTHON_COMMAND=${RESEARCH_RAG_PYTHON:-python}
DEPLOY_COMMAND=${PYSIDE6_DEPLOY:-pyside6-deploy}
SECURITY_COMMAND=${RESEARCH_RAG_SECURITY_COMMAND:-/usr/bin/security}
CODESIGN_COMMAND=${RESEARCH_RAG_CODESIGN_COMMAND:-/usr/bin/codesign}
XCRUN_COMMAND=${RESEARCH_RAG_XCRUN_COMMAND:-/usr/bin/xcrun}
DITTO_COMMAND=${RESEARCH_RAG_DITTO_COMMAND:-/usr/bin/ditto}
HDIUTIL_COMMAND=${RESEARCH_RAG_HDIUTIL_COMMAND:-/usr/bin/hdiutil}
LIPO_COMMAND=${RESEARCH_RAG_LIPO_COMMAND:-/usr/bin/lipo}
SPCTL_COMMAND=${RESEARCH_RAG_SPCTL_COMMAND:-/usr/sbin/spctl}
SHASUM_COMMAND=${RESEARCH_RAG_SHASUM_COMMAND:-/usr/bin/shasum}
ICON_GENERATOR=${RESEARCH_RAG_ICON_GENERATOR:-$SCRIPT_DIR/generate_app_icon.py}
ICON_OUTPUT=${RESEARCH_RAG_ICON_OUTPUT:-$REPOSITORY_ROOT/build/generated/ResearchRAG.icns}
DMG_PACKAGER=${RESEARCH_RAG_DMG_PACKAGER:-$SCRIPT_DIR/package_macos_dmg.sh}
RELEASE_DIRECTORY=${RESEARCH_RAG_RELEASE_DIR:-$REPOSITORY_ROOT/build/release}
IDENTITY=${RESEARCH_RAG_DEVELOPER_ID_APPLICATION:-}
NOTARY_PROFILE=${RESEARCH_RAG_NOTARY_PROFILE:-}
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    shift
fi

if [ "$#" -ne 0 ]; then
    echo "Usage: $0 [--dry-run]" >&2
    exit 2
fi

if [ "$SYSTEM_NAME" != "Darwin" ]; then
    echo "Error: the Research RAG release can only be prepared on macOS." >&2
    exit 1
fi

if ! command -v "$PYTHON_COMMAND" >/dev/null 2>&1; then
    echo "Error: Python was not found. Activate the project virtual environment." >&2
    exit 1
fi

VERSION=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" version)
BUNDLE_IDENTIFIER=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" bundle-identifier)
DMG_IDENTIFIER=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" dmg-identifier)
HOST_ARCHITECTURE=$(uname -m)
EXPECTED_APP="$RELEASE_DIRECTORY/Research RAG.app"
DRY_RUN_DMG="$RELEASE_DIRECTORY/Research-RAG-$VERSION-macos-$HOST_ARCHITECTURE.dmg"

if [ "$DRY_RUN" = true ]; then
    echo "Research RAG macOS release dry run"
    echo "Version: $VERSION"
    echo "Bundle identifier: $BUNDLE_IDENTIFIER"
    echo "DMG identifier: $DMG_IDENTIFIER"
    echo "Application: $EXPECTED_APP"
    echo "Application icon: $ICON_OUTPUT"
    echo "Expected release DMG (host architecture; actual build is inspected): $DRY_RUN_DMG"
    echo "Expected checksum: $DRY_RUN_DMG.sha256"
    echo "Required environment: RESEARCH_RAG_DEVELOPER_ID_APPLICATION"
    echo "Required environment: RESEARCH_RAG_NOTARY_PROFILE"
    echo "Stages: generate icon; build app with native Developer ID signing and hardened runtime"
    echo "Stages: verify signed app metadata, icon, signature, timestamp, and entitlements"
    echo "Stages: create UDZO DMG with app and Applications symlink; sign and verify DMG"
    echo "Stages: submit the DMG itself with notarytool --wait"
    echo "Stages: staple and validate DMG; verify codesign, hdiutil, and Gatekeeper"
    echo "Stages: generate SHA-256 checksum after stapling"
    echo "Dry run performs no build, signing, Keychain mutation, or Apple network request."
    exit 0
fi

if [ -z "$IDENTITY" ]; then
    echo "Error: RESEARCH_RAG_DEVELOPER_ID_APPLICATION is required for a release build." >&2
    exit 1
fi

case "$IDENTITY" in
    "Developer ID Application: "*) ;;
    *)
        echo "Error: the signing identity must be a Developer ID Application identity." >&2
        exit 1
        ;;
esac

if [ -z "$NOTARY_PROFILE" ]; then
    echo "Error: RESEARCH_RAG_NOTARY_PROFILE is required for notarization." >&2
    exit 1
fi

for required_command in \
    "$DEPLOY_COMMAND" "$SECURITY_COMMAND" "$CODESIGN_COMMAND" \
    "$XCRUN_COMMAND" "$DITTO_COMMAND" "$HDIUTIL_COMMAND" \
    "$LIPO_COMMAND" "$SHASUM_COMMAND"
do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Error: required release command was not found: $required_command" >&2
        exit 1
    fi
done

if [ ! -x "$DMG_PACKAGER" ]; then
    echo "Error: DMG packaging helper is not executable: $DMG_PACKAGER" >&2
    exit 1
fi
if ! "$XCRUN_COMMAND" --find notarytool >/dev/null 2>&1; then
    echo "Error: xcrun could not find notarytool." >&2
    exit 1
fi
if ! "$XCRUN_COMMAND" --find stapler >/dev/null 2>&1; then
    echo "Error: xcrun could not find stapler." >&2
    exit 1
fi

AVAILABLE_IDENTITIES=$("$SECURITY_COMMAND" find-identity -v -p codesigning)
if ! printf '%s\n' "$AVAILABLE_IDENTITIES" | grep -F "$IDENTITY" >/dev/null; then
    echo "Error: the requested Developer ID Application identity is not available." >&2
    exit 1
fi
unset AVAILABLE_IDENTITIES

cd "$REPOSITORY_ROOT"
mkdir -p "$RELEASE_DIRECTORY"

NUITKA_VERSION=$(awk -F'==' '/^packages = Nuitka==/ {print $2; exit}' \
    "$REPOSITORY_ROOT/pysidedeploy.spec")
if [ -z "$NUITKA_VERSION" ]; then
    echo "Error: pysidedeploy.spec must pin packages = Nuitka==<version>." >&2
    exit 1
fi

"$PYTHON_COMMAND" "$ICON_GENERATOR" --output "$ICON_OUTPUT"
if [ ! -f "$ICON_OUTPUT" ]; then
    echo "Error: icon generator did not create $ICON_OUTPUT" >&2
    exit 1
fi

RELEASE_SPEC=$(mktemp "$REPOSITORY_ROOT/.pysidedeploy.release.XXXXXX")
trap 'rm -f -- "$RELEASE_SPEC"' EXIT HUP INT TERM
"$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" prepare-spec \
    --source "$REPOSITORY_ROOT/pysidedeploy.spec" \
    --destination "$RELEASE_SPEC" \
    --exec-directory "$RELEASE_DIRECTORY" \
    --bundle-metadata-plugin "$SCRIPT_DIR/nuitka_bundle_metadata_plugin.py" \
    --icon "$ICON_OUTPUT" \
    --signing-identity "$IDENTITY"

NOTARY_RESULT="$RELEASE_DIRECTORY/notarytool-result.json"
rm -rf -- "$EXPECTED_APP"
rm -f -- "$NOTARY_RESULT"

RESEARCH_RAG_BUNDLE_VERSION="$VERSION" \
    "$DEPLOY_COMMAND" -c "$RELEASE_SPEC" --mode standalone \
        --nuitka-version "$NUITKA_VERSION" -f

EXPECTED_EXECUTABLE="$EXPECTED_APP/Contents/MacOS/run_gui"
EXPECTED_ICON_RESOURCE="$EXPECTED_APP/Contents/Resources/ResearchRAG.icns"
if [ ! -x "$EXPECTED_EXECUTABLE" ]; then
    echo "Error: the release bundle has no executable at $EXPECTED_EXECUTABLE" >&2
    exit 1
fi
if [ ! -f "$EXPECTED_ICON_RESOURCE" ]; then
    echo "Error: the release bundle has no icon at $EXPECTED_ICON_RESOURCE" >&2
    exit 1
fi

"$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" verify-bundle \
    --info-plist "$EXPECTED_APP/Contents/Info.plist"
"$CODESIGN_COMMAND" --verify --deep --strict --verbose=2 "$EXPECTED_APP"

SIGNATURE_DETAILS=$("$CODESIGN_COMMAND" -dvvv "$EXPECTED_APP" 2>&1)
if ! printf '%s\n' "$SIGNATURE_DETAILS" | grep -F "Authority=$IDENTITY" >/dev/null; then
    echo "Error: the bundle was not signed by the requested Developer ID identity." >&2
    exit 1
fi
if ! printf '%s\n' "$SIGNATURE_DETAILS" | grep -E '^flags=.*runtime' >/dev/null; then
    echo "Error: the bundle signature does not enable the hardened runtime." >&2
    exit 1
fi
if ! printf '%s\n' "$SIGNATURE_DETAILS" | grep -E '^Timestamp=' >/dev/null; then
    echo "Error: the bundle signature does not contain a secure timestamp." >&2
    exit 1
fi
unset SIGNATURE_DETAILS

ENTITLEMENTS=$("$CODESIGN_COMMAND" -d --entitlements :- "$EXPECTED_APP" 2>&1 || true)
if printf '%s\n' "$ENTITLEMENTS" | grep -F 'com.apple.security.get-task-allow' >/dev/null; then
    echo "Error: release entitlements must not contain com.apple.security.get-task-allow." >&2
    exit 1
fi
unset ENTITLEMENTS

ARCHITECTURES=$("$LIPO_COMMAND" -archs "$EXPECTED_EXECUTABLE")
case " $ARCHITECTURES " in
    *" arm64 "*" x86_64 "*|*" x86_64 "*" arm64 "*) ARCHITECTURE=universal2 ;;
    " arm64 ") ARCHITECTURE=arm64 ;;
    " x86_64 ") ARCHITECTURE=x86_64 ;;
    *)
        echo "Error: unsupported application architecture list: $ARCHITECTURES" >&2
        exit 1
        ;;
esac

FINAL_DMG="$RELEASE_DIRECTORY/Research-RAG-$VERSION-macos-$ARCHITECTURE.dmg"
CHECKSUM="$FINAL_DMG.sha256"
rm -f -- "$FINAL_DMG" "$CHECKSUM"

env \
    RESEARCH_RAG_BUILD_SYSTEM_NAME="$SYSTEM_NAME" \
    RESEARCH_RAG_PYTHON="$PYTHON_COMMAND" \
    RESEARCH_RAG_HDIUTIL_COMMAND="$HDIUTIL_COMMAND" \
    RESEARCH_RAG_DITTO_COMMAND="$DITTO_COMMAND" \
    RESEARCH_RAG_LIPO_COMMAND="$LIPO_COMMAND" \
    "$DMG_PACKAGER" "$EXPECTED_APP" "$FINAL_DMG"

"$CODESIGN_COMMAND" \
    --sign "$IDENTITY" \
    --timestamp \
    --identifier "$DMG_IDENTIFIER" \
    "$FINAL_DMG"
"$CODESIGN_COMMAND" --verify --strict --verbose=2 "$FINAL_DMG"
"$HDIUTIL_COMMAND" verify "$FINAL_DMG"

DMG_SIGNATURE_DETAILS=$("$CODESIGN_COMMAND" -dvvv "$FINAL_DMG" 2>&1)
if ! printf '%s\n' "$DMG_SIGNATURE_DETAILS" | grep -F "Authority=$IDENTITY" >/dev/null; then
    echo "Error: the DMG was not signed by the requested Developer ID identity." >&2
    exit 1
fi
if ! printf '%s\n' "$DMG_SIGNATURE_DETAILS" | grep -F "Identifier=$DMG_IDENTIFIER" >/dev/null; then
    echo "Error: the DMG signature identifier is incorrect." >&2
    exit 1
fi
if ! printf '%s\n' "$DMG_SIGNATURE_DETAILS" | grep -E '^Timestamp=' >/dev/null; then
    echo "Error: the DMG signature does not contain a secure timestamp." >&2
    exit 1
fi
unset DMG_SIGNATURE_DETAILS

if ! "$XCRUN_COMMAND" notarytool submit "$FINAL_DMG" \
    --keychain-profile "$NOTARY_PROFILE" --wait --output-format json \
    >"$NOTARY_RESULT"; then
    SUBMISSION_ID=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
        --pyproject "$REPOSITORY_ROOT/pyproject.toml" notary-result \
        --result "$NOTARY_RESULT" --field id 2>/dev/null || true)
    echo "Error: notarization submission failed. Result: $NOTARY_RESULT" >&2
    if [ -n "$SUBMISSION_ID" ]; then
        echo "Notarization submission ID: $SUBMISSION_ID" >&2
        "$XCRUN_COMMAND" notarytool log "$SUBMISSION_ID" \
            --keychain-profile "$NOTARY_PROFILE" || true
    fi
    exit 1
fi

SUBMISSION_ID=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" notary-result \
    --result "$NOTARY_RESULT" --field id)
NOTARY_STATUS=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" notary-result \
    --result "$NOTARY_RESULT" --field status)
echo "Notarization submission ID: $SUBMISSION_ID"
if [ "$NOTARY_STATUS" != "Accepted" ]; then
    echo "Error: notarization status was $NOTARY_STATUS. Result: $NOTARY_RESULT" >&2
    "$XCRUN_COMMAND" notarytool log "$SUBMISSION_ID" \
        --keychain-profile "$NOTARY_PROFILE" || true
    exit 1
fi

"$XCRUN_COMMAND" stapler staple "$FINAL_DMG"
"$XCRUN_COMMAND" stapler validate "$FINAL_DMG"
"$CODESIGN_COMMAND" --verify --strict --verbose=2 "$FINAL_DMG"
"$HDIUTIL_COMMAND" verify "$FINAL_DMG"
if command -v "$SPCTL_COMMAND" >/dev/null 2>&1; then
    "$SPCTL_COMMAND" --assess --type open \
        --context context:primary-signature --verbose=2 "$FINAL_DMG"
else
    echo "Warning: spctl was not found; Gatekeeper assessment was skipped." >&2
fi

FINAL_DMG_NAME=$(basename -- "$FINAL_DMG")
CHECKSUM_NAME=$(basename -- "$CHECKSUM")
(
    cd "$RELEASE_DIRECTORY"
    "$SHASUM_COMMAND" -a 256 "$FINAL_DMG_NAME" >"$CHECKSUM_NAME"
)
if [ ! -s "$CHECKSUM" ]; then
    echo "Error: checksum was not created: $CHECKSUM" >&2
    exit 1
fi

echo "Notarized macOS release DMG: $FINAL_DMG"
echo "SHA-256 checksum: $CHECKSUM"

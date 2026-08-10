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
LIPO_COMMAND=${RESEARCH_RAG_LIPO_COMMAND:-/usr/bin/lipo}
SPCTL_COMMAND=${RESEARCH_RAG_SPCTL_COMMAND:-/usr/sbin/spctl}
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
HOST_ARCHITECTURE=$(uname -m)
EXPECTED_APP="$RELEASE_DIRECTORY/Research RAG.app"
DRY_RUN_ZIP="$RELEASE_DIRECTORY/Research-RAG-$VERSION-macos-$HOST_ARCHITECTURE.zip"

if [ "$DRY_RUN" = true ]; then
    echo "Research RAG macOS release dry run"
    echo "Version: $VERSION"
    echo "Bundle identifier: $BUNDLE_IDENTIFIER"
    echo "Application: $EXPECTED_APP"
    echo "Expected release ZIP (host architecture; actual build is inspected): $DRY_RUN_ZIP"
    echo "Required environment: RESEARCH_RAG_DEVELOPER_ID_APPLICATION"
    echo "Required environment: RESEARCH_RAG_NOTARY_PROFILE"
    echo "Stages: build with native Developer ID signing and hardened runtime"
    echo "Stages: verify signature, secure timestamp, runtime flag, and entitlements"
    echo "Stages: create notarization ZIP; submit with notarytool --wait"
    echo "Stages: staple; validate; verify with codesign and Gatekeeper"
    echo "Stages: inspect actual architecture and create the final release ZIP"
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
    "$XCRUN_COMMAND" "$DITTO_COMMAND" "$LIPO_COMMAND"
do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Error: required release command was not found: $required_command" >&2
        exit 1
    fi
done

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

RELEASE_SPEC=$(mktemp "$REPOSITORY_ROOT/.pysidedeploy.release.XXXXXX")
trap 'rm -f -- "$RELEASE_SPEC"' EXIT HUP INT TERM
"$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" prepare-spec \
    --source "$REPOSITORY_ROOT/pysidedeploy.spec" \
    --destination "$RELEASE_SPEC" \
    --exec-directory "$RELEASE_DIRECTORY" \
    --bundle-metadata-plugin "$SCRIPT_DIR/nuitka_bundle_metadata_plugin.py" \
    --signing-identity "$IDENTITY"

# Remove only this workflow's known outputs. The release build must never use a
# stale application bundle or notarization archive as evidence of success.
INTERMEDIATE_ZIP="$RELEASE_DIRECTORY/Research-RAG-$VERSION-notarization.zip"
NOTARY_RESULT="$RELEASE_DIRECTORY/notarytool-result.json"
rm -rf -- "$EXPECTED_APP"
rm -f -- "$INTERMEDIATE_ZIP" "$NOTARY_RESULT"

RESEARCH_RAG_BUNDLE_VERSION="$VERSION" \
    "$DEPLOY_COMMAND" -c "$RELEASE_SPEC" --mode standalone \
        --nuitka-version "$NUITKA_VERSION" -f

EXPECTED_EXECUTABLE="$EXPECTED_APP/Contents/MacOS/run_gui"
if [ ! -x "$EXPECTED_EXECUTABLE" ]; then
    echo "Error: the release bundle has no executable at $EXPECTED_EXECUTABLE" >&2
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

"$DITTO_COMMAND" -c -k --keepParent "$EXPECTED_APP" "$INTERMEDIATE_ZIP"

if ! "$XCRUN_COMMAND" notarytool submit "$INTERMEDIATE_ZIP" \
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

"$XCRUN_COMMAND" stapler staple "$EXPECTED_APP"
"$XCRUN_COMMAND" stapler validate "$EXPECTED_APP"
"$CODESIGN_COMMAND" --verify --deep --strict --verbose=2 "$EXPECTED_APP"
if command -v "$SPCTL_COMMAND" >/dev/null 2>&1; then
    "$SPCTL_COMMAND" --assess --type execute --verbose=2 "$EXPECTED_APP"
else
    echo "Warning: spctl was not found; Gatekeeper assessment was skipped." >&2
fi

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

FINAL_ZIP="$RELEASE_DIRECTORY/Research-RAG-$VERSION-macos-$ARCHITECTURE.zip"
rm -f -- "$FINAL_ZIP"
"$DITTO_COMMAND" -c -k --keepParent "$EXPECTED_APP" "$FINAL_ZIP"

echo "Notarized macOS application: $EXPECTED_APP"
echo "Final release ZIP: $FINAL_ZIP"

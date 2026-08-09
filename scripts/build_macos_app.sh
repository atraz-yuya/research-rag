#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SYSTEM_NAME=${RESEARCH_RAG_BUILD_SYSTEM_NAME:-$(uname -s)}
DEPLOY_COMMAND=${PYSIDE6_DEPLOY:-pyside6-deploy}
EXPECTED_APP="$REPOSITORY_ROOT/build/deploy/Research RAG.app"
EXPECTED_EXECUTABLE="$EXPECTED_APP/Contents/MacOS/run_gui"
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
    echo "Error: the Research RAG application bundle can only be built on macOS." >&2
    exit 1
fi

if ! command -v "$DEPLOY_COMMAND" >/dev/null 2>&1; then
    echo "Error: pyside6-deploy was not found. Activate the project virtual environment and install the project dependencies." >&2
    exit 1
fi

cd "$REPOSITORY_ROOT"
mkdir -p build/deploy

NUITKA_VERSION=$(awk -F'==' '/^packages = Nuitka==/ {print $2; exit}' \
    "$REPOSITORY_ROOT/pysidedeploy.spec")
if [ -z "$NUITKA_VERSION" ]; then
    echo "Error: pysidedeploy.spec must pin packages = Nuitka==<version>." >&2
    exit 1
fi

# pyside6-deploy updates its config during a real build (for example, by
# resolving the bundled default icon). Build from a disposable copy so the
# checked-in specification remains portable between developer machines.
BUILD_SPEC=$(mktemp "$REPOSITORY_ROOT/.pysidedeploy.build.XXXXXX")
trap 'rm -f -- "$BUILD_SPEC"' EXIT HUP INT TERM
cp "$REPOSITORY_ROOT/pysidedeploy.spec" "$BUILD_SPEC"

if [ "$DRY_RUN" = true ]; then
    "$DEPLOY_COMMAND" -c "$BUILD_SPEC" --mode standalone \
        --nuitka-version "$NUITKA_VERSION" --dry-run -f
    exit 0
fi

# Remove only the expected ignored output so a failed deployment cannot be
# mistaken for success because of a stale bundle from an earlier build.
rm -rf -- "$EXPECTED_APP"
"$DEPLOY_COMMAND" -c "$BUILD_SPEC" --mode standalone \
    --nuitka-version "$NUITKA_VERSION" -f

if [ ! -d "$EXPECTED_APP" ]; then
    echo "Error: pyside6-deploy finished without creating $EXPECTED_APP" >&2
    exit 1
fi

if [ ! -x "$EXPECTED_EXECUTABLE" ]; then
    echo "Error: pyside6-deploy created a bundle without an executable at $EXPECTED_EXECUTABLE" >&2
    exit 1
fi

# macOS code signing rejects Finder/resource-fork extended attributes. Clear
# them immediately before the mandatory local ad-hoc signature, then validate
# the complete bundle rather than trusting pyside6-deploy's exit status alone.
if ! (/usr/bin/xattr -cr "$EXPECTED_APP" && \
    /usr/bin/codesign --force --deep --sign - "$EXPECTED_APP" && \
    /usr/bin/codesign --verify --deep --strict "$EXPECTED_APP"); then
    echo "Error: unable to ad-hoc sign and validate the generated application." >&2
    exit 1
fi

echo "Built macOS application: $EXPECTED_APP"

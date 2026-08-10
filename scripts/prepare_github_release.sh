#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON_COMMAND=${RESEARCH_RAG_PYTHON:-python}
GH_COMMAND=${RESEARCH_RAG_GH_COMMAND:-gh}
GIT_COMMAND=${RESEARCH_RAG_GIT_COMMAND:-git}
SHASUM_COMMAND=${RESEARCH_RAG_SHASUM_COMMAND:-/usr/bin/shasum}
LIPO_COMMAND=${RESEARCH_RAG_LIPO_COMMAND:-/usr/bin/lipo}
RELEASE_DIRECTORY=${RESEARCH_RAG_RELEASE_DIR:-$REPOSITORY_ROOT/build/release}
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    shift
fi

if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [--dry-run] [release.dmg]" >&2
    exit 2
fi

if ! command -v "$PYTHON_COMMAND" >/dev/null 2>&1; then
    echo "Error: Python was not found. Activate the project virtual environment." >&2
    exit 1
fi

VERSION=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" version)
TAG="v$VERSION"
HOST_ARCHITECTURE=$(uname -m)
DEFAULT_DMG="$RELEASE_DIRECTORY/Research-RAG-$VERSION-macos-$HOST_ARCHITECTURE.dmg"
DMG_PATH=${1:-$DEFAULT_DMG}
CHECKSUM_PATH="$DMG_PATH.sha256"
RELEASE_TITLE="Research RAG $VERSION"

if [ "$DRY_RUN" = true ]; then
    echo "Research RAG GitHub Release preparation dry run"
    echo "Version: $VERSION"
    echo "Expected existing tag: $TAG"
    echo "DMG: $DMG_PATH"
    echo "Checksum: $CHECKSUM_PATH"
    echo "Release title: $RELEASE_TITLE"
    echo "Release state: draft"
    echo "Validation: existing local and remote tag, intended commit, artifacts, checksum, and architecture"
    echo "Creation: gh release create --verify-tag --draft with the DMG and checksum"
    echo "Dry run creates no tag, push, GitHub Release, or asset upload."
    exit 0
fi

for required_command in \
    "$GH_COMMAND" "$GIT_COMMAND" "$SHASUM_COMMAND" "$LIPO_COMMAND"
do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Error: required GitHub Release command was not found: $required_command" >&2
        exit 1
    fi
done

if [ ! -f "$DMG_PATH" ]; then
    echo "Error: release DMG does not exist: $DMG_PATH" >&2
    exit 1
fi
if [ ! -f "$CHECKSUM_PATH" ]; then
    echo "Error: release checksum does not exist: $CHECKSUM_PATH" >&2
    exit 1
fi

DMG_FILENAME=$(basename -- "$DMG_PATH")
case "$DMG_FILENAME" in
    "Research-RAG-$VERSION-macos-arm64.dmg") ARTIFACT_ARCHITECTURE=arm64 ;;
    "Research-RAG-$VERSION-macos-x86_64.dmg") ARTIFACT_ARCHITECTURE=x86_64 ;;
    "Research-RAG-$VERSION-macos-universal2.dmg") ARTIFACT_ARCHITECTURE=universal2 ;;
    *)
        echo "Error: release DMG filename does not match version $VERSION and a supported architecture." >&2
        exit 1
        ;;
esac

RELEASE_APP=${RESEARCH_RAG_RELEASE_APP:-$RELEASE_DIRECTORY/Research RAG.app}
RELEASE_EXECUTABLE="$RELEASE_APP/Contents/MacOS/run_gui"
if [ -x "$RELEASE_EXECUTABLE" ]; then
    APP_ARCHITECTURES=$("$LIPO_COMMAND" -archs "$RELEASE_EXECUTABLE")
    case " $APP_ARCHITECTURES " in
        *" arm64 "*" x86_64 "*|*" x86_64 "*" arm64 "*) APP_ARCHITECTURE=universal2 ;;
        " arm64 ") APP_ARCHITECTURE=arm64 ;;
        " x86_64 ") APP_ARCHITECTURE=x86_64 ;;
        *)
            echo "Error: unsupported application architecture list: $APP_ARCHITECTURES" >&2
            exit 1
            ;;
    esac
    if [ "$APP_ARCHITECTURE" != "$ARTIFACT_ARCHITECTURE" ]; then
        echo "Error: DMG architecture label does not match the release application." >&2
        exit 1
    fi
else
    echo "Warning: release application is unavailable; architecture was validated from the canonical DMG filename only." >&2
fi

CHECKSUM_DIRECTORY=$(dirname -- "$CHECKSUM_PATH")
CHECKSUM_FILENAME=$(basename -- "$CHECKSUM_PATH")
(
    cd "$CHECKSUM_DIRECTORY"
    "$SHASUM_COMMAND" -a 256 -c "$CHECKSUM_FILENAME"
)

if ! "$GIT_COMMAND" show-ref --verify --quiet "refs/tags/$TAG"; then
    echo "Error: required existing local tag was not found: $TAG" >&2
    exit 1
fi
TAG_COMMIT=$("$GIT_COMMAND" rev-parse "$TAG^{commit}")
HEAD_COMMIT=$("$GIT_COMMAND" rev-parse HEAD)
if [ "$TAG_COMMIT" != "$HEAD_COMMIT" ]; then
    echo "Error: $TAG does not point to the intended current commit." >&2
    exit 1
fi
LOCAL_TAG_OBJECT=$("$GIT_COMMAND" rev-parse "$TAG")
REMOTE_TAG_OBJECT=$("$GIT_COMMAND" ls-remote --exit-code --tags origin \
    "refs/tags/$TAG" | awk 'NR == 1 {print $1}')
if [ -z "$REMOTE_TAG_OBJECT" ] || [ "$REMOTE_TAG_OBJECT" != "$LOCAL_TAG_OBJECT" ]; then
    echo "Error: remote $TAG is missing or differs from the local tag." >&2
    exit 1
fi

"$GH_COMMAND" auth status
"$GH_COMMAND" release create "$TAG" \
    --verify-tag \
    --draft \
    --title "$RELEASE_TITLE" \
    --generate-notes \
    "$DMG_PATH" \
    "$CHECKSUM_PATH"

echo "Created draft GitHub Release for $TAG. Review it manually before publishing."

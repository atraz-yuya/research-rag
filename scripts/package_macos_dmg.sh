#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SYSTEM_NAME=${RESEARCH_RAG_BUILD_SYSTEM_NAME:-$(uname -s)}
PYTHON_COMMAND=${RESEARCH_RAG_PYTHON:-python}
HDIUTIL_COMMAND=${RESEARCH_RAG_HDIUTIL_COMMAND:-/usr/bin/hdiutil}
DITTO_COMMAND=${RESEARCH_RAG_DITTO_COMMAND:-/usr/bin/ditto}
LIPO_COMMAND=${RESEARCH_RAG_LIPO_COMMAND:-/usr/bin/lipo}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: $0 <Research RAG.app> [output.dmg]" >&2
    exit 2
fi

if [ "$SYSTEM_NAME" != "Darwin" ]; then
    echo "Error: Research RAG DMG packaging requires macOS." >&2
    exit 1
fi

for required_command in \
    "$PYTHON_COMMAND" "$HDIUTIL_COMMAND" "$DITTO_COMMAND" "$LIPO_COMMAND"
do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Error: required DMG packaging command was not found: $required_command" >&2
        exit 1
    fi
done

APP_PATH=$1
EXPECTED_EXECUTABLE="$APP_PATH/Contents/MacOS/run_gui"
if [ ! -d "$APP_PATH" ] || [ ! -x "$EXPECTED_EXECUTABLE" ]; then
    echo "Error: a built Research RAG.app is required: $APP_PATH" >&2
    exit 1
fi

VERSION=$("$PYTHON_COMMAND" "$SCRIPT_DIR/release_metadata.py" \
    --pyproject "$REPOSITORY_ROOT/pyproject.toml" version)
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

EXPECTED_FILENAME="Research-RAG-$VERSION-macos-$ARCHITECTURE.dmg"
OUTPUT_PATH=${2:-$REPOSITORY_ROOT/build/dmg/$EXPECTED_FILENAME}
if [ "$(basename -- "$OUTPUT_PATH")" != "$EXPECTED_FILENAME" ]; then
    echo "Error: DMG filename must be $EXPECTED_FILENAME" >&2
    exit 1
fi

OUTPUT_DIRECTORY=$(dirname -- "$OUTPUT_PATH")
mkdir -p "$OUTPUT_DIRECTORY"
if [ -d "$OUTPUT_PATH" ]; then
    echo "Error: DMG output path is a directory: $OUTPUT_PATH" >&2
    exit 1
fi
rm -f -- "$OUTPUT_PATH"

STAGING_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/research-rag-dmg.XXXXXX")
STAGING_DIRECTORY="$STAGING_ROOT/Research RAG"
cleanup() {
    rm -rf -- "$STAGING_ROOT"
}
trap cleanup EXIT HUP INT TERM
mkdir "$STAGING_DIRECTORY"

"$DITTO_COMMAND" "$APP_PATH" "$STAGING_DIRECTORY/Research RAG.app"
ln -s /Applications "$STAGING_DIRECTORY/Applications"

"$HDIUTIL_COMMAND" create \
    -volname "Research RAG" \
    -srcfolder "$STAGING_DIRECTORY" \
    -format UDZO \
    -ov \
    "$OUTPUT_PATH"
"$HDIUTIL_COMMAND" verify "$OUTPUT_PATH"

if [ ! -f "$OUTPUT_PATH" ]; then
    echo "Error: hdiutil did not create $OUTPUT_PATH" >&2
    exit 1
fi

echo "Created macOS DMG: $OUTPUT_PATH"

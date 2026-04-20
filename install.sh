#!/usr/bin/env bash
#
# install.sh - Symlink stay-awake into ~/.local/bin.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_BIN="$HOME/.local/bin/stay-awake"
SOURCE_BIN="$SCRIPT_DIR/src/stay-awake"

if [[ ! -x "$SOURCE_BIN" ]]; then
    echo "error: $SOURCE_BIN is not executable" >&2
    exit 1
fi

mkdir -p "$HOME/.local/bin"

# Remove any stale file/symlink so we always point at this checkout.
if [[ -L "$INSTALL_BIN" || -e "$INSTALL_BIN" ]]; then
    rm -f "$INSTALL_BIN"
fi

ln -s "$SOURCE_BIN" "$INSTALL_BIN"
echo "Symlinked: $INSTALL_BIN -> $SOURCE_BIN"

# Sanity-check systemd-inhibit presence (non-fatal; warn only).
if ! command -v systemd-inhibit >/dev/null 2>&1; then
    echo "warning: systemd-inhibit not found on PATH; stay-awake needs it at runtime" >&2
fi

# Warn if ~/.local/bin is not on PATH.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "note: $HOME/.local/bin is not on your PATH; add it or invoke by full path" >&2 ;;
esac

echo "Done. Try: stay-awake --help"

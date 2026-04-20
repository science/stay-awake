#!/usr/bin/env bash
#
# uninstall.sh - Remove the stay-awake symlink from ~/.local/bin.
#

set -euo pipefail

INSTALL_BIN="$HOME/.local/bin/stay-awake"

if [[ -L "$INSTALL_BIN" || -f "$INSTALL_BIN" ]]; then
    rm -f "$INSTALL_BIN"
    echo "Removed: $INSTALL_BIN"
else
    echo "Nothing to remove at $INSTALL_BIN"
fi

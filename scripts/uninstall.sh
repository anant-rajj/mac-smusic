#!/usr/bin/env bash
# mac-smusic: Uninstaller

set -e

echo "Uninstalling mac-smusic..."
pip3 uninstall -y mac-smusic 2>/dev/null || pip uninstall -y mac-smusic 2>/dev/null || true
rm -f /usr/local/bin/mac-smusic-engine ~/.local/bin/mac-smusic-engine
echo "✓ mac-smusic removed cleanly."

#!/usr/bin/env bash
# mac-smusic: Universal Installer for macOS

set -e

CYAN='\033[96m'
GREEN='\033[92m'
BOLD='\033[1m'
RESET='\033[0m'

echo -e "${CYAN}${BOLD}Installing mac-smusic...${RESET}"

# Install editable package via pip
if command -v pip3 >/dev/null 2>&1; then
    pip3 install -e .
elif command -v pip >/dev/null 2>&1; then
    pip install -e .
else
    echo "Error: pip is required to install mac-smusic."
    exit 1
fi

# Build native Swift engine if swiftc is available
if command -v swiftc >/dev/null 2>&1; then
    echo -e "${CYAN}Compiling native Swift CoreAudio engine...${RESET}"
    make -C "$(dirname "$0")/.."
fi

echo -e "${GREEN}${BOLD}✓ mac-smusic installed successfully!${RESET}\n"

# Display the multi-Mac connection walkthrough & command guide
if command -v mac-smusic >/dev/null 2>&1; then
    mac-smusic guide
else
    python3 -m mac_smusic.cli guide
fi

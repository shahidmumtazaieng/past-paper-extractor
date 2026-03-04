#!/bin/bash
# build.sh — One-click build script for Linux/macOS

set -e

echo "========================================"
echo " Past Paper Extractor - Build Script"
echo "========================================"
echo

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

# 2. Create virtualenv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# 3. Install deps
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

# 4. Clean
rm -rf dist build

# 5. Build
echo "Building..."
pyinstaller past_paper_extractor.spec --clean

echo
echo "========================================"
echo " BUILD COMPLETE: dist/PastPaperExtractor"
echo "========================================"

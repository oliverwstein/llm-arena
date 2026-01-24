#!/bin/bash
# Setup script for Technical Machine AI bot
# Technical Machine is a sophisticated Pokemon AI by davidstone
# https://github.com/davidstone/technical-machine

set -e

echo "=============================================="
echo "Technical Machine Setup"
echo "=============================================="
echo ""
echo "Technical Machine is a C++ Pokemon AI that requires:"
echo "  - clang trunk (latest development version)"
echo "  - mold or lld linker"
echo "  - libstdc++ (gcc 14.2.1+)"
echo "  - Boost 1.86.0+"
echo "  - TBB (Threading Building Blocks)"
echo "  - CMake 3.28+"
echo "  - ninja 1.10+"
echo ""
echo "WARNING: Technical Machine requires C++26 features (parallel execution"
echo "policies) that are NOT supported on macOS. Linux is recommended."
echo ""
echo "This is an ADVANCED setup. Most users should use the"
echo "built-in random or heuristic bots instead."
echo ""

read -p "Do you want to continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Setup cancelled."
    exit 0
fi

# Create directory for technical machine
TM_DIR="$(dirname "$0")/../technical-machine"
mkdir -p "$TM_DIR"
cd "$TM_DIR"

# Check if already cloned
if [ -d ".git" ]; then
    echo "Technical Machine already cloned. Updating..."
    git pull
    git submodule update --init
else
    echo "Cloning Technical Machine..."
    git clone https://github.com/davidstone/technical-machine.git .
    git submodule update --init
fi

# Check for required tools
echo ""
echo "Checking build dependencies..."

check_command() {
    if command -v $1 &> /dev/null; then
        echo "  ✓ $1 found"
        return 0
    else
        echo "  ✗ $1 not found"
        return 1
    fi
}

MISSING=0

check_command clang++ || MISSING=1
check_command cmake || MISSING=1
check_command ninja || MISSING=1

if [ $MISSING -eq 1 ]; then
    echo ""
    echo "Some dependencies are missing. Please install them and try again."
    echo ""
    echo "On macOS with Homebrew:"
    echo "  brew install llvm cmake ninja boost tbb"
    echo ""
    echo "On Ubuntu/Debian:"
    echo "  sudo apt install clang cmake ninja-build libboost-all-dev libtbb-dev"
    echo ""
    exit 1
fi

echo ""
echo "Attempting to build Technical Machine..."
echo "This may take several minutes..."
echo ""

# Determine compiler and flags based on platform
if [[ "$(uname)" == "Darwin" ]]; then
    # macOS: Use Homebrew LLVM and set SDK sysroot
    if [ -x "/opt/homebrew/opt/llvm/bin/clang++" ]; then
        CXX_COMPILER="/opt/homebrew/opt/llvm/bin/clang++"
    elif [ -x "/usr/local/opt/llvm/bin/clang++" ]; then
        CXX_COMPILER="/usr/local/opt/llvm/bin/clang++"
    else
        echo "ERROR: Homebrew LLVM not found. Install with: brew install llvm"
        exit 1
    fi
    SDK_PATH=$(xcrun --show-sdk-path 2>/dev/null)
    CMAKE_EXTRA_FLAGS="-DCMAKE_OSX_SYSROOT=$SDK_PATH -DCMAKE_CXX_FLAGS=-isysroot\ $SDK_PATH"
else
    # Linux: Use system clang
    CXX_COMPILER="clang++"
    CMAKE_EXTRA_FLAGS=""
fi

echo "Using compiler: $CXX_COMPILER"

# Configure
cmake -G"Ninja" -B build \
    -DCMAKE_CXX_COMPILER="$CXX_COMPILER" \
    -DCMAKE_BUILD_TYPE=Release \
    $CMAKE_EXTRA_FLAGS \
    2>&1 || {
    echo ""
    echo "CMake configuration failed."
    echo "Technical Machine requires very specific compiler versions."
    echo "See documentation/building.md in the technical-machine directory."
    exit 1
}

# Build
cmake --build build 2>&1 || {
    echo ""
    echo "Build failed."
    echo "Technical Machine requires clang trunk (development version)."
    echo "Your clang version may be too old."
    exit 1
}

echo ""
echo "=============================================="
echo "Technical Machine built successfully!"
echo "=============================================="
echo ""
echo "The AI executable is at: $TM_DIR/build/ai"
echo ""
echo "To configure it, edit: $TM_DIR/build/settings/settings.json"
echo ""
echo "To run against Pokemon Showdown, the settings.json needs:"
echo "  - server: Your Pokemon Showdown server URL"
echo "  - username: Bot username"
echo "  - password: Bot password (if required)"
echo "  - team: Path to team file or directory"
echo ""

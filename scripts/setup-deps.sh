#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Alpaca Paper Trading CLI — System Dependency Installer
# ──────────────────────────────────────────────────────────────────────
# Detects OS and installs all required system dependencies:
#   - Python 3.10+
#   - pip
#   - tmux
#   - git
#
# Usage:
#   bash scripts/setup-deps.sh
#
# Supports: macOS (Homebrew), Ubuntu/Debian (apt), Fedora/RHEL (dnf),
#           Arch (pacman), Alpine (apk), Windows (WSL)
# ──────────────────────────────────────────────────────────────────────

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERR]${NC}  $1"; }

# ── Detect OS ─────────────────────────────────────────────────────────

detect_os() {
    case "$(uname -s)" in
        Darwin)
            OS="macos"
            ;;
        Linux)
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                case "$ID" in
                    ubuntu|debian|pop|linuxmint|elementary)
                        OS="debian"
                        ;;
                    fedora|rhel|centos|rocky|alma)
                        OS="fedora"
                        ;;
                    arch|manjaro|endeavouros)
                        OS="arch"
                        ;;
                    alpine)
                        OS="alpine"
                        ;;
                    *)
                        OS="linux-unknown"
                        ;;
                esac
            else
                OS="linux-unknown"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            OS="windows"
            ;;
        *)
            OS="unknown"
            ;;
    esac
    info "Detected OS: $OS"
}

# ── Check if command exists ───────────────────────────────────────────

has() {
    command -v "$1" &> /dev/null
}

# ── Install package manager (macOS) ──────────────────────────────────

ensure_brew() {
    if ! has brew; then
        warn "Homebrew not found. Installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        success "Homebrew installed"
    else
        success "Homebrew found"
    fi
}

# ── Install Python ────────────────────────────────────────────────────

install_python() {
    if has python3; then
        PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
            success "Python $PY_VERSION found (>= 3.10 required)"
            return
        else
            warn "Python $PY_VERSION found but 3.10+ required"
        fi
    fi

    info "Installing Python 3..."
    case "$OS" in
        macos)
            brew install python@3.12
            ;;
        debian)
            sudo apt-get update -qq
            sudo apt-get install -y -qq python3 python3-pip python3-venv
            ;;
        fedora)
            sudo dnf install -y python3 python3-pip
            ;;
        arch)
            sudo pacman -S --noconfirm python python-pip
            ;;
        alpine)
            sudo apk add python3 py3-pip
            ;;
        *)
            error "Cannot auto-install Python on $OS. Install Python 3.10+ manually."
            exit 1
            ;;
    esac
    success "Python installed: $(python3 --version)"
}

# ── Install pip ───────────────────────────────────────────────────────

install_pip() {
    if has pip3 || has pip; then
        success "pip found"
        return
    fi

    info "Installing pip..."
    case "$OS" in
        macos)
            python3 -m ensurepip --upgrade
            ;;
        debian)
            sudo apt-get install -y -qq python3-pip
            ;;
        fedora)
            sudo dnf install -y python3-pip
            ;;
        arch)
            sudo pacman -S --noconfirm python-pip
            ;;
        alpine)
            sudo apk add py3-pip
            ;;
        *)
            python3 -m ensurepip --upgrade 2>/dev/null || {
                error "Cannot install pip. Install manually."
                exit 1
            }
            ;;
    esac
    success "pip installed"
}

# ── Install tmux ──────────────────────────────────────────────────────

install_tmux() {
    if has tmux; then
        success "tmux found: $(tmux -V)"
        return
    fi

    info "Installing tmux..."
    case "$OS" in
        macos)
            brew install tmux
            ;;
        debian)
            sudo apt-get update -qq
            sudo apt-get install -y -qq tmux
            ;;
        fedora)
            sudo dnf install -y tmux
            ;;
        arch)
            sudo pacman -S --noconfirm tmux
            ;;
        alpine)
            sudo apk add tmux
            ;;
        windows)
            warn "tmux is not natively available on Windows."
            warn "Use WSL (Windows Subsystem for Linux) and run this script inside WSL."
            warn "  wsl --install"
            warn "  wsl"
            warn "  bash scripts/setup-deps.sh"
            return
            ;;
        *)
            error "Cannot auto-install tmux on $OS. Install manually."
            return
            ;;
    esac
    success "tmux installed: $(tmux -V)"
}

# ── Install git ───────────────────────────────────────────────────────

install_git() {
    if has git; then
        success "git found: $(git --version)"
        return
    fi

    info "Installing git..."
    case "$OS" in
        macos)
            brew install git
            ;;
        debian)
            sudo apt-get install -y -qq git
            ;;
        fedora)
            sudo dnf install -y git
            ;;
        arch)
            sudo pacman -S --noconfirm git
            ;;
        alpine)
            sudo apk add git
            ;;
        *)
            error "Cannot auto-install git. Install manually."
            ;;
    esac
    success "git installed"
}

# ── Install the CLI ──────────────────────────────────────────────────

install_cli() {
    REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

    info "Installing alpaca-cli from $REPO_DIR..."
    pip3 install -e "$REPO_DIR" --quiet 2>/dev/null || pip install -e "$REPO_DIR" --quiet

    if has alpaca; then
        success "alpaca CLI installed: $(alpaca --version)"
    else
        warn "alpaca command not on PATH. You may need to add pip's bin directory to PATH."
        warn "  Try: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
}

# ── Main ──────────────────────────────────────────────────────────────

main() {
    echo ""
    echo "========================================"
    echo "  Alpaca Paper Trading CLI — Setup"
    echo "========================================"
    echo ""

    detect_os

    # macOS needs Homebrew first
    if [ "$OS" = "macos" ]; then
        ensure_brew
    fi

    echo ""
    info "Checking and installing dependencies..."
    echo ""

    install_python
    install_pip
    install_tmux
    install_git

    echo ""
    install_cli

    echo ""
    echo "========================================"
    echo "  Setup Complete!"
    echo "========================================"
    echo ""
    echo "  Next steps:"
    echo "    1. alpaca configure init          # Set API keys"
    echo "    2. alpaca account summary          # Check balance"
    echo "    3. bash scripts/tmux-trading.sh    # Launch trading workspace"
    echo ""
}

main "$@"

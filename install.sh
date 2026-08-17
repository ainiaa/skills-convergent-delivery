#!/usr/bin/env bash
# Install convergent-delivery as a native Codex and/or Claude Code skill.
set -euo pipefail

GITHUB_OWNER="ainiaa"
GITHUB_REPO="skills-convergent-delivery"
GITHUB_BRANCH="main"
GITHUB_RAW_VERSION_URL="https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPO}/${GITHUB_BRANCH}/VERSION"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
MANAGED_SOURCE="${HOME}/.convergent-delivery/source"
INSTALL_LOCK_DIR="${HOME}/.convergent-delivery/.install.lock"
CODEX_TARGET="${HOME}/.codex/skills/convergent-delivery"
CLAUDE_TARGET="${HOME}/.claude/skills/convergent-delivery"

ACTION="install"
TARGET="all"
SOURCE_OVERRIDE=""
OFFLINE=0
FORCE=0
INSTALL_LOCK_HELD=0

usage() {
  cat <<EOF
convergent-delivery installer

Usage:
  bash install.sh [--target codex|claude|all] [--source /path/to/clone]
  bash install.sh --upgrade [--target codex|claude|all]
  bash install.sh --uninstall [--target codex|claude|all]
  bash install.sh --version [--offline]

The default target is all (Codex and Claude Code). Installation creates only
the runtime's convergent-delivery symlink; it never replaces an existing
directory unless --force is supplied.

Remote install:
  curl -fsSL https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPO}/${GITHUB_BRANCH}/install.sh | bash -s -- --target all
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --source) SOURCE_OVERRIDE="${2:-}"; shift 2 ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --upgrade) ACTION="upgrade"; shift ;;
    --version) ACTION="version"; shift ;;
    --offline) OFFLINE=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Error: unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$TARGET" in
  codex|claude|all) ;;
  *) echo "Error: --target must be codex, claude, or all." >&2; exit 1 ;;
esac

target_path() {
  case "$1" in
    codex) printf '%s\n' "$CODEX_TARGET" ;;
    claude) printf '%s\n' "$CLAUDE_TARGET" ;;
  esac
}

version_at() {
  local path="$1"
  if [[ -f "$path/VERSION" ]]; then
    head -1 "$path/VERSION"
  else
    echo "not installed"
  fi
}

latest_version() {
  if [[ "$OFFLINE" -eq 1 ]] || ! command -v curl >/dev/null 2>&1; then
    echo "not checked"
    return
  fi
  curl -fsSL --max-time 5 "$GITHUB_RAW_VERSION_URL" 2>/dev/null | head -1 || echo "unable to fetch"
}

do_version() {
  local local_version="not a local checkout"
  if [[ -f "$SCRIPT_DIR/VERSION" ]]; then
    local_version="$(head -1 "$SCRIPT_DIR/VERSION")"
  fi

  echo "convergent-delivery version status"
  echo "──────────────────────────────────────"
  echo "  Local source: ${local_version}"
  echo "  Codex:       $(version_at "$CODEX_TARGET")"
  echo "  Claude Code: $(version_at "$CLAUDE_TARGET")"
  echo "  GitHub main: $(latest_version)"
}

release_install_lock() {
  if [[ "$INSTALL_LOCK_HELD" -eq 1 ]]; then
    rm -f "$INSTALL_LOCK_DIR/pid"
    rmdir "$INSTALL_LOCK_DIR" 2>/dev/null || true
  fi
}

acquire_install_lock() {
  mkdir -p "$(dirname "$INSTALL_LOCK_DIR")"
  if ! mkdir "$INSTALL_LOCK_DIR" 2>/dev/null; then
    echo "Error: another installation is in progress: $INSTALL_LOCK_DIR" >&2
    exit 1
  fi
  printf '%s\n' "$$" > "$INSTALL_LOCK_DIR/pid"
  INSTALL_LOCK_HELD=1
  trap release_install_lock EXIT INT TERM
}

prepare_source() {
  if [[ -n "$SOURCE_OVERRIDE" ]]; then
    SOURCE_DIR="$SOURCE_OVERRIDE"
  elif [[ -f "$SCRIPT_DIR/SKILL.md" && -f "$SCRIPT_DIR/VERSION" ]]; then
    SOURCE_DIR="$SCRIPT_DIR"
  else
    if ! command -v git >/dev/null 2>&1; then
      echo "Error: git is required for a remote installation." >&2
      exit 1
    fi
    if [[ -d "$MANAGED_SOURCE/.git" ]]; then
      git -C "$MANAGED_SOURCE" pull --ff-only
    elif [[ -e "$MANAGED_SOURCE" ]]; then
      echo "Error: managed source exists but is not a Git checkout: $MANAGED_SOURCE" >&2
      exit 1
    else
      mkdir -p "$(dirname "$MANAGED_SOURCE")"
      git clone --depth 1 --branch "$GITHUB_BRANCH" \
        "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git" "$MANAGED_SOURCE"
    fi
    SOURCE_DIR="$MANAGED_SOURCE"
  fi

  if [[ ! -f "$SOURCE_DIR/SKILL.md" || ! -f "$SOURCE_DIR/VERSION" ]]; then
    echo "Error: source must contain SKILL.md and VERSION: $SOURCE_DIR" >&2
    exit 1
  fi
  SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd -P)"
}

same_source() {
  [[ -L "$1" ]] && [[ "$(cd "$1" 2>/dev/null && pwd -P)" == "$SOURCE_DIR" ]]
}

ensure_installable() {
  local target="$1"
  if same_source "$target"; then
    return
  fi
  if [[ -L "$target" ]]; then
    if [[ "$FORCE" -eq 1 ]]; then
      return
    fi
    echo "Error: refusing to replace existing symlink: $target (use --force)." >&2
    exit 1
  fi
  if [[ -e "$target" ]]; then
    echo "Error: refusing to replace existing directory or file: $target" >&2
    exit 1
  fi
}

install_target() {
  local runtime="$1"
  local target
  target="$(target_path "$runtime")"
  if same_source "$target"; then
    echo "${runtime}: already installed → $SOURCE_DIR"
    return
  fi
  mkdir -p "$(dirname "$target")"
  if [[ -L "$target" ]]; then
    rm "$target"
  fi
  ln -s "$SOURCE_DIR" "$target"
  echo "${runtime}: installed → $target"
}

is_skill_link() {
  local target="$1"
  [[ -L "$target" ]] && [[ -f "$target/SKILL.md" ]] \
    && grep -q '^name: convergent-delivery$' "$target/SKILL.md"
}

uninstall_target() {
  local runtime="$1"
  local target
  target="$(target_path "$runtime")"
  if is_skill_link "$target" || { [[ "$FORCE" -eq 1 ]] && [[ -L "$target" ]]; }; then
    rm "$target"
    echo "${runtime}: removed $target"
  elif [[ -e "$target" || -L "$target" ]]; then
    echo "Error: refusing to remove unrecognized path: $target (use --force for a symlink)." >&2
    exit 1
  else
    echo "${runtime}: not installed"
  fi
}

if [[ "$ACTION" == "version" ]]; then
  do_version
  exit 0
fi

acquire_install_lock

if [[ "$ACTION" == "install" || "$ACTION" == "upgrade" ]]; then
  prepare_source
  if [[ "$TARGET" == "all" ]]; then
    ensure_installable "$CODEX_TARGET"
    ensure_installable "$CLAUDE_TARGET"
    install_target codex
    install_target claude
  else
    ensure_installable "$(target_path "$TARGET")"
    install_target "$TARGET"
  fi
  echo "✅ convergent-delivery $(head -1 "$SOURCE_DIR/VERSION") is ready. Restart the runtime if it is already open."
elif [[ "$ACTION" == "uninstall" ]]; then
  if [[ "$TARGET" == "all" ]]; then
    uninstall_target codex
    uninstall_target claude
  else
    uninstall_target "$TARGET"
  fi
  echo "✅ Uninstall completed. The managed source is retained at ${MANAGED_SOURCE}."
fi

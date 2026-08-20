#!/usr/bin/env bash
# Install converge as a native Codex and/or Claude Code skill.
set -euo pipefail

GITHUB_OWNER="ainiaa"
GITHUB_REPO="skills-convergent-delivery"
GITHUB_BRANCH="main"
GITHUB_RAW_VERSION_URL="https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPO}/${GITHUB_BRANCH}/VERSION"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
MANAGED_SOURCE="${HOME}/.convergent-delivery/source"
INSTALL_LOCK_DIR="${HOME}/.convergent-delivery/.install.lock"
CODEX_SKILLS_ROOT="${HOME}/.codex/skills"
CLAUDE_SKILLS_ROOT="${HOME}/.claude/skills"
LEGACY_CODEX_TARGET="${HOME}/.codex/skills/convergent-delivery"
LEGACY_CLAUDE_TARGET="${HOME}/.claude/skills/convergent-delivery"
SKILL_NAMES=(converge converge-review converge-batch)
REQUIRED_SOURCE_FILES=(
  SKILL.md
  VERSION
  references/evaluation-scenarios.md
  references/execution-protocol.md
  references/reporting.md
  references/state-schema.md
  references/tdd-providers.md
  scripts/delivery_engine.py
  scripts/delivery_lease.py
  scripts/delivery_next.py
  scripts/delivery_state.py
  scripts/delivery_task_key.py
  skills/converge-review/SKILL.md
  skills/converge-review/references/review-contract.md
  skills/converge-batch/SKILL.md
  skills/converge-batch/references/batch-contract.md
  skills/converge-batch/scripts/batch_state.py
)

ACTION="install"
TARGET="all"
SOURCE_OVERRIDE=""
OFFLINE=0
FORCE=0
INSTALL_LOCK_HELD=0

usage() {
  cat <<EOF
converge installer

Usage:
  bash install.sh [--target codex|claude|all] [--source /path/to/clone]
  bash install.sh --upgrade [--target codex|claude|all]
  bash install.sh --uninstall [--target codex|claude|all]
  bash install.sh --version [--offline]

The default target is all (Codex and Claude Code). Installation creates the
converge, converge-review, and converge-batch symlinks as one Suite. It never
replaces an existing directory.

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
  local skill="${2:-converge}"
  case "$1" in
    codex) printf '%s/%s\n' "$CODEX_SKILLS_ROOT" "$skill" ;;
    claude) printf '%s/%s\n' "$CLAUDE_SKILLS_ROOT" "$skill" ;;
  esac
}

skill_source() {
  case "$1" in
    converge) printf '%s\n' "$SOURCE_DIR" ;;
    converge-review|converge-batch) printf '%s/skills/%s\n' "$SOURCE_DIR" "$1" ;;
  esac
}

legacy_target_path() {
  case "$1" in
    codex) printf '%s\n' "$LEGACY_CODEX_TARGET" ;;
    claude) printf '%s\n' "$LEGACY_CLAUDE_TARGET" ;;
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

  echo "converge version status"
  echo "──────────────────────────────────────"
  echo "  Local source: ${local_version}"
  echo "  Codex:       $(version_at "$(target_path codex converge)")"
  echo "  Claude Code: $(version_at "$(target_path claude converge)")"
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

  local relative
  for relative in "${REQUIRED_SOURCE_FILES[@]}"; do
    if [[ ! -f "$SOURCE_DIR/$relative" ]]; then
      echo "Error: mandatory Suite file is missing: $SOURCE_DIR/$relative" >&2
      exit 1
    fi
  done
  SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd -P)"
}

same_source() {
  [[ -L "$1" ]] && [[ "$(cd "$1" 2>/dev/null && pwd -P)" == "$2" ]]
}

migrate_legacy_target() {
  local runtime="$1"
  local legacy
  legacy="$(legacy_target_path "$runtime")"
  if same_source "$legacy" "$SOURCE_DIR"; then
    rm "$legacy"
    echo "${runtime}: migrated legacy link → $(target_path "$runtime")"
  elif [[ -d "$legacy" ]] && [[ -f "$legacy/SKILL.md" ]] \
    && grep -Eq '^name: (converge|convergent-delivery)$' "$legacy/SKILL.md"; then
    local backup_root="${HOME}/.convergent-delivery/legacy-backups"
    local backup_dir
    mkdir -p "$backup_root"
    backup_dir="$(mktemp -d "$backup_root/${runtime}-convergent-delivery.XXXXXX")"
    mv "$legacy" "$backup_dir/convergent-delivery"
    echo "${runtime}: backed up legacy directory → $backup_dir/convergent-delivery"
  fi
}

ensure_installable() {
  local target="$1"
  local source="$2"
  if same_source "$target" "$source"; then
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

install_skill() {
  local runtime="$1"
  local skill="$2"
  local target
  local source
  target="$(target_path "$runtime" "$skill")"
  source="$(skill_source "$skill")"
  if same_source "$target" "$source"; then
    echo "${runtime}: ${skill} already installed → $source"
    return
  fi
  mkdir -p "$(dirname "$target")"
  local temporary="${target}.tmp.$$"
  rm -f "$temporary"
  ln -s "$source" "$temporary"
  mv -f "$temporary" "$target"
  echo "${runtime}: installed ${skill} → $target"
}

is_skill_link() {
  local target="$1"
  local skill="$2"
  [[ -L "$target" ]] && [[ -f "$target/SKILL.md" ]] \
    && grep -Eq "^name: (${skill}|convergent-delivery)$" "$target/SKILL.md"
}

ensure_uninstallable() {
  local runtime="$1"
  local skill="$2"
  local target
  target="$(target_path "$runtime" "$skill")"
  if is_skill_link "$target" "$skill" || { [[ "$FORCE" -eq 1 ]] && [[ -L "$target" ]]; }; then
    return
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    echo "Error: refusing to remove unrecognized path: $target (use --force for a symlink)." >&2
    exit 1
  fi
}

uninstall_skill() {
  local runtime="$1"
  local skill="$2"
  local target
  target="$(target_path "$runtime" "$skill")"
  if [[ -L "$target" ]]; then
    rm "$target"
    echo "${runtime}: removed $target"
  else
    echo "${runtime}: ${skill} not installed"
  fi
}

if [[ "$ACTION" == "version" ]]; then
  do_version
  exit 0
fi

acquire_install_lock

if [[ "$ACTION" == "install" || "$ACTION" == "upgrade" ]]; then
  prepare_source
  RUNTIMES=("$TARGET")
  [[ "$TARGET" == "all" ]] && RUNTIMES=(codex claude)
  for runtime in "${RUNTIMES[@]}"; do
    for skill in "${SKILL_NAMES[@]}"; do
      ensure_installable "$(target_path "$runtime" "$skill")" "$(skill_source "$skill")"
    done
  done
  for runtime in "${RUNTIMES[@]}"; do
    migrate_legacy_target "$runtime"
  done
  for runtime in "${RUNTIMES[@]}"; do
    for skill in "${SKILL_NAMES[@]}"; do
      install_skill "$runtime" "$skill"
    done
  done
  echo "✅ converge $(head -1 "$SOURCE_DIR/VERSION") is ready. Restart the runtime if it is already open."
elif [[ "$ACTION" == "uninstall" ]]; then
  RUNTIMES=("$TARGET")
  [[ "$TARGET" == "all" ]] && RUNTIMES=(codex claude)
  for runtime in "${RUNTIMES[@]}"; do
    for skill in "${SKILL_NAMES[@]}"; do
      ensure_uninstallable "$runtime" "$skill"
    done
  done
  for runtime in "${RUNTIMES[@]}"; do
    for skill in "${SKILL_NAMES[@]}"; do
      uninstall_skill "$runtime" "$skill"
    done
  done
  echo "✅ Uninstall completed. The managed source is retained at ${MANAGED_SOURCE}."
fi

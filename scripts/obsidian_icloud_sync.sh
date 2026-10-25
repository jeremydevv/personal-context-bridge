#!/usr/bin/env bash
# Run on the Linux archive host. The configured remote may be the Mac's authenticated
# iCloud File Provider or a directly authenticated iCloud Drive backend.
# Ubuntu remains the canonical MCP file store.
set -euo pipefail

mode="${1:-}"
if [[ "$mode" != --initialize && "$mode" != --run && "$mode" != --dry-run ]]; then
  echo 'usage: obsidian_icloud_sync.sh --initialize|--run|--dry-run' >&2
  exit 64
fi

vault_root="${OBSIDIAN_VAULT_ROOT:-$HOME/.local/share/obsidian-vaults-live}"
remote_base="${OBSIDIAN_ICLOUD_BASE:-}"
remote_backup_base="${OBSIDIAN_REMOTE_BACKUP_BASE:-}"
rclone_bin="${RCLONE_BIN:-$HOME/.local/bin/rclone}"
if [[ -z "$remote_base" || "$remote_base" != *:* ||
      -z "$remote_backup_base" || "$remote_backup_base" != *:* ||
      ! -x "$rclone_bin" ]]; then
  echo 'OBSIDIAN_ICLOUD_BASE and OBSIDIAN_REMOTE_BACKUP_BASE must be rclone remote paths' >&2
  exit 64
fi
if ! mountpoint -q "$vault_root"; then
  echo 'Encrypted vault mount is unavailable; sync refused' >&2
  exit 75
fi

if [[ -z "${OBSIDIAN_VAULTS:-}" ]]; then
  echo 'OBSIDIAN_VAULTS must explicitly allowlist vault names' >&2
  exit 64
fi
IFS=',' read -r -a vaults <<< "$OBSIDIAN_VAULTS"
for vault in "${vaults[@]}"; do
  if [[ -z "$vault" || "$vault" == . || "$vault" == .. || "$vault" == */* || "$vault" == *\\* ]]; then
    echo 'Invalid vault allowlist' >&2
    exit 64
  fi
done

remote_base="${remote_base%/}"
remote_backup_base="${remote_backup_base%/}"
state_dir="${OBSIDIAN_BISYNC_STATE_DIR:-$vault_root/.mcp-backups/bisync-state}"
local_backups="${OBSIDIAN_LOCAL_BACKUP_DIR:-$vault_root/.mcp-backups/bisync-overwrites}"
mkdir -p "$state_dir" "$local_backups"
chmod 700 "$state_dir" "$local_backups"

# The Obsidian MCP write tools use the same lock. Never reconcile a vault
# while an MCP edit is in progress.
exec 9>"$vault_root/.mcp-write.lock"
if ! flock -x -w 30 9; then
  echo 'Timed out waiting for vault write lock' >&2
  exit 75
fi

for vault in "${vaults[@]}"; do
  local_path="$vault_root/$vault"
  remote_path="$remote_base/$vault"
  if [[ -L "$local_path" || ! -d "$local_path" || ! -f "$local_path/.obsidian/app.json" ]]; then
    echo "Local vault $vault is incomplete; sync refused" >&2
    exit 75
  fi
  if ! "$rclone_bin" lsf "$remote_path/.obsidian/app.json" --files-only --format p --retries 1 \
       | grep -Fxq 'app.json'; then
    echo "iCloud vault $vault is unavailable; sync refused" >&2
    exit 75
  fi
  if [[ "$mode" == --initialize ]]; then
    if [[ ! -f "$local_path/.RCLONE_TEST" ]]; then
      printf 'Obsidian vault sync access check\n' > "$local_path/.RCLONE_TEST"
      chmod 600 "$local_path/.RCLONE_TEST"
    fi
    "$rclone_bin" copyto "$local_path/.RCLONE_TEST" "$remote_path/.RCLONE_TEST" --retries 1
  fi
  if [[ ! -f "$local_path/.RCLONE_TEST" ]] || \
     ! "$rclone_bin" lsf "$remote_path/.RCLONE_TEST" --files-only --format p --retries 1 \
       | grep -Fxq '.RCLONE_TEST'; then
    echo "Sync access marker missing for $vault; sync refused" >&2
    exit 75
  fi
done

for vault in "${vaults[@]}"; do
  local_path="$vault_root/$vault"
  remote_path="$remote_base/$vault"
  common=(
    --workdir "$state_dir"
    --check-access --check-filename '.RCLONE_TEST'
    --conflict-resolve path1 --conflict-loser num
    --backup-dir1 "$local_backups/$vault"
    --backup-dir2 "$remote_backup_base/$vault"
    --max-delete 20
    --modify-window 1s
    --resilient --recover
    # A killed run must not leave a permanent lock. The shared flock above
    # still excludes every live reconciliation and MCP edit.
    --max-lock 30m
    --retries 1
  )
  case "$mode" in
    --initialize)
      # Require byte-for-byte equality before establishing the first baseline.
      # Run both directions so files present on only one side are caught.
      "$rclone_bin" check "$local_path" "$remote_path" --download --one-way --retries 1
      "$rclone_bin" check "$remote_path" "$local_path" --download --one-way --retries 1
      "$rclone_bin" bisync "$local_path" "$remote_path" "${common[@]}" \
        --resync --resync-mode path1
      ;;
    --run)
      "$rclone_bin" bisync "$local_path" "$remote_path" "${common[@]}"
      ;;
    --dry-run)
      "$rclone_bin" bisync "$local_path" "$remote_path" "${common[@]}" --dry-run
      ;;
  esac
done

if [[ "$mode" != --dry-run ]]; then
  status_file="$vault_root/.mcp-backups/sync_status.json"
  status_temp="$(mktemp "$vault_root/.mcp-backups/sync_status.XXXXXX")"
  printf '{"last_success_at":"%s","mode":"%s"}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$mode" > "$status_temp"
  chmod 600 "$status_temp"
  mv "$status_temp" "$status_file"
  # Emit only this invocation's correlated result, while the vault lock is held.
  # This is local reconciliation completion, not a core archive SQL receipt.
  if [[ -n "${PERSONAL_CONTEXT_REFRESH_ID:-}" &&
        -n "${PERSONAL_CONTEXT_REFRESH_ATTEMPT:-}" &&
        "${PERSONAL_CONTEXT_REFRESH_SOURCE:-}" == obsidian ]]; then
    python3 - <<'PYRECEIPT'
import json, os
print(json.dumps({
    "refresh_id": os.environ["PERSONAL_CONTEXT_REFRESH_ID"],
    "attempt_id": os.environ["PERSONAL_CONTEXT_REFRESH_ATTEMPT"],
    "source": "obsidian", "collection_finished": True, "coverage": "complete",
    "batch_ids": [], "acked_batch_ids": []
}), flush=True)
PYRECEIPT
  fi
fi

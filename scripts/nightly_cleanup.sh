#!/bin/zsh

set -euo pipefail

HOME_DIR="${HOME}"
DESKTOP_DIR="${HOME_DIR}/Desktop"
DOWNLOADS_DIR="${HOME_DIR}/Downloads"
TRASH_DIR="${HOME_DIR}/.Trash"
LOG_FILE="${HOME_DIR}/Library/Logs/nightly_cleanup.log"

mkdir -p "$(dirname "${LOG_FILE}")"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log() {
  printf '[%s] %s\n' "$(timestamp)" "$1" >> "${LOG_FILE}"
}

delete_desktop_screenshots() {
  if [[ ! -d "${DESKTOP_DIR}" ]]; then
    log "Desktop folder not found; skipping screenshot cleanup."
    return
  fi

  find "${DESKTOP_DIR}" -maxdepth 1 -type f \
    \( -name 'Screenshot *.png' -o -name 'Screenshot *.jpg' -o -name 'Screenshot *.jpeg' \
    -o -name 'Screen Shot *.png' -o -name 'Screen Shot *.jpg' -o -name 'Screen Shot *.jpeg' \) \
    -print -delete >> "${LOG_FILE}" 2>&1 || true
}

delete_downloads_contents() {
  if [[ ! -d "${DOWNLOADS_DIR}" ]]; then
    log "Downloads folder not found; skipping downloads cleanup."
    return
  fi

  find "${DOWNLOADS_DIR}" -mindepth 1 -maxdepth 1 -print -exec rm -rf {} + >> "${LOG_FILE}" 2>&1 || true
}

empty_trash() {
  if [[ ! -d "${TRASH_DIR}" ]]; then
    log "Trash folder not found; skipping trash cleanup."
    return
  fi

  find "${TRASH_DIR}" -mindepth 1 -maxdepth 1 -print -exec rm -rf {} + >> "${LOG_FILE}" 2>&1 || true
}

log "Nightly cleanup started."
delete_desktop_screenshots
delete_downloads_contents
empty_trash
log "Nightly cleanup completed."

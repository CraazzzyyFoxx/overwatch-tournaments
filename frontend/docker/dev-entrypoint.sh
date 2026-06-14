#!/bin/sh
set -eu

APP_DIR=/app
LOCKFILE="$APP_DIR/bun.lock"
CHECKSUM_FILE="$APP_DIR/node_modules/.bun-lock.cksum"

log() {
  printf '%s %s\n' "[frontend-dev]" "$*"
}

install_dependencies() {
  log "Installing dependencies with bun install"
  bun install --frozen-lockfile
  mkdir -p "$APP_DIR/node_modules"
  cksum "$LOCKFILE" > "$CHECKSUM_FILE"
}

cd "$APP_DIR"

if [ -f "$LOCKFILE" ]; then
  current_checksum=$(cksum "$LOCKFILE")
  stored_checksum=""
  should_install=0

  if [ -f "$CHECKSUM_FILE" ]; then
    stored_checksum=$(cat "$CHECKSUM_FILE")
  fi

  if [ ! -d "$APP_DIR/node_modules" ]; then
    log "node_modules is missing"
    should_install=1
  elif [ ! -f "$CHECKSUM_FILE" ]; then
    log "Dependency checksum is missing"
    should_install=1
  elif [ "$current_checksum" != "$stored_checksum" ]; then
    log "bun.lock changed"
    should_install=1
  fi

  if [ "$should_install" -eq 1 ]; then
    install_dependencies
  else
    log "Dependencies are up to date"
  fi
else
  log "bun.lock not found; skipping dependency sync"
fi

if [ "$#" -eq 0 ]; then
  set -- bun run dev -- --hostname 0.0.0.0 --port 3000
fi

exec "$@"

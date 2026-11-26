# Resolve the login file before any private server or backup opens runtime data.
if [ -z "${LEGAL_KB_PRIVATE_ENV_PATH:-}" ]; then
  if [ -f "$PROJECT_DIR/.env.private-location" ]; then
    LEGAL_KB_PRIVATE_ENV_PATH="$(cat "$PROJECT_DIR/.env.private-location")" || return 1
    case "$LEGAL_KB_PRIVATE_ENV_PATH" in
      /*) ;;
      *) printf 'Private configuration locator must store an absolute path\n' >&2; return 1 ;;
    esac
  else
    LEGAL_KB_PRIVATE_ENV_PATH="$PROJECT_DIR/.env.private"
  fi
fi
export LEGAL_KB_PRIVATE_ENV_PATH

if [ -f "$LEGAL_KB_PRIVATE_ENV_PATH" ]; then
  set -a
  . "$LEGAL_KB_PRIVATE_ENV_PATH" || return 1
  set +a
elif [ "$LEGAL_KB_PRIVATE_ENV_PATH" != "$PROJECT_DIR/.env.private" ]; then
  printf 'Configured private environment file is missing\n' >&2
  return 1
fi

if [ "$LEGAL_KB_PRIVATE_ENV_PATH" != "$PROJECT_DIR/.env.private" ] && [ -z "${LEGAL_KB_RUNTIME_DIR:-}" ]; then
  printf 'External private configuration requires a separate runtime directory\n' >&2
  return 1
fi

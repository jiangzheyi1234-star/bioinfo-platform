from __future__ import annotations

from core.remote_runner.layout import (
    REMOTE_RUNNER_RUNTIME_STATE_SHELL_PATH,
    REMOTE_RUNNER_STOP_SCRIPT_SHELL_PATH,
    REMOTE_STOP_PROCESS_OUTPUT,
    REMOTE_STOP_SCRIPT_OUTPUT,
    REMOTE_STOP_SYSTEMD_OUTPUT,
)


STOP_REMOTE_RUNNER_COMMAND = rf"""
set -u
RUNNER_MODE="${{H2OMETA_RUNNER_MODE:-}}"
STATE_PATH="{REMOTE_RUNNER_RUNTIME_STATE_SHELL_PATH}"
STOP_SCRIPT="{REMOTE_RUNNER_STOP_SCRIPT_SHELL_PATH}"
FAILED=0
SYSTEMD_STOPPED=0
STOP_SCRIPT_RAN=0
PROCESS_CHECKED=0

if [ "$RUNNER_MODE" = "background_process" ]; then
  printf 'systemd_user=skipped\n'
elif command -v systemctl >/dev/null 2>&1; then
  if systemctl --user stop h2ometa-remote.service >{REMOTE_STOP_SYSTEMD_OUTPUT} 2>&1; then
    SYSTEMD_STOPPED=1
    printf 'systemd_user=stopped\n'
  else
    if [ "$RUNNER_MODE" = "systemd_user" ]; then
      FAILED=1
      printf 'systemd_user=failed: '
    else
      printf 'systemd_user=not-stopped: '
    fi
    cat {REMOTE_STOP_SYSTEMD_OUTPUT}
    printf '\n'
  fi
else
  if [ "$RUNNER_MODE" = "systemd_user" ]; then
    FAILED=1
  fi
  printf 'systemd_user=unavailable\n'
fi

if [ -f "$STOP_SCRIPT" ]; then
  if bash "$STOP_SCRIPT" >{REMOTE_STOP_SCRIPT_OUTPUT} 2>&1; then
    STOP_SCRIPT_RAN=1
    printf 'stop_script=stopped\n'
  else
    FAILED=1
    printf 'stop_script=failed: '
    cat {REMOTE_STOP_SCRIPT_OUTPUT}
    printf '\n'
  fi
else
  printf 'stop_script=missing\n'
fi

if command -v pkill >/dev/null 2>&1; then
  PROCESS_CHECKED=1
  pkill -f '[r]emote_runner.run' >{REMOTE_STOP_PROCESS_OUTPUT} 2>&1
  PKILL_CODE=$?
  if [ "$PKILL_CODE" -eq 0 ]; then
    printf 'process=stopped\n'
  elif [ "$PKILL_CODE" -eq 1 ]; then
    printf 'process=not-running\n'
  else
    FAILED=1
    printf 'process=failed: '
    cat {REMOTE_STOP_PROCESS_OUTPUT}
    printf '\n'
  fi
else
  printf 'process=pkill-unavailable\n'
fi

if [ "$SYSTEMD_STOPPED" -eq 0 ] && [ "$STOP_SCRIPT_RAN" -eq 0 ] && [ "$PROCESS_CHECKED" -eq 0 ]; then
  FAILED=1
  printf 'stop_mechanism=unavailable\n'
fi

rm -f "$STATE_PATH"
exit "$FAILED"
"""

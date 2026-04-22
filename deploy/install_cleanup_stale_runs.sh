#!/usr/bin/env bash
# AURUM · installer pro timer de cleanup de stale running rows no live_runs DB.
#
# Uso: bash deploy/install_cleanup_stale_runs.sh [/srv/aurum.finance]
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SVC_SRC="${REPO_PATH}/deploy/aurum_cleanup_stale_runs.service"
TIMER_SRC="${REPO_PATH}/deploy/aurum_cleanup_stale_runs.timer"
SVC_DST="/etc/systemd/system/aurum_cleanup_stale_runs.service"
TIMER_DST="/etc/systemd/system/aurum_cleanup_stale_runs.timer"

echo "=== install aurum_cleanup_stale_runs timer ==="

if [ ! -f "${SVC_SRC}" ] || [ ! -f "${TIMER_SRC}" ]; then
  echo "ERRO: templates nao encontrados em ${REPO_PATH}/deploy/"; exit 1
fi

echo "[1/4] copiando unit + timer pra /etc/systemd/system"
sudo cp "${SVC_SRC}" "${SVC_DST}"
sudo cp "${TIMER_SRC}" "${TIMER_DST}"
echo "  OK"

echo "[2/4] daemon-reload"
sudo systemctl daemon-reload

echo "[3/4] enable + start timer"
sudo systemctl enable --now aurum_cleanup_stale_runs.timer

echo "[4/4] status"
sudo systemctl list-timers aurum_cleanup_stale_runs.timer --no-pager
echo
echo "=== timer ativo ==="
echo "  Logs:     journalctl -u aurum_cleanup_stale_runs.service -f"
echo "  Manual:   sudo systemctl start aurum_cleanup_stale_runs.service"
echo "  Timer:    sudo systemctl list-timers aurum_cleanup_stale_runs.timer"
echo "  Desativar:sudo systemctl disable --now aurum_cleanup_stale_runs.timer"

#!/usr/bin/env bash
# AURUM · installer do PROBE (diagnostic scanner)
# Uso (no VPS, como root ou com sudo):
#   bash deploy/install_probe_vps.sh [/srv/aurum.finance] [aurum] [desk-a]
# Argumentos: <repo_path> <service_user> <label>. Defaults abaixo.
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SERVICE_USER="${2:-aurum}"
LABEL="${3:-desk-a}"
UNIT_SRC="${REPO_PATH}/deploy/aurum_probe@.service"
UNIT_DST="/etc/systemd/system/aurum_probe@.service"
SVC_INSTANCE="aurum_probe@${LABEL}.service"

echo "=== AURUM probe installer ==="
echo "  repo:     ${REPO_PATH}"
echo "  user:     ${SERVICE_USER}"
echo "  label:    ${LABEL}"
echo "  instance: ${SVC_INSTANCE}"
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: repo_path ${REPO_PATH} nao existe."
  exit 1
fi
if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit nao encontrada em ${UNIT_SRC}. Atualize o repo:"
  echo "  cd ${REPO_PATH} && git pull"
  exit 1
fi

echo "[1/5] smoke: python3 tools/maintenance/probe_runner.py --help"
(cd "${REPO_PATH}" && python3 tools/maintenance/probe_runner.py --help >/dev/null)
echo "  OK"

echo "[2/5] instalando unit template em ${UNIT_DST}"
sed \
  -e "s|^User=.*|User=${SERVICE_USER}|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" \
  -e "s|^ReadWritePaths=.*|ReadWritePaths=${REPO_PATH}/data|" \
  "${UNIT_SRC}" | sudo tee "${UNIT_DST}" >/dev/null
echo "  OK"

echo "[3/5] systemctl daemon-reload"
sudo systemctl daemon-reload

echo "[4/5] systemctl enable + start ${SVC_INSTANCE}"
sudo systemctl enable "${SVC_INSTANCE}"
sudo systemctl start "${SVC_INSTANCE}"

sleep 5
echo "[5/5] status inicial:"
sudo systemctl status "${SVC_INSTANCE}" --no-pager -l | head -20

echo
echo "=== tudo pronto ==="
echo "  Follow logs:   sudo journalctl -u ${SVC_INSTANCE} -f"
echo "  Probe log:     tail -f ${REPO_PATH}/data/probe_shadow/<RUN_ID>/logs/shadow.log"
echo "  Heartbeat:     cat ${REPO_PATH}/data/probe_shadow/<RUN_ID>/state/heartbeat.json"
echo "  Probe ticks:   tail -f ${REPO_PATH}/data/probe_shadow/<RUN_ID>/reports/probe_tick.jsonl"
echo "  Stop:          sudo systemctl stop ${SVC_INSTANCE}"

#!/usr/bin/env bash
# AURUM · installer pro paper runner do MILLENNIUM
# Uso (no VPS, root/sudo):
#   bash deploy/install_paper_vps.sh [/srv/aurum.finance] [aurum] [10000]
# Argumentos opcionais: <repo_path> <service_user> <account_size>.
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SERVICE_USER="${2:-$(whoami)}"
ACCOUNT_SIZE="${3:-10000}"
UNIT_SRC="${REPO_PATH}/deploy/millennium_paper.service"
UNIT_DST="/etc/systemd/system/millennium_paper.service"
ENV_FILE="/etc/aurum/paper.env"

echo "=== AURUM paper installer ==="
echo "  repo:    ${REPO_PATH}"
echo "  user:    ${SERVICE_USER}"
echo "  account: \$${ACCOUNT_SIZE}"
echo "  unit:    ${UNIT_DST}"
echo "  env:     ${ENV_FILE}"
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: ${REPO_PATH} nao existe"; exit 1
fi
if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit nao encontrada em ${UNIT_SRC}"; exit 1
fi

echo "[1/6] smoke: python tools/operations/millennium_paper.py --help"
(cd "${REPO_PATH}" && python3 tools/operations/millennium_paper.py --help >/dev/null)
echo "  OK"

echo "[2/6] criando ${ENV_FILE} (se nao existir)"
sudo mkdir -p /etc/aurum
if [ ! -f "${ENV_FILE}" ]; then
  echo "AURUM_PAPER_ACCOUNT_SIZE=${ACCOUNT_SIZE}" | sudo tee "${ENV_FILE}" >/dev/null
  echo "  criado"
else
  echo "  ja existe (preservado)"
fi

echo "[3/6] instalando unit em ${UNIT_DST}"
sed \
  -e "s|^User=.*|User=${SERVICE_USER}|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" \
  -e "s|^ReadWritePaths=.*|ReadWritePaths=${REPO_PATH}/data|" \
  "${UNIT_SRC}" | sudo tee "${UNIT_DST}" >/dev/null
echo "  OK"

echo "[4/6] systemctl daemon-reload"
sudo systemctl daemon-reload

echo "[5/6] enable + start"
sudo systemctl enable millennium_paper.service
sudo systemctl start millennium_paper.service

sleep 10
echo "[6/6] status:"
sudo systemctl status millennium_paper.service --no-pager -l | head -20

echo
echo "=== paper runner ativo ==="
echo "  Logs:        sudo journalctl -u millennium_paper.service -f"
echo "  Heartbeat:   cat ${REPO_PATH}/data/millennium_paper/<RUN>/state/heartbeat.json"
echo "  Account:     cat ${REPO_PATH}/data/millennium_paper/<RUN>/state/account.json"
echo "  Stop:        sudo systemctl stop millennium_paper.service"
echo "  Kill flag:   touch ${REPO_PATH}/data/millennium_paper/<RUN>/.kill"

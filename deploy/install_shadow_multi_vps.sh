#!/usr/bin/env bash
# AURUM · installer pro template multi-instance shadow runner do MILLENNIUM
# Uso:
#   bash deploy/install_shadow_multi_vps.sh [/srv/aurum.finance] [aurum] [slot]
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SERVICE_USER="${2:-$(whoami)}"
SLOT="${3:-desk-shadow-b}"
UNIT_SRC="${REPO_PATH}/deploy/millennium_shadow@.service"
UNIT_DST="/etc/systemd/system/millennium_shadow@.service"
ENV_FILE="/etc/aurum/shadow-${SLOT}.env"

echo "=== AURUM shadow multi-instance installer ==="
echo "  repo:    ${REPO_PATH}"
echo "  user:    ${SERVICE_USER}"
echo "  slot:    ${SLOT}"
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: ${REPO_PATH} nao existe"; exit 1
fi
if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit template nao encontrada em ${UNIT_SRC}"; exit 1
fi

echo "[1/6] smoke: python tools/maintenance/millennium_shadow.py --help"
(cd "${REPO_PATH}" && python3 tools/maintenance/millennium_shadow.py --help >/dev/null)
echo "  OK"

echo "[2/6] criando ${ENV_FILE}"
sudo mkdir -p /etc/aurum
cat <<EOF | sudo tee "${ENV_FILE}" >/dev/null
AURUM_SHADOW_LABEL=${SLOT}
EOF
echo "  OK"

echo "[3/6] instalando template unit em ${UNIT_DST}"
sed \
  -e "s|^User=.*|User=${SERVICE_USER}|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" \
  -e "s|^ReadWritePaths=.*|ReadWritePaths=${REPO_PATH}/data|" \
  "${UNIT_SRC}" | sudo tee "${UNIT_DST}" >/dev/null
echo "  OK"

echo "[4/6] systemctl daemon-reload"
sudo systemctl daemon-reload

echo "[5/6] enable + start millennium_shadow@${SLOT}.service"
sudo systemctl enable "millennium_shadow@${SLOT}.service"
sudo systemctl start "millennium_shadow@${SLOT}.service"

sleep 10
echo "[6/6] status:"
sudo systemctl status "millennium_shadow@${SLOT}.service" --no-pager -l | head -20

echo
echo "=== shadow template instance ativa ==="
echo "  Logs:      sudo journalctl -u millennium_shadow@${SLOT}.service -f"
echo "  Env file:  ${ENV_FILE}"
echo "  Stop:      sudo systemctl stop millennium_shadow@${SLOT}.service"

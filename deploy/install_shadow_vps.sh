#!/usr/bin/env bash
# AURUM · one-shot installer pro shadow runner do MILLENNIUM
# Uso (no VPS, como root ou com sudo):
#   bash deploy/install_shadow_vps.sh [/srv/aurum.finance] [aurum]
# Argumentos opcionais: <repo_path> <service_user>. Defaults abaixo.
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SERVICE_USER="${2:-$(whoami)}"
UNIT_SRC="${REPO_PATH}/deploy/millennium_shadow.service"
UNIT_DST="/etc/systemd/system/millennium_shadow.service"

echo "=== AURUM shadow installer ==="
echo "  repo:    ${REPO_PATH}"
echo "  user:    ${SERVICE_USER}"
echo "  unit:    ${UNIT_DST}"
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: repo_path ${REPO_PATH} nao existe. Clone o repo primeiro:"
  echo "  git clone https://github.com/JoaoCarretero/aurum.git ${REPO_PATH}"
  exit 1
fi

if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit nao encontrada em ${UNIT_SRC}. Atualize o repo:"
  echo "  cd ${REPO_PATH} && git pull origin feat/phi-engine"
  exit 1
fi

# Smoke: Python consegue importar o runner?
echo "[1/6] smoke: python tools/maintenance/millennium_shadow.py --help"
(cd "${REPO_PATH}" && python3 tools/maintenance/millennium_shadow.py --help >/dev/null)
echo "  OK"

# Hardening: garantir perms restritivas em config/ + secrets se existirem.
# keys.json é gitignored (não está no repo), mas se foi copiado manualmente
# pro VPS, precisa estar 600 (owner-only). Idempotente: só age se file existe.
echo "[2/6] hardening perms de config/"
if [ -d "${REPO_PATH}/config" ]; then
  sudo chown -R "${SERVICE_USER}:${SERVICE_USER}" "${REPO_PATH}/config"
  sudo chmod 700 "${REPO_PATH}/config"
  for sensitive in keys.json keys.json.enc connections.json vps.json vpn.json; do
    if [ -f "${REPO_PATH}/config/${sensitive}" ]; then
      sudo chmod 600 "${REPO_PATH}/config/${sensitive}"
      echo "  chmod 600 config/${sensitive}"
    fi
  done
  echo "  OK"
else
  echo "  WARN: ${REPO_PATH}/config nao existe (skip)"
fi

# Instalar unit com User e WorkingDirectory ajustados.
echo "[3/6] instalando unit em ${UNIT_DST}"
sed \
  -e "s|^User=.*|User=${SERVICE_USER}|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" \
  -e "s|^ReadWritePaths=.*|ReadWritePaths=${REPO_PATH}/data|" \
  "${UNIT_SRC}" | sudo tee "${UNIT_DST}" >/dev/null
echo "  OK"

# Reload + enable + start.
echo "[4/6] systemctl daemon-reload"
sudo systemctl daemon-reload

echo "[5/6] systemctl enable + start"
sudo systemctl enable millennium_shadow.service
sudo systemctl start millennium_shadow.service

# Aguarda 5s e reporta status inicial.
sleep 5
echo "[6/6] status inicial:"
sudo systemctl status millennium_shadow.service --no-pager -l | head -20

echo
echo "=== tudo pronto ==="
echo "  Follow logs:   sudo journalctl -u millennium_shadow.service -f"
echo "  Shadow log:    tail -f ${REPO_PATH}/data/millennium_shadow/<RUN_ID>/logs/shadow.log"
echo "  Heartbeat:     cat ${REPO_PATH}/data/millennium_shadow/<RUN_ID>/state/heartbeat.json"
echo "  Stop:          sudo systemctl stop millennium_shadow.service"
echo "  Kill flag:     touch ${REPO_PATH}/data/millennium_shadow/<RUN_ID>/.kill"

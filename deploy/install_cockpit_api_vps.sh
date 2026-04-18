#!/usr/bin/env bash
# AURUM · installer pro Cockpit API no VPS.
# Uso:  bash deploy/install_cockpit_api_vps.sh [/srv/aurum.finance] [root]
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SERVICE_USER="${2:-$(whoami)}"
UNIT_SRC="${REPO_PATH}/deploy/aurum_cockpit_api.service"
UNIT_DST="/etc/systemd/system/aurum_cockpit_api.service"
ENV_DIR="/etc/aurum"
ENV_FILE="${ENV_DIR}/cockpit_api.env"

echo "=== AURUM cockpit_api installer ==="
echo "  repo:  ${REPO_PATH}"
echo "  user:  ${SERVICE_USER}"
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: ${REPO_PATH} nao existe." >&2
  exit 1
fi
if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit nao encontrada em ${UNIT_SRC}. Atualize o repo." >&2
  exit 1
fi

# 1/7: smoke — imports OK
echo "[1/7] smoke: python3 -c 'from tools.cockpit_api import build_app'"
(cd "${REPO_PATH}" && python3 -c "
import os
os.environ.setdefault('AURUM_COCKPIT_READ_TOKEN','dummy')
os.environ.setdefault('AURUM_COCKPIT_ADMIN_TOKEN','dummy')
from tools.cockpit_api import build_app
build_app()
") && echo "  OK"

# 2/7: dir /etc/aurum
echo "[2/7] mkdir -p ${ENV_DIR}"
sudo mkdir -p "${ENV_DIR}"

# 3/7: gera tokens (se env file nao existir)
if [ ! -f "${ENV_FILE}" ]; then
  echo "[3/7] gerando tokens em ${ENV_FILE}"
  READ_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sudo tee "${ENV_FILE}" >/dev/null <<EOF
AURUM_COCKPIT_READ_TOKEN=${READ_TOKEN}
AURUM_COCKPIT_ADMIN_TOKEN=${ADMIN_TOKEN}
EOF
  sudo chmod 600 "${ENV_FILE}"
  echo "  OK (tokens novos — vais precisar copiar pro launcher local)"
else
  echo "[3/7] ${ENV_FILE} ja existe — preservando tokens existentes"
fi

# 4/7: instala unit
echo "[4/7] instalando ${UNIT_DST}"
sed \
  -e "s|^User=.*|User=${SERVICE_USER}|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" \
  "${UNIT_SRC}" | sudo tee "${UNIT_DST}" >/dev/null

# 5/7: reload
echo "[5/7] systemctl daemon-reload"
sudo systemctl daemon-reload

# 6/7: enable + start
echo "[6/7] systemctl enable + start"
sudo systemctl enable aurum_cockpit_api.service
sudo systemctl restart aurum_cockpit_api.service

# 7/7: probe — retry loop tolera uvicorn boot lento
echo "[7/7] probe /v1/healthz"
for i in 1 2 3 4 5; do
  if curl -sf http://127.0.0.1:8787/v1/healthz >/tmp/cockpit_healthz.json 2>/dev/null; then
    python3 -m json.tool </tmp/cockpit_healthz.json
    rm -f /tmp/cockpit_healthz.json
    break
  fi
  if [ "${i}" = "5" ]; then
    echo "  ERRO: /v1/healthz nao respondeu em 5 tentativas" >&2
    sudo journalctl -u aurum_cockpit_api.service --no-pager -n 30 >&2
    exit 1
  fi
  sleep 1
done

echo
echo "=== tudo pronto ==="
echo "  Tokens:  sudo cat ${ENV_FILE}"
echo "  Logs:    sudo journalctl -u aurum_cockpit_api.service -f"
echo "  Probe:   curl -sH \"Authorization: Bearer \$READ\" localhost:8787/v1/runs"
echo "  Stop:    sudo systemctl stop aurum_cockpit_api.service"

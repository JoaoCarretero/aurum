#!/usr/bin/env bash
# AURUM - installer pro Cockpit API no VPS.
# Uso: bash deploy/install_cockpit_api_vps.sh [/srv/aurum.finance] [service-user]
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
DEFAULT_SERVICE_USER="${SUDO_USER:-$(whoami)}"
if [ "${DEFAULT_SERVICE_USER}" = "root" ]; then
  DEFAULT_SERVICE_USER="aurum"
fi
SERVICE_USER="${2:-${DEFAULT_SERVICE_USER}}"
SERVICE_GROUP="${SERVICE_USER}"
UNIT_SRC="${REPO_PATH}/deploy/aurum_cockpit_api.service"
UNIT_DST="/etc/systemd/system/aurum_cockpit_api.service"
ENV_DIR="/etc/aurum"
ENV_FILE="${ENV_DIR}/cockpit_api.env"
DATA_DIR="${REPO_PATH}/data"

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
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "[0/9] criando usuario de servico ${SERVICE_USER}"
  sudo useradd --system --create-home --home-dir "/home/${SERVICE_USER}" --shell /usr/sbin/nologin "${SERVICE_USER}"
else
  echo "[0/9] usuario de servico ${SERVICE_USER} ja existe"
fi
if ! getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
  echo "ERRO: grupo ${SERVICE_GROUP} nao existe." >&2
  exit 1
fi

# 1/9: deps - fastapi + uvicorn (pinned em pyproject.toml)
echo "[1/9] verificando fastapi + uvicorn"
if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "  instalando fastapi>=0.100,<1 uvicorn>=0.23,<1"
  # Tenta pip normal; fallback --break-system-packages pra Debian/Ubuntu PEP 668
  sudo python3 -m pip install --quiet 'fastapi>=0.100,<1' 'uvicorn>=0.23,<1' 2>/dev/null \
    || sudo python3 -m pip install --quiet --break-system-packages 'fastapi>=0.100,<1' 'uvicorn>=0.23,<1'
fi
echo "  OK"

# 2/9: smoke - imports OK
echo "[2/9] smoke: python3 -c 'from tools.cockpit_api import build_app'"
(cd "${REPO_PATH}" && python3 -c "
import os
os.environ.setdefault('AURUM_COCKPIT_READ_TOKEN','dummy')
os.environ.setdefault('AURUM_COCKPIT_ADMIN_TOKEN','dummy')
from tools.cockpit_api import build_app
build_app()
") && echo "  OK"

# 3/9: dirs e ownership minima
echo "[3/9] preparando ${ENV_DIR} e ${DATA_DIR}"
sudo mkdir -p "${ENV_DIR}" "${DATA_DIR}"
sudo chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${DATA_DIR}"
sudo chmod 750 "${DATA_DIR}"
sudo chmod 755 "${REPO_PATH}"

# 4/9: gera tokens (se env file nao existir)
if [ ! -f "${ENV_FILE}" ]; then
  echo "[4/9] gerando tokens em ${ENV_FILE}"
  READ_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sudo tee "${ENV_FILE}" >/dev/null <<EOF
AURUM_COCKPIT_READ_TOKEN=${READ_TOKEN}
AURUM_COCKPIT_ADMIN_TOKEN=${ADMIN_TOKEN}
EOF
  sudo chown root:"${SERVICE_GROUP}" "${ENV_FILE}"
  sudo chmod 640 "${ENV_FILE}"
  echo "  OK (tokens novos - vais precisar copiar pro launcher local)"
else
  echo "[4/9] ${ENV_FILE} ja existe - preservando tokens existentes"
  sudo chown root:"${SERVICE_GROUP}" "${ENV_FILE}"
  sudo chmod 640 "${ENV_FILE}"
fi

# 5/9: instala unit
echo "[5/9] instalando ${UNIT_DST}"
sed \
  -e "s|^User=.*|User=${SERVICE_USER}|" \
  -e "s|^Group=.*|Group=${SERVICE_GROUP}|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" \
  -e "s|^Environment=AURUM_COCKPIT_DATA_ROOT=.*|Environment=AURUM_COCKPIT_DATA_ROOT=${DATA_DIR}|" \
  "${UNIT_SRC}" | sudo tee "${UNIT_DST}" >/dev/null

# 6/9: reload
echo "[6/9] systemctl daemon-reload"
sudo systemctl daemon-reload

# 7/9: valida unit
echo "[7/9] systemd-analyze verify"
sudo systemd-analyze verify "${UNIT_DST}"

# 8/9: reset-failed + enable + restart
# reset-failed limpa estado caso StartLimitBurst=5 tenha sido atingido antes
# (ex.: deploy anterior falhou por dep faltando e travou o service em failed)
echo "[8/9] systemctl reset-failed + enable + restart"
sudo systemctl reset-failed aurum_cockpit_api.service 2>/dev/null || true
sudo systemctl enable aurum_cockpit_api.service
sudo systemctl restart aurum_cockpit_api.service

# 9/9: probe - retry loop tolera uvicorn boot lento
echo "[9/9] probe /v1/healthz"
for i in 1 2 3 4 5; do
  if curl --fail --silent --show-error http://127.0.0.1:8787/v1/healthz >/tmp/cockpit_healthz.json 2>/dev/null; then
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

#!/usr/bin/env bash
# AURUM · installer unificado pros runners per-engine (CITADEL/JUMP/RENAISSANCE).
#
# Uso:
#   bash deploy/install_engine_vps.sh <engine> <mode> [slot] [account_size] [repo_path] [user]
#
# Exemplos:
#   bash deploy/install_engine_vps.sh citadel paper desk-a 10000
#   bash deploy/install_engine_vps.sh jump shadow desk-a
#   bash deploy/install_engine_vps.sh renaissance paper desk-b 5000
#
# Parametros:
#   engine       citadel | jump | renaissance
#   mode         paper | shadow
#   slot         label da instancia (default: desk-a) — systemd unit sera
#                {engine}_{mode}@{slot}.service
#   account_size [paper only] tamanho da conta simulada (default: 10000)
#   repo_path    caminho do checkout (default: /srv/aurum.finance)
#   user         usuario do systemd service (default: $(whoami))
set -euo pipefail

ENGINE="${1:-}"
MODE="${2:-}"
SLOT="${3:-desk-a}"
ACCOUNT_SIZE="${4:-10000}"
REPO_PATH="${5:-/srv/aurum.finance}"
SERVICE_USER="${6:-$(whoami)}"

# ─── Validacao ─────────────────────────────────────────────────
if [ -z "${ENGINE}" ] || [ -z "${MODE}" ]; then
  echo "uso: $0 <engine> <mode> [slot] [account_size] [repo_path] [user]"
  echo "     engine: citadel | jump | renaissance"
  echo "     mode:   paper | shadow"
  exit 2
fi

case "${ENGINE}" in
  citadel|jump|renaissance) ;;
  *) echo "ERRO: engine invalido '${ENGINE}' (use citadel|jump|renaissance)"; exit 2 ;;
esac

case "${MODE}" in
  paper|shadow) ;;
  *) echo "ERRO: mode invalido '${MODE}' (use paper|shadow)"; exit 2 ;;
esac

ENGINE_UPPER="$(echo "${ENGINE}" | tr '[:lower:]' '[:upper:]')"
UNIT_NAME="${ENGINE}_${MODE}@.service"
UNIT_SRC="${REPO_PATH}/deploy/${UNIT_NAME}"
UNIT_DST="/etc/systemd/system/${UNIT_NAME}"
ENV_FILE="/etc/aurum/${ENGINE}-${MODE}-${SLOT}.env"
INSTANCE="${ENGINE}_${MODE}@${SLOT}.service"

case "${MODE}" in
  paper)
    RUNNER_PATH="tools/operations/${ENGINE}_paper.py"
    LABEL_ENV="AURUM_${ENGINE_UPPER}_PAPER_LABEL"
    ACCOUNT_ENV="AURUM_${ENGINE_UPPER}_PAPER_ACCOUNT_SIZE"
    ;;
  shadow)
    RUNNER_PATH="tools/maintenance/${ENGINE}_shadow.py"
    LABEL_ENV="AURUM_${ENGINE_UPPER}_SHADOW_LABEL"
    ACCOUNT_ENV=""
    ;;
esac

echo "=== AURUM ${ENGINE_UPPER} ${MODE} installer ==="
echo "  repo:    ${REPO_PATH}"
echo "  user:    ${SERVICE_USER}"
echo "  slot:    ${SLOT}"
echo "  unit:    ${INSTANCE}"
echo "  env:     ${ENV_FILE}"
if [ "${MODE}" = "paper" ]; then
  echo "  account: \$${ACCOUNT_SIZE}"
fi
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: ${REPO_PATH} nao existe"; exit 1
fi
if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit template nao encontrada em ${UNIT_SRC}"; exit 1
fi
if [ ! -f "${REPO_PATH}/${RUNNER_PATH}" ]; then
  echo "ERRO: runner nao encontrado em ${REPO_PATH}/${RUNNER_PATH}"; exit 1
fi

echo "[1/6] smoke: python ${RUNNER_PATH} --help"
(cd "${REPO_PATH}" && python3 "${RUNNER_PATH}" --help >/dev/null)
echo "  OK"

echo "[2/6] criando ${ENV_FILE}"
sudo mkdir -p /etc/aurum
{
  echo "${LABEL_ENV}=${SLOT}"
  if [ -n "${ACCOUNT_ENV}" ]; then
    echo "${ACCOUNT_ENV}=${ACCOUNT_SIZE}"
  fi
} | sudo tee "${ENV_FILE}" >/dev/null
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

echo "[5/6] enable + start ${INSTANCE}"
sudo systemctl enable "${INSTANCE}"
sudo systemctl start "${INSTANCE}"

sleep 10
echo "[6/6] status:"
sudo systemctl status "${INSTANCE}" --no-pager -l | head -20

echo
echo "=== ${ENGINE_UPPER} ${MODE} (${SLOT}) ativa ==="
echo "  Logs:      sudo journalctl -u ${INSTANCE} -f"
echo "  Env file:  ${ENV_FILE}"
echo "  Data dir:  ${REPO_PATH}/data/${ENGINE}_${MODE}/"
echo "  Stop:      sudo systemctl stop ${INSTANCE}"
echo "  Restart:   sudo systemctl restart ${INSTANCE}"

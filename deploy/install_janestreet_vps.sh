#!/usr/bin/env bash
# AURUM · installer pro JANESTREET paper runner (cross-venue funding arb)
# Uso (no VPS, root/sudo):
#   bash deploy/install_janestreet_vps.sh [/srv/aurum.finance] [aurum]
# Argumentos opcionais: <repo_path> <service_user>.
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SERVICE_USER="${2:-$(whoami)}"
UNIT_SRC="${REPO_PATH}/deploy/janestreet_paper.service"
UNIT_DST="/etc/systemd/system/janestreet_paper.service"
ENV_FILE="/etc/aurum/janestreet.env"

echo "=== AURUM janestreet paper installer ==="
echo "  repo:  ${REPO_PATH}"
echo "  user:  ${SERVICE_USER}"
echo "  unit:  ${UNIT_DST}"
echo "  env:   ${ENV_FILE}"
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: ${REPO_PATH} nao existe"; exit 1
fi
if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit nao encontrada em ${UNIT_SRC}"; exit 1
fi

echo "[1/6] smoke: python -c 'import ast; ast.parse(open(\"engines/janestreet.py\").read())'"
# janestreet.py usa parse_known_args e NÃO suporta --help (cai no menu
# interativo). AST parse garante syntax válida; import checa dependencies.
(cd "${REPO_PATH}" && python3 -c "
import ast, sys
ast.parse(open('engines/janestreet.py', encoding='utf-8').read())
print('  syntax OK')
")
echo "  OK"

echo "[2/6] criando ${ENV_FILE} (se nao existir)"
sudo mkdir -p /etc/aurum
if [ ! -f "${ENV_FILE}" ]; then
  sudo tee "${ENV_FILE}" >/dev/null <<'EOF'
# JANESTREET paper mode — sem API keys necessárias.
# Para demo/testnet/live precisaria das venues em config/keys.json.
EOF
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
sudo systemctl enable janestreet_paper.service
sudo systemctl start janestreet_paper.service

sleep 10
echo "[6/6] status:"
sudo systemctl status janestreet_paper.service --no-pager -l | head -20

echo
echo "=== janestreet paper runner ativo ==="
echo "  Logs:       sudo journalctl -u janestreet_paper.service -f"
echo "  Run dir:    ls ${REPO_PATH}/data/janestreet/"
echo "  Stop:       sudo systemctl stop janestreet_paper.service"
echo "  Nota:       shadow mode ainda não implementado pra JANESTREET (arbitragem"
echo "              cross-venue requer design diferente do MILLENNIUM shadow)."

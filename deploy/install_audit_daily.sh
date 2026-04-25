#!/usr/bin/env bash
# AURUM · installer pro timer de audit diaria live vs backtest.
#
# Instala /etc/aurum/audit_daily.env (token Telegram) + unit + timer
# systemd. Lê o token e chat id do config/keys.json do proprio repo.
#
# Uso: bash deploy/install_audit_daily.sh [/srv/aurum.finance]
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SVC_SRC="${REPO_PATH}/deploy/aurum_audit_daily.service"
TIMER_SRC="${REPO_PATH}/deploy/aurum_audit_daily.timer"
SVC_DST="/etc/systemd/system/aurum_audit_daily.service"
TIMER_DST="/etc/systemd/system/aurum_audit_daily.timer"
ENV_DST="/etc/aurum/audit_daily.env"
KEYS="${REPO_PATH}/config/keys.json"

echo "=== install aurum_audit_daily timer ==="

if [ ! -f "${SVC_SRC}" ] || [ ! -f "${TIMER_SRC}" ]; then
  echo "ERRO: templates nao encontrados em ${REPO_PATH}/deploy/"; exit 1
fi
if [ ! -f "${KEYS}" ]; then
  echo "ERRO: ${KEYS} nao encontrado — precisamos do telegram token dele."; exit 1
fi

echo "[1/5] gerando ${ENV_DST} do telegram bot em keys.json"
sudo mkdir -p /etc/aurum
TG_TOKEN=$(python3 -c "import json; print(json.load(open('${KEYS}'))['telegram']['bot_token'])")
TG_CHAT=$(python3 -c "import json; print(json.load(open('${KEYS}'))['telegram']['chat_id'])")
if [ -z "${TG_TOKEN}" ] || [ -z "${TG_CHAT}" ]; then
  echo "ERRO: telegram.bot_token ou chat_id vazio em keys.json"; exit 1
fi
sudo tee "${ENV_DST}" >/dev/null <<EOF
# AURUM daily audit — auto-gerado por install_audit_daily.sh.
# Reads from config/keys.json. NAO commitar.
AURUM_AUDIT_TG_TOKEN=${TG_TOKEN}
AURUM_AUDIT_TG_CHAT=${TG_CHAT}
EOF
sudo chmod 600 "${ENV_DST}"
echo "  ${ENV_DST} (600) criado"

echo "[2/5] copiando unit + timer pra /etc/systemd/system"
sudo cp "${SVC_SRC}" "${SVC_DST}"
sudo cp "${TIMER_SRC}" "${TIMER_DST}"
echo "  OK"

echo "[3/5] daemon-reload"
sudo systemctl daemon-reload

echo "[4/5] enable + start timer"
sudo systemctl enable --now aurum_audit_daily.timer

echo "[5/5] status"
sudo systemctl list-timers aurum_audit_daily.timer --no-pager

echo
echo "=== timer ativo ==="
echo "  Logs:       journalctl -u aurum_audit_daily.service -f"
echo "  Manual:     sudo systemctl start aurum_audit_daily.service"
echo "  Timer:      sudo systemctl list-timers aurum_audit_daily.timer"
echo "  Desativar:  sudo systemctl disable --now aurum_audit_daily.timer"
echo "  Relatorio:  /srv/aurum.finance/data/audits/live_vs_backtest/YYYY-MM-DD.json"

#!/usr/bin/env bash
# =====================================================================
# Installation de la VM SERVEUR (Debian 12 / Ubuntu) – à lancer en root depuis le dossier du projet
#   sudo ./scripts/vm_serveur_setup.sh <IP_VM_BASE> '<MOT_DE_PASSE_BASE>' [JETON_IHM]
# Exemple : sudo ./scripts/vm_serveur_setup.sh 10.0.0.5 'MotDePasseFort' 'jeton-secret'
# Appelé normalement par install.sh (qui génère le mot de passe et le jeton).
# Idempotent : peut être relancé après une mise à jour du code.
# =====================================================================
set -euo pipefail
DB_IP="${1:?IP de la VM Database (ex. 192.168.56.102)}"
DB_PASS="${2:?mot de passe du compte applicatif}"
TOKEN="${3:-}"
[[ "$DB_PASS" == *"'"* ]] && { echo "Le mot de passe ne doit pas contenir d'apostrophe."; exit 1; }
[[ $EUID -eq 0 ]] || { echo "À lancer avec sudo."; exit 1; }
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/carrefour-connecte

echo "[1/6] Paquets système"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-dev gcc libmariadb-dev mariadb-client rsync

echo "[2/6] Compte de service et dossiers"
id carrefour >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin carrefour
mkdir -p "$APP" /etc/carrefour /var/lib/carrefour
rsync -a --delete --exclude venv --exclude .git --exclude '__pycache__' --exclude '*.db' "$ROOT_DIR"/ "$APP"/

echo "[3/6] Environnement Python"
[[ -d "$APP/venv" ]] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
SQLITE_SEUL=0
if ! "$APP/venv/bin/pip" install -q -r "$APP/requirements-serveur.txt"; then
  # Le connecteur MariaDB se compile et exige MariaDB Connector/C >= 3.3.1 (Debian 12+, Ubuntu 24.04+).
  SQLITE_SEUL=1
  echo "  ATTENTION : connecteur Python MariaDB impossible à installer sur ce système"
  echo "  (cause probable : libmariadb trop ancienne, version installée : $(dpkg-query -W -f='${Version}' libmariadb-dev 2>/dev/null || echo inconnue))."
  echo "  Le serveur fonctionnera quand même, avec une base SQLite locale (/var/lib/carrefour/carrefour.db)."
fi

echo "[4/6] Test d'accès à la base ${DB_IP}"
mariadb -h "$DB_IP" -u carrefour -p"$DB_PASS" carrefour -e "SHOW TABLES;" >/dev/null \
  || { echo "Connexion à la base impossible (IP, mot de passe ou compte non autorisé pour cette VM)."
       echo "  Sur la VM base, relancer :  sudo ./install.sh database --serveur ${CARREFOUR_IP_SOURCE:-<IP_DE_CETTE_VM>}"
       echo "  puis ici la commande affichée à la fin (avec --mdp)."; exit 1; }

echo "[5/6] Configuration (/etc/carrefour/serveur.env, droits 640)"
cat > /etc/carrefour/serveur.env <<ENV
DB_HOST=${DB_IP}
DB_PORT=3306
DB_USER=carrefour
DB_PASSWORD=${DB_PASS}
DB_NAME=carrefour
CARREFOUR_TOKEN=${TOKEN}
SERVER_HOST=0.0.0.0
SERVER_PORT=5050
LOG_LEVEL=INFO
SQLITE_PATH=/var/lib/carrefour/carrefour.db
ENV
chown root:carrefour /etc/carrefour/serveur.env && chmod 640 /etc/carrefour/serveur.env
chown -R carrefour:carrefour /var/lib/carrefour
chown -R root:carrefour "$APP" && chmod -R g+rX "$APP"

echo "[6/6] Service systemd et vérification"
install -m 644 "$APP/deploy/carrefour-serveur.service" /etc/systemd/system/carrefour-serveur.service
systemctl daemon-reload
systemctl enable carrefour-serveur >/dev/null
systemctl restart carrefour-serveur
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then ufw allow 5050/tcp; fi
sleep 2
systemctl --no-pager --lines=3 status carrefour-serveur || true
CHECK=(--host 127.0.0.1 --token "$TOKEN"); (( SQLITE_SEUL )) && CHECK+=(--accepter-sqlite)
"$APP/venv/bin/python" "$APP/scripts/check_server.py" "${CHECK[@]}" && echo "VM Serveur prête (port 5050)." \
  || { echo "Auto-test en échec : journalctl -u carrefour-serveur -n 50"; exit 1; }

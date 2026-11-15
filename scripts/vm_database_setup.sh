#!/usr/bin/env bash
# =====================================================================
# Installation de la VM DATABASE (base de données) (Debian 12 / Ubuntu) – à lancer en root
#   sudo ./scripts/vm_database_setup.sh <IP_VM_BASE> <IP_VM_SERVEUR> '<MOT_DE_PASSE_BASE>'
# Exemple : sudo ./scripts/vm_database_setup.sh 192.168.56.102 192.168.56.101 'MotDePasseFort!'
# Idempotent : peut être relancé sans risque.
# =====================================================================
set -euo pipefail
DB_IP="${1:?IP de cette VM (ex. 192.168.56.102)}"
SRV_IP="${2:?IP de la VM Serveur (ex. 192.168.56.101)}"
DB_PASS="${3:?mot de passe du compte applicatif}"
[[ "$DB_PASS" == *"'"* ]] && { echo "Le mot de passe ne doit pas contenir d'apostrophe."; exit 1; }
[[ $EUID -eq 0 ]] || { echo "À lancer avec sudo."; exit 1; }
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/5] Installation de MariaDB"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq mariadb-server

echo "[2/5] Écoute réseau sur $DB_IP uniquement"
CONF=/etc/mysql/mariadb.conf.d/50-server.cnf
sed -i "s/^\s*bind-address.*/bind-address = ${DB_IP}/" "$CONF"
systemctl enable --now mariadb
systemctl restart mariadb

echo "[3/5] Création de la base et des 5 tables (server/schema.sql)"
mariadb < "$ROOT_DIR/server/schema.sql"

echo "[4/5] Compte applicatif limité à la VM Serveur (SELECT/INSERT/UPDATE/DELETE)"
mariadb <<SQL
CREATE USER IF NOT EXISTS 'carrefour'@'${SRV_IP}' IDENTIFIED BY '${DB_PASS}';
ALTER USER 'carrefour'@'${SRV_IP}' IDENTIFIED BY '${DB_PASS}';
GRANT SELECT, INSERT, UPDATE, DELETE ON carrefour.* TO 'carrefour'@'${SRV_IP}';
FLUSH PRIVILEGES;
SQL

echo "[5/5] Pare-feu (si ufw est actif) et vérifications"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow from "$SRV_IP" to any port 3306 proto tcp
fi
TABLES=$(mariadb -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='carrefour' AND table_type='BASE TABLE'")
echo "  tables présentes : ${TABLES}/5"
ss -tln | grep ":3306" || true
[[ "$TABLES" == "5" ]] && echo "VM Database prête." || { echo "Anomalie : 5 tables attendues."; exit 1; }

#!/usr/bin/env bash
# Pare-feu de la VM DATABASE : MariaDB (3306) uniquement depuis la VM Serveur ; SSH depuis la VM Serveur (défaut) ou depuis tous.
#   sudo ./scripts/vm_database_firewall.sh <IP_VM_SERVEUR> [SSH_DEPUIS]     ex. 10.10.10.1      ou   10.0.0.6 any
set -euo pipefail
SRV="${1:?IP de la VM Serveur sur le réseau données (ex. 10.10.10.1)}"
SSH_DEPUIS="${2:-$SRV}"
[[ $EUID -eq 0 ]] || { echo "À lancer avec sudo."; exit 1; }
apt-get install -y -qq ufw
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$SRV" to any port 3306 proto tcp comment 'MariaDB depuis la VM Serveur'
ufw allow from "$SSH_DEPUIS" to any port 22 proto tcp comment 'SSH administration'
ufw --force enable
ufw status verbose

#!/usr/bin/env bash
# Pare-feu de la VM SERVEUR : port 5050 (IHM) et SSH uniquement depuis le réseau clients, le reste fermé.
#   sudo ./scripts/vm_serveur_firewall.sh <RESEAU_CLIENTS_CIDR>        ex. 192.168.56.0/24
#   sudo ./scripts/vm_serveur_firewall.sh any                          réseau inconnu : 5050 et SSH ouverts à tous
set -euo pipefail
NET="${1:?Réseau des clients en notation CIDR (ex. 192.168.56.0/24) ou any}"
[[ $EUID -eq 0 ]] || { echo "À lancer avec sudo."; exit 1; }
apt-get install -y -qq ufw
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$NET" to any port 5050 proto tcp comment 'IHM carrefour (V2I)'
ufw allow from "$NET" to any port 22 proto tcp comment 'SSH administration'
ufw --force enable
ufw status verbose

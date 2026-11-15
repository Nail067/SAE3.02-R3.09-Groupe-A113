#!/usr/bin/env bash
# Réaffiche l'adresse, le jeton et l'état du serveur installé sur cette VM :   sudo ./scripts/infos.sh
set -uo pipefail
ENV=/etc/carrefour/serveur.env
[[ $EUID -eq 0 ]] || { echo "À lancer avec sudo (le jeton n'est lisible que par root)."; exit 1; }
if [[ -r "$ENV" ]]; then
  TOKEN="$(sed -n 's/^CARREFOUR_TOKEN=//p' "$ENV")"
  IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
  AUTRE="$(ip -4 -o addr show scope global | awk '{split($4,a,"/"); print a[1]}' | grep -v '^10\.0\.2\.15$' | head -1)"
  if [[ -z "$IP" || "$IP" == 10.0.2.15 ]] && [[ -n "$AUTRE" ]]; then IP="$AUTRE"; fi   # 10.0.2.15 : NAT VirtualBox
  echo "Serveur      : ${IP:-<IP_DE_CETTE_VM>}:5050   (toutes les adresses : $(ip -4 -o addr show scope global | awk '{split($4,a,"/"); printf "%s ", a[1]}'))"
  echo "Jeton IHM    : ${TOKEN}"
  echo "Sur le PC    : demarrer.bat vm ${IP:-<IP>} ${TOKEN}      (Linux : bash demarrer.sh vm ${IP:-<IP>} ${TOKEN})"
  echo "Service      : $(systemctl is-active carrefour-serveur 2>/dev/null)"
  journalctl -u carrefour-serveur -n 200 --no-pager 2>/dev/null | grep -o "Base de données : [a-z]*" | tail -1
fi
if [[ -s /etc/carrefour/db_password ]]; then
  echo "Base MariaDB : présente sur cette VM (mot de passe du compte applicatif : $(< /etc/carrefour/db_password))"
fi
[[ -r "$ENV" || -s /etc/carrefour/db_password ]] || echo "Rien d'installé sur cette VM (lancer install.sh)."

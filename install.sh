#!/usr/bin/env bash
# =====================================================================
# Installation d'une VM du projet « carrefour connecté » (SAÉ 3.02, groupe A113)
#
# VM QUELCONQUES (réseau déjà configuré, nombre de VM imposé) : le réseau n'est JAMAIS modifié.
#   1 VM  : sudo ./install.sh tout                                base + serveur sur la même VM
#   2 VM  : sudo ./install.sh database --serveur <IP_VM_SERVEUR>  sur la VM base (EN PREMIER)
#           sudo ./install.sh serveur --db <IP_VM_BASE> --mdp <MOT_DE_PASSE affiché par la VM base>
#
# VIRTUALBOX DE L'ÉQUIPE (cartes NAT / privé hôte / réseau interne, plan deploy/carrefour.conf) :
#           sudo ./install.sh database          puis          sudo ./install.sh serveur --mdp <MOT_DE_PASSE>
#
# Options :  --jeton <J>   impose le jeton des postes IHM (sinon généré, puis réutilisé)
#            --pare-feu    applique aussi le pare-feu (à la fin, une fois tout validé)
#            --dry-run     affiche ce qui serait fait, sans rien modifier
# Le mot de passe de la base et le jeton ne sont jamais stockés dans le dépôt : ils sont générés ici.
# =====================================================================
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROLE=""; DRY=0; FW=0; OPT_DB=""; OPT_SRV=""; OPT_MDP=""; OPT_JETON=""

usage() { sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; }
while (( $# )); do
  case "$1" in
    tout|database|serveur) ROLE="$1" ;;
    --db) OPT_DB="${2:?--db attend une adresse IP de la VM base}"; shift ;;
    --serveur) OPT_SRV="${2:?--serveur attend une adresse IP de la VM serveur}"; shift ;;
    --mdp) OPT_MDP="${2:?--mdp attend le mot de passe affiché par la VM base}"; shift ;;
    --jeton) OPT_JETON="${2:?--jeton attend une valeur}"; shift ;;
    --dry-run) DRY=1 ;;
    --pare-feu) FW=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Argument inconnu : $1"; echo; usage; exit 1 ;;
  esac
  shift
done
[[ -n "$ROLE" ]] || { usage; exit 1; }
if (( ! DRY )) && [[ $EUID -ne 0 ]]; then echo "À lancer avec sudo."; exit 1; fi

source "$ROOT_DIR/scripts/lib_reseau.sh"
charger_conf
[[ -n "$OPT_JETON" ]] && TOKEN="$OPT_JETON"
[[ -n "$OPT_MDP" ]] && DB_PASSWORD="$OPT_MDP"
SECRETS=/etc/carrefour

# Mode « réseau existant » : VM quelconque, on ne touche pas aux cartes réseau.
GARDER_RESEAU=0
[[ "$ROLE" == tout || -n "$OPT_DB" || -n "$OPT_SRV" ]] && GARDER_RESEAU=1

secret_aleatoire() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-20}" || true; }
valide_ip() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || erreur "« $1 » n'est pas une adresse IPv4."; }
ip_vers() {  # adresse locale utilisée pour joindre $1
  ip -4 route get "$1" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1
}
ip_principale() {  # adresse à donner aux postes IHM : on évite 10.0.2.15 (NAT VirtualBox, injoignable depuis le PC)
  local a autre
  a="$(ip_vers 1.1.1.1)"
  autre="$(ips_locales | tr ' ' '\n' | grep -v '^10\.0\.2\.15$' | grep . | head -1)"
  if [[ -z "$a" || "$a" == 10.0.2.15 ]] && [[ -n "$autre" ]]; then a="$autre"; fi
  echo "${a:-<IP_DE_CETTE_VM>}"
}
ips_locales() { ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); printf "%s ", a[1]}'; }

# Mot de passe de la base : imposé (--mdp / carrefour.local.conf), sinon réutilisé, sinon généré.
mot_de_passe_base() {
  if [[ -z "$DB_PASSWORD" && -s "$SECRETS/db_password" ]]; then DB_PASSWORD="$(<"$SECRETS/db_password")"; fi
  if [[ -z "$DB_PASSWORD" && -s "$SECRETS/serveur.env" ]]; then
    DB_PASSWORD="$(sed -n 's/^DB_PASSWORD=//p' "$SECRETS/serveur.env")"
  fi
  if [[ -z "$DB_PASSWORD" ]]; then DB_PASSWORD="$(secret_aleatoire 20)"; fi
  [[ "$DB_PASSWORD" == *"'"* ]] && erreur "le mot de passe ne doit pas contenir d'apostrophe."
  if (( ! DRY )); then
    mkdir -p "$SECRETS"; umask 077; printf '%s' "$DB_PASSWORD" > "$SECRETS/db_password"; chmod 600 "$SECRETS/db_password"
  fi
}

# Jeton des postes IHM : imposé (--jeton / carrefour.local.conf), sinon réutilisé, sinon généré.
jeton_ihm() {
  if [[ -z "$TOKEN" && -s "$SECRETS/serveur.env" ]]; then TOKEN="$(sed -n 's/^CARREFOUR_TOKEN=//p' "$SECRETS/serveur.env")"; fi
  if [[ -z "$TOKEN" ]]; then TOKEN="$(secret_aleatoire 16)"; fi
}

# Rôle serveur : le mot de passe de la base doit être connu AVANT de toucher à quoi que ce soit.
if [[ "$ROLE" == serveur && -z "$DB_PASSWORD" ]] && ! grep -qs '^DB_PASSWORD=.' "$SECRETS/serveur.env"; then
  erreur "mot de passe de la base inconnu : relancer avec --mdp <MOT_DE_PASSE> (affiché à la fin de l'installation de la VM base)."
fi

echo "=== Installation : rôle ${ROLE^^} ($( (( GARDER_RESEAU )) && echo 'réseau existant conservé' || echo 'plan VirtualBox deploy/carrefour.conf')) ==="

# ------------------------------------------------------------------ 1. réseau
echo "[1/4] Réseau"
if (( GARDER_RESEAU )); then
  echo "  aucune modification du réseau ; adresses de cette VM : $(ips_locales)"
  case "$ROLE" in
    tout)
      DB_BIND=127.0.0.1; SRV_SRC=127.0.0.1; DB_CIBLE=127.0.0.1 ;;
    database)
      [[ -n "$OPT_SRV" ]] || erreur "préciser l'adresse de la VM serveur : sudo ./install.sh database --serveur <IP_VM_SERVEUR>"
      valide_ip "$OPT_SRV"; SRV_SRC="$OPT_SRV"
      DB_BIND="$(ip_vers "$OPT_SRV")"
      [[ -n "$DB_BIND" ]] || erreur "aucune route vers $OPT_SRV depuis cette VM (vérifier l'adresse et le réseau)."
      echo "  MariaDB écoutera sur $DB_BIND (adresse de cette VM vers $OPT_SRV)" ;;
    serveur)
      [[ -n "$OPT_DB" ]] || erreur "préciser l'adresse de la VM base : sudo ./install.sh serveur --db <IP_VM_BASE> --mdp <MOT_DE_PASSE>"
      valide_ip "$OPT_DB"; DB_CIBLE="$OPT_DB"
      SRV_SRC="$(ip_vers "$OPT_DB")"
      echo "  base de données visée : $OPT_DB (vue depuis cette VM en ${SRV_SRC:-?})" ;;
  esac
else
  [[ "$ROLE" == tout ]] && erreur "rôle inattendu"
  detecter_interfaces
  if [[ "$ROLE" == serveur ]]; then
    appliquer_reseau "${IFACE_CLIENTS}=${IP_SERVEUR_CLIENTS}" "${IFACE_DONNEES}=${IP_SERVEUR_DONNEES}"
  else
    appliquer_reseau "${IFACE_DONNEES}=${IP_DATABASE}"
  fi
  DB_BIND="$IP_DATABASE"; SRV_SRC="$IP_SERVEUR_DONNEES"; DB_CIBLE="$IP_DATABASE"
fi
if (( DRY )); then echo "(--dry-run : aucune modification effectuée)"; exit 0; fi

# ------------------------------------------------------------------ 2-4. logiciels
installer_base() {
  mot_de_passe_base
  echo "[2/4] MariaDB, base et 5 tables"
  bash "$ROOT_DIR/scripts/vm_database_setup.sh" "$DB_BIND" "$SRV_SRC" "$DB_PASSWORD"
}

installer_serveur() {
  jeton_ihm
  if [[ -z "$DB_PASSWORD" && -s "$SECRETS/serveur.env" ]]; then
    DB_PASSWORD="$(sed -n 's/^DB_PASSWORD=//p' "$SECRETS/serveur.env")"
  fi
  [[ -n "$DB_PASSWORD" ]] || erreur "mot de passe de la base inconnu : relancer avec --mdp <MOT_DE_PASSE> (affiché à la fin de l'installation de la VM base)."
  if [[ "$ROLE" == serveur ]]; then
    echo "[2/4] Attente de la base (${DB_CIBLE}:3306)"
    local ok=0
    for _ in $(seq 1 30); do
      if timeout 3 bash -c "exec 3<>/dev/tcp/${DB_CIBLE}/3306" 2>/dev/null; then ok=1; break; fi
      sleep 2
    done
    (( ok )) || erreur "la base ne répond pas sur ${DB_CIBLE}:3306. Installer d'abord la VM base (sudo ./install.sh database --serveur ${SRV_SRC:-<IP_DE_CETTE_VM>})."
    echo "  base joignable."
  fi
  echo "[3/4] Serveur (service systemd) et auto-test"
  CARREFOUR_IP_SOURCE="$SRV_SRC" bash "$ROOT_DIR/scripts/vm_serveur_setup.sh" "$DB_CIBLE" "$DB_PASSWORD" "$TOKEN"
}

pare_feu() {
  (( FW )) || { echo "  pare-feu non appliqué (relancer avec --pare-feu une fois l'installation validée)"; return 0; }
  if (( GARDER_RESEAU )); then
    # Réseau inconnu : SSH et port 5050 restent ouverts à tous (pas de risque de se bloquer), le reste est fermé.
    case "$ROLE" in
      tout|serveur) bash "$ROOT_DIR/scripts/vm_serveur_firewall.sh" any ;;
      database) bash "$ROOT_DIR/scripts/vm_database_firewall.sh" "$SRV_SRC" any ;;
    esac
  else
    case "$ROLE" in
      serveur) bash "$ROOT_DIR/scripts/vm_serveur_firewall.sh" "$RESEAU_CLIENTS" ;;
      database) bash "$ROOT_DIR/scripts/vm_database_firewall.sh" "$SRV_SRC" ;;
    esac
  fi
}

recap_pc() {
  local ip="$1"
  cat <<RECAP

  ┌──────────────────────────────────────────────────────────────────┐
    Serveur prêt :  ${ip}:5050
    Jeton IHM    :  ${TOKEN}
    Sur le PC (Windows) :  demarrer.bat vm ${ip} ${TOKEN}
    Sur le PC (Linux)   :  bash demarrer.sh vm ${ip} ${TOKEN}
    Contrôle            :  python scripts/check_server.py --host ${ip} --token ${TOKEN}
  └──────────────────────────────────────────────────────────────────┘
  Réafficher ces informations plus tard :  sudo ./scripts/infos.sh
RECAP
}

case "$ROLE" in
  database)
    installer_base
    echo "[3/4] Pare-feu"; pare_feu
    echo "[4/4] Terminé"
    if (( GARDER_RESEAU )); then CMD="sudo ./install.sh serveur --db ${DB_BIND} --mdp ${DB_PASSWORD}"
    else CMD="sudo ./install.sh serveur --mdp ${DB_PASSWORD}"; fi
    cat <<RECAP

  Base prête : ${DB_BIND}:3306 (base '${DB_NAME}', compte '${DB_USER}'@'${SRV_SRC}').
  Étape suivante, sur la VM serveur (copier la ligne entière) :

      ${CMD}

RECAP
    ;;
  serveur)
    installer_serveur
    pare_feu
    echo "[4/4] Terminé"
    if (( GARDER_RESEAU )); then recap_pc "$(ip_principale)"; else recap_pc "$IP_SERVEUR_CLIENTS"; fi
    echo "  (autres adresses de cette VM : $(ips_locales))"
    ;;
  tout)
    installer_base
    installer_serveur
    pare_feu
    echo "[4/4] Terminé"
    recap_pc "$(ip_principale)"
    echo "  (autres adresses de cette VM : $(ips_locales))"
    ;;
esac

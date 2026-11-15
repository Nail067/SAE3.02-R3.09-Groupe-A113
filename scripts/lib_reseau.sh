#!/usr/bin/env bash
# Fonctions partagées par install.sh : lecture de deploy/carrefour.conf et configuration réseau automatique.
# (ne pas lancer directement)

erreur() { echo "ERREUR : $*" >&2; exit 1; }

# --- Lecture de la configuration : défauts < carrefour.conf < carrefour.local.conf < variables CARREFOUR_<NOM>
charger_conf() {
  IP_SERVEUR_CLIENTS=192.168.56.101; IP_SERVEUR_DONNEES=10.10.10.1; IP_DATABASE=10.10.10.2; MASQUE=24
  RESEAU_CLIENTS=192.168.56.0/24; DB_NAME=carrefour; DB_USER=carrefour; DB_PASSWORD=""
  TOKEN=""; IFACE_CLIENTS=""; IFACE_DONNEES=""
  local f k v
  for f in "$ROOT_DIR/deploy/carrefour.conf" "$ROOT_DIR/deploy/carrefour.local.conf"; do
    [[ -f "$f" ]] || continue
    while IFS='=' read -r k v; do
      k="${k//[[:space:]]/}"
      v="$(echo "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']$//")"
      printf -v "$k" '%s' "$v"
    done < <(grep -E '^[[:space:]]*[A-Z_]+[[:space:]]*=' "$f")
  done
  for k in IP_SERVEUR_CLIENTS IP_SERVEUR_DONNEES IP_DATABASE MASQUE RESEAU_CLIENTS DB_NAME DB_USER DB_PASSWORD TOKEN IFACE_CLIENTS IFACE_DONNEES; do
    v="CARREFOUR_$k"
    [[ -n "${!v:-}" ]] && printf -v "$k" '%s' "${!v}"
  done
  [[ -n "${CARREFOUR_HOST:-}" ]] && IP_SERVEUR_CLIENTS="$CARREFOUR_HOST"
  [[ "$DB_PASSWORD" == *"'"* ]] && erreur "DB_PASSWORD ne doit pas contenir d'apostrophe."
  return 0
}

# --- Interfaces physiques, dans l'ordre des cartes (celui des adaptateurs VirtualBox 1, 2, 3...)
lister_interfaces() {
  if [[ -n "${CARREFOUR_FAKE_IFACES:-}" ]]; then tr ' ' '\n' <<<"$CARREFOUR_FAKE_IFACES"; return 0; fi
  local d n
  for d in /sys/class/net/*; do
    n="$(basename "$d")"
    [[ "$n" == lo || ! -e "$d/device" ]] && continue
    echo "$(<"$d/ifindex") $n"
  done | sort -n | awk '{print $2}'
}

# --- Attribue les rôles : 1re carte = NAT (Internet), puis réseau clients (serveur), puis réseau données
detecter_interfaces() {
  mapfile -t IFACES < <(lister_interfaces)
  local n=${#IFACES[@]} besoin=2 i
  [[ "$ROLE" == serveur ]] && besoin=3
  (( n >= besoin )) || erreur "cette VM a $n carte(s) réseau, $besoin attendues (adaptateurs VirtualBox : NAT$( [[ $ROLE == serveur ]] && echo ' + réseau privé hôte') + réseau interne 'reseau-donnees'). Vérifier Configuration > Réseau.
  Sur une VM quelconque (réseau déjà configuré), ne pas utiliser ce mode : sudo ./install.sh tout   (1 VM)
  ou sudo ./install.sh database --serveur <IP_SERVEUR> puis serveur --db <IP_BASE> --mdp <MDP>   (2 VM)."
  NAT_IF="${IFACES[0]}"
  for i in "${IFACES[@]}"; do ip -4 -o addr show dev "$i" 2>/dev/null | grep -q ' 10\.0\.2\.' && NAT_IF="$i"; done
  RESTE=()
  for i in "${IFACES[@]}"; do [[ "$i" != "$NAT_IF" ]] && RESTE+=("$i"); done
  if [[ "$ROLE" == serveur ]]; then
    : "${IFACE_CLIENTS:=${RESTE[0]}}"; : "${IFACE_DONNEES:=${RESTE[1]}}"
  else
    : "${IFACE_DONNEES:=${RESTE[0]}}"
  fi
}

detecter_pile() {
  if [[ -n "${CARREFOUR_NETSTACK:-}" ]]; then echo "$CARREFOUR_NETSTACK"; return 0; fi
  if command -v netplan >/dev/null 2>&1 && compgen -G "/etc/netplan/*.yaml" >/dev/null; then echo netplan
  elif [[ -f /etc/network/interfaces ]] && command -v ifup >/dev/null 2>&1; then echo ifupdown
  elif command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager 2>/dev/null; then echo networkmanager
  else echo inconnue; fi
}

gen_netplan() {
  echo "# Généré par install.sh (SAÉ 3.02) - ne pas modifier à la main"
  echo "network:"; echo "  version: 2"; echo "  ethernets:"
  local p
  for p in "$@"; do
    echo "    ${p%%=*}:"; echo "      dhcp4: false"; echo "      optional: true"; echo "      addresses: [${p##*=}/${MASQUE}]"
  done
}

gen_ifupdown() {
  echo "# Généré par install.sh (SAÉ 3.02) - ne pas modifier à la main"
  local p
  for p in "$@"; do
    echo "auto ${p%%=*}"; echo "iface ${p%%=*} inet static"; echo "    address ${p##*=}/${MASQUE}"; echo
  done
}

# --- Applique les adresses : arguments = paires interface=adresse. En --dry-run : affiche sans rien modifier.
appliquer_reseau() {
  local pile p cible=""; pile="$(detecter_pile)"
  echo "  carte NAT (Internet)  : $NAT_IF  (DHCP, inchangée)"
  for p in "$@"; do echo "  carte ${p%%=*}  ->  ${p##*=}/${MASQUE}"; done
  echo "  gestionnaire réseau   : $pile"
  case "$pile" in netplan) cible=/etc/netplan/60-carrefour.yaml ;; ifupdown) cible=/etc/network/interfaces.d/carrefour ;; esac
  if (( DRY )); then
    case "$pile" in
      netplan) echo "--- $cible"; gen_netplan "$@" ;;
      ifupdown) echo "--- $cible"; gen_ifupdown "$@" ;;
      networkmanager) for p in "$@"; do echo "nmcli connection add type ethernet ifname ${p%%=*} con-name carrefour-${p%%=*} ipv4.method manual ipv4.addresses ${p##*=}/${MASQUE}"; done ;;
      *) echo "(aucun gestionnaire reconnu : adresses posées avec 'ip addr', non persistantes)" ;;
    esac
    return 0
  fi
  case "$pile" in
    netplan)
      gen_netplan "$@" > "$cible"; chmod 600 "$cible"; netplan generate; netplan apply ;;
    ifupdown)
      mkdir -p /etc/network/interfaces.d
      grep -qs '^source.*interfaces.d' /etc/network/interfaces || echo 'source /etc/network/interfaces.d/*' >> /etc/network/interfaces
      gen_ifupdown "$@" > "$cible"
      for p in "$@"; do ifdown --force "${p%%=*}" >/dev/null 2>&1 || true; ifup "${p%%=*}" >/dev/null 2>&1 || true; done ;;
    networkmanager)
      for p in "$@"; do
        nmcli connection delete "carrefour-${p%%=*}" >/dev/null 2>&1 || true
        nmcli connection add type ethernet ifname "${p%%=*}" con-name "carrefour-${p%%=*}" ipv4.method manual ipv4.addresses "${p##*=}/${MASQUE}" >/dev/null
        nmcli connection up "carrefour-${p%%=*}" >/dev/null || true
      done ;;
    *) echo "  ATTENTION : gestionnaire réseau non reconnu, configuration non persistante." ;;
  esac
  for p in "$@"; do ip link set "${p%%=*}" up; ip addr replace "${p##*=}/${MASQUE}" dev "${p%%=*}"; done
  for p in "$@"; do
    ip -4 -o addr show dev "${p%%=*}" | grep -q " ${p##*=}/" || erreur "l'adresse ${p##*=} n'est pas active sur ${p%%=*}"
  done
}

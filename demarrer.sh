#!/usr/bin/env bash
# Démarrage en une commande (Linux / macOS) :
#   bash demarrer.sh        démonstration complète sur ce poste (aucune VM nécessaire)
#   bash demarrer.sh vm IP JETON   interface seule, connectée au serveur d'une VM (IP et jeton affichés par install.sh)
#   bash demarrer.sh vm            idem avec la dernière adresse et le dernier jeton utilisés
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "Python 3.10 ou plus récent est requis."
  echo "  Debian/Ubuntu : sudo apt install -y python3 python3-venv python3-pip      macOS : brew install python"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Première utilisation : préparation de l'environnement (1 à 2 minutes, Internet requis)..."
  "$PY" -m venv .venv || { echo "Échec de la création de l'environnement. Debian/Ubuntu : sudo apt install -y python3-venv"; exit 1; }
fi
if [[ ! -f .venv/.ok ]]; then
  echo "Python utilisé : $(.venv/bin/python --version)"
  # Le connecteur MariaDB ne sert qu'au serveur des VM : inutile (et parfois impossible à compiler) pour l'interface.
  grep -vi '^mariadb' requirements.txt > .venv/requirements-client.txt
  # --only-binary : jamais de compilation (évite l'erreur « compilateur C++ requis »)
  PIP=(.venv/bin/python -m pip install -q --disable-pip-version-check --only-binary=:all:)
  if ! "${PIP[@]}" -r .venv/requirements-client.txt; then
    echo "Versions figées indisponibles pour votre système : installation de la dernière version de PyQt6..."
    "${PIP[@]}" PyQt6 || { echo "Installation impossible : connexion Internet requise, et Python 3.10 minimum."; exit 1; }
  fi
  touch .venv/.ok
fi

if [[ "$(uname -s)" == Linux && -z "${QT_QPA_PLATFORM:-}" ]] && ! ldconfig -p 2>/dev/null | grep -q libxcb-cursor; then
  echo "ATTENTION : bibliothèque graphique manquante. Si la fenêtre ne s'ouvre pas : sudo apt install -y libxcb-cursor0"
fi

if [[ "${1:-}" == "vm" ]]; then exec .venv/bin/python run_demo.py --vm "${@:2}"; fi
exec .venv/bin/python run_demo.py

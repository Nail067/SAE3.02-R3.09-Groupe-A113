#!/usr/bin/env bash
# Sauvegarde logique de la base (VM Database) :  sudo ./scripts/backup_db.sh [dossier]   -> carrefour_AAAAMMJJ_HHMM.sql.gz
set -euo pipefail
DIR="${1:-/var/backups/carrefour}"
mkdir -p "$DIR"
OUT="$DIR/carrefour_$(date +%Y%m%d_%H%M).sql.gz"
mariadb-dump --single-transaction --routines carrefour | gzip > "$OUT"
echo "Sauvegarde créée : $OUT"

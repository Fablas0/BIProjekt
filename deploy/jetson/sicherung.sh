#!/usr/bin/env bash
# Taegliche Sicherung der Nutzerdatenbank.
#
# Gesichert wird ueber das Backup-API von SQLite (VACUUM INTO), nicht per
# Dateikopie: eine Kopie waehrend eines Schreibvorgangs waere inkonsistent.
# Vorgehalten werden 14 Staende -- gleicher Rhythmus wie die Vorhaltezeit
# der Champions-Quelle, aus demselben Grund: aelteres braucht niemand mehr.
set -euo pipefail

DATEN="${1:-/var/lib/vgc-bi}"
QUELLE="${DATEN}/vgc_nutzer.db"
ZIEL="${DATEN}/sicherungen/vgc_nutzer_$(date +%Y-%m-%d).db"

if [[ ! -f "${QUELLE}" ]]; then
  echo "Keine Nutzerdatenbank unter ${QUELLE} -- nichts zu sichern."
  exit 0
fi

sqlite3 "${QUELLE}" "VACUUM INTO '${ZIEL}.neu'"
mv "${ZIEL}.neu" "${ZIEL}"
echo "Gesichert: ${ZIEL}"

# Aufbewahrung: die juengsten 14 Staende.
ls -1t "${DATEN}/sicherungen/"vgc_nutzer_*.db 2>/dev/null | tail -n +15 | xargs -r rm --

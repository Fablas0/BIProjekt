#!/usr/bin/env bash
# Richtet die Anwendung als systemd-Dienst auf dem Jetson ein.
#
# Wiederholbar: ein erneuter Lauf aktualisiert Abhaengigkeiten und Units,
# ohne Daten anzufassen. Muss mit sudo aus der Projektwurzel laufen.
set -euo pipefail

if [[ $(id -u) -ne 0 ]]; then
  echo "Bitte mit sudo ausfuehren." >&2
  exit 1
fi

PROJEKT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NUTZER="${SUDO_USER:-bautb}"
DATEN=/var/lib/vgc-bi

echo "== Projekt: ${PROJEKT}, Dienstnutzer: ${NUTZER} =="

# Datenverzeichnis ausserhalb des Repositories: ein "git clean" oder ein
# frischer Checkout darf die Nutzerdatenbank niemals beruehren.
install -d -o "${NUTZER}" -g "${NUTZER}" "${DATEN}" "${DATEN}/sicherungen"

# Python-Umgebung im Projekt.
sudo -u "${NUTZER}" python3 -m venv "${PROJEKT}/.venv"
sudo -u "${NUTZER}" "${PROJEKT}/.venv/bin/pip" install --upgrade pip -q
sudo -u "${NUTZER}" "${PROJEKT}/.venv/bin/pip" install -r "${PROJEKT}/requirements.txt" -q

# systemd-Units aus den Vorlagen, Pfade und Nutzer eingesetzt.
for unit in vgc-bi.service vgc-bi-aktualisieren.service vgc-bi-aktualisieren.timer \
            vgc-bi-sicherung.service vgc-bi-sicherung.timer; do
  sed -e "s|@PROJEKT@|${PROJEKT}|g" -e "s|@NUTZER@|${NUTZER}|g" \
      -e "s|@DATEN@|${DATEN}|g" \
      "${PROJEKT}/deploy/jetson/${unit}" > "/etc/systemd/system/${unit}"
done

systemctl daemon-reload
systemctl enable --now vgc-bi
systemctl enable --now vgc-bi-aktualisieren.timer
systemctl enable --now vgc-bi-sicherung.timer

echo "== Fertig. Status: =="
systemctl --no-pager status vgc-bi | head -5
echo "Naechster Schritt: Cloudflare Tunnel gemaess deploy/jetson/README.md."

# Betrieb auf dem Jetson unter bi.fablas.org

Die Anwendung laeuft als systemd-Dienst auf dem Jetson (`bautb@192.168.178.163`)
und wird ueber einen **Cloudflare Tunnel** unter `bi.fablas.org`
veroeffentlicht -- als Unterseite der bestehenden Domain `fablas.org`.

## Warum dieser Aufbau

* **Kein offener Port.** Der Tunnel baut eine ausgehende Verbindung zu
  Cloudflare auf; die Fritzbox braucht keine Portfreigabe, und der Jetson ist
  aus dem Internet nicht direkt adressierbar. Streamlit lauscht nur auf
  `127.0.0.1`.
* **Anmeldung in der Anwendung.** Die Zugangskontrolle liegt in der Anwendung
  selbst (`bi.ui.anmeldung`): PBKDF2-Passwoerter, Sperre nach Fehlversuchen,
  Registrierung nur mit Zugangscode. Die Maske folgt dem Designsystem der
  Seite. Wer zusaetzlich eine Schicht davor will, kann im Zero-Trust-Dashboard
  **Cloudflare Access** auf `bi.fablas.org` legen -- noetig ist es nicht.
* **Eigene Daten bleiben auf dem Geraet.** Das Warehouse ist aus dem Archiv
  jederzeit neu ableitbar; die Nutzerdatenbank (`vgc_nutzer.db`) ist es
  **nicht**. Sie liegt ausserhalb des Repositories unter
  `/var/lib/vgc-bi/` und wird taeglich gesichert.

## Einrichtung (einmalig, auf dem Jetson)

```bash
ssh bautb@192.168.178.163

# 1. Repository und Dienst einrichten (fragt nichts, ist wiederholbar):
git clone https://github.com/Fablas0/BIProjekt.git ~/BIProjekt
cd ~/BIProjekt
sudo bash deploy/jetson/install.sh

# 2. Zugangscode fuer die Selbstregistrierung setzen:
sudo systemctl edit vgc-bi        # im [Service]-Block:
#   Environment=VGC_BI_REGISTRIERUNGSCODE=<selbst gewaehlt>
sudo systemctl restart vgc-bi

# 3. Cloudflare Tunnel (einmalig; cloudflared fuer arm64):
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 \
  -o /tmp/cloudflared && sudo install /tmp/cloudflared /usr/local/bin/cloudflared
cloudflared tunnel login                       # Browser: fablas.org waehlen
cloudflared tunnel create vgc-bi
sudo mkdir -p /etc/cloudflared
sudo cp deploy/jetson/cloudflared-config.yml /etc/cloudflared/config.yml
# In /etc/cloudflared/config.yml die Tunnel-ID eintragen (steht in der
# Ausgabe von "tunnel create" bzw. unter ~/.cloudflared/*.json).
sudo cp ~/.cloudflared/<TUNNEL-ID>.json /etc/cloudflared/
cloudflared tunnel route dns vgc-bi bi.fablas.org   # legt den DNS-Eintrag an
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

Danach: `https://bi.fablas.org` aufrufen. Beim ersten Besuch bietet die
Anwendung die **Einrichtung** an -- das erste Konto erhaelt die
Verwaltungsrolle. Erst danach greift der Registrierungscode.

## Laufender Betrieb

Der taegliche Datenabzug laeuft weiterhin in GitHub Actions und schreibt das
Archiv ins Repository. Der Jetson holt ihn sich per Timer
(`vgc-bi-aktualisieren.timer`, taeglich 06:00): `git pull`, danach
Neuverarbeitung aus dem Archiv **ohne** Quellzugriff. Die Nutzerdatenbank ist
davon nie betroffen.

```bash
systemctl status vgc-bi cloudflared            # laeuft alles?
journalctl -u vgc-bi -e                        # Anwendungsprotokoll
sudo systemctl start vgc-bi-aktualisieren      # Datenstand sofort holen
sudo systemctl start vgc-bi-sicherung          # Sicherung sofort ziehen
ls /var/lib/vgc-bi/sicherungen/                # taegliche Sicherungen (14 Stueck)
```

## Wiederherstellung

Faellt der Jetson aus, ist nichts verloren, was nicht wiederkommt:

* Warehouse und Archiv: aus dem Repository (`git clone` + Kaltstart).
* Nutzerdatenbank: juengste Datei aus `/var/lib/vgc-bi/sicherungen/` nach
  `/var/lib/vgc-bi/vgc_nutzer.db` kopieren. Die Sicherungen zusaetzlich
  ausserhalb des Geraets abzulegen (z. B. regelmaessig per `scp` auf den
  Rechner) bleibt Handarbeit -- der Jetson kennt kein zweites Laufwerk.

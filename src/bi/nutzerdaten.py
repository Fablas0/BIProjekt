"""Eigene Datenhaltung: Nutzerkonten, PC-System und Teams.

Warum eine zweite Datenbank
---------------------------
Das Data Warehouse ist eine **Ableitung**: es entsteht bei jedem Start aus dem
Rohdatenarchiv neu und darf jederzeit verworfen werden. Genau das macht es als
Ablage fuer eigene Daten untauglich -- ein Team, das jemand angelegt hat, waere
beim naechsten Neuaufbau verschwunden.

Eigene Daten sind der umgekehrte Fall: sie sind nirgends sonst vorhanden, nicht
wiederbeschaffbar und muessen jede Neuberechnung ueberleben. Sie liegen deshalb
in einer eigenen Datei, die kein Ladelauf und kein Zuruecksetzen beruehrt:

===========================  ==========================  =========================
                             Data Warehouse              Nutzerdatenbank
===========================  ==========================  =========================
Herkunft                     abgeleitet aus dem Archiv   von Hand erfasst
Wiederbeschaffbar            ja, in Sekunden             nein
Verhalten beim Neuaufbau     wird neu erzeugt            bleibt unberuehrt
Datei                        ``data/vgc_dwh.db``         ``data/vgc_nutzer.db``
===========================  ==========================  =========================

Verbunden werden beide ueber ``ATTACH DATABASE``: die Nutzerdatenbank haengt
unter dem Schemanamen ``nutzer`` an derselben Verbindung. Damit sind Abfragen
ueber beide Bestaende hinweg moeglich -- eine Box laesst sich unmittelbar gegen
``Dim_Pokemon`` verknuepfen -- ohne die Trennung der Lebenszyklen aufzugeben.

Der Bezug zur Pokemon-Dimension laeuft ueber den **natuerlichen Schluessel**
(``slug``), nicht ueber den Surrogatschluessel. Der Surrogatschluessel wechselt
bei jedem Neuaufbau des Warehouse; eine Box, die darauf zeigte, waere danach
falsch verknuepft -- und zwar still, nicht mit einem Fehler.

Anmeldung
---------
Passwoerter werden mit PBKDF2-HMAC-SHA256 abgelegt, je Konto mit eigenem Salz
und mit der Iterationszahl im Datensatz. Beides steht in der Tabelle, damit die
Zahl spaeter angehoben werden kann, ohne bestehende Konten zu entwerten: beim
naechsten erfolgreichen Anmelden wird der Hash mit dem neuen Aufwand neu
gebildet.

Der Vergleich erfolgt mit ``hmac.compare_digest``, also in konstanter Zeit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import NUTZER_DB_PFAD, PBKDF2_ITERATIONEN, datenverzeichnis_anlegen

# Schemaname, unter dem die Nutzerdatenbank an die Warehouse-Verbindung gehaengt
# wird. Er steht in jeder Abfrage und macht damit im Quelltext sichtbar, wann
# eigene Daten im Spiel sind.
SCHEMA = "nutzer"

ROLLEN = ("verwaltung", "spieler")

NUTZER_DDL = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.Nutzer (
    nutzer_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    benutzername     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    anzeigename      TEXT    NOT NULL,
    passwort_hash    TEXT    NOT NULL,       -- hexadezimal
    salz             TEXT    NOT NULL,       -- hexadezimal, je Konto eigen
    verfahren        TEXT    NOT NULL DEFAULT 'pbkdf2_sha256',
    iterationen      INTEGER NOT NULL,
    rolle            TEXT    NOT NULL DEFAULT 'spieler',
    angelegt_am      TEXT    NOT NULL,
    letzte_anmeldung TEXT,
    ist_aktiv        INTEGER NOT NULL DEFAULT 1
);

-- Eintraege des PC-Systems: ein abgelegtes Pokemon samt Konfiguration.
--
-- Die Statuspunkte folgen den Regeln von Pokemon Champions (hoechstens 32 je
-- Wert, 66 insgesamt) und nicht der Fleisspunkte-Rechnung der Hauptreihe. Die
-- Attacken stehen als kompakte Schluessel und werden beim Lesen gegen
-- ``Dim_Attacke`` aufgeloest.
CREATE TABLE IF NOT EXISTS {SCHEMA}.Box_Pokemon (
    box_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nutzer_id         INTEGER NOT NULL REFERENCES Nutzer (nutzer_id) ON DELETE CASCADE,
    slug              TEXT    NOT NULL,      -- natuerlicher Schluessel zu Dim_Pokemon
    spitzname         TEXT,
    item_slug         TEXT,                  -- natuerlicher Schluessel zu Dim_Item
    faehigkeit_slug   TEXT,                  -- natuerlicher Schluessel zu Dim_Faehigkeit
    wesen             TEXT    NOT NULL DEFAULT 'Hardy',
    punkte_hp         INTEGER NOT NULL DEFAULT 0,
    punkte_attack     INTEGER NOT NULL DEFAULT 0,
    punkte_defense    INTEGER NOT NULL DEFAULT 0,
    punkte_sp_attack  INTEGER NOT NULL DEFAULT 0,
    punkte_sp_defense INTEGER NOT NULL DEFAULT 0,
    punkte_speed      INTEGER NOT NULL DEFAULT 0,
    attacken          TEXT    NOT NULL DEFAULT '[]',   -- JSON-Liste kompakter Schluessel
    notiz             TEXT,
    angelegt_am       TEXT    NOT NULL,
    geaendert_am      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS {SCHEMA}.ix_box_nutzer ON Box_Pokemon (nutzer_id, slug);

CREATE TABLE IF NOT EXISTS {SCHEMA}.Team (
    team_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nutzer_id    INTEGER NOT NULL REFERENCES Nutzer (nutzer_id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    kampfformat  TEXT    NOT NULL DEFAULT 'Doubles',
    notiz        TEXT,
    angelegt_am  TEXT    NOT NULL,
    geaendert_am TEXT    NOT NULL,
    UNIQUE (nutzer_id, name)
);

-- Zuordnung Team zu Box-Eintrag. Ein Pokemon kann in mehreren Teams stehen,
-- ohne mehrfach erfasst zu werden -- deshalb eine eigene Tabelle und keine
-- sechs Spalten im Team.
CREATE TABLE IF NOT EXISTS {SCHEMA}.Team_Mitglied (
    team_id  INTEGER NOT NULL REFERENCES Team (team_id) ON DELETE CASCADE,
    box_id   INTEGER NOT NULL REFERENCES Box_Pokemon (box_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY (team_id, box_id)
);

-- Anmeldeprotokoll. Kein Berichtswesen, sondern Betriebssicherheit: eine
-- Haeufung fehlgeschlagener Versuche ist ohne Protokoll nicht erkennbar.
CREATE TABLE IF NOT EXISTS {SCHEMA}.Anmeldeprotokoll (
    eintrag_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    benutzername TEXT NOT NULL,
    erfolgreich  INTEGER NOT NULL,
    zeitpunkt    TEXT NOT NULL,
    hinweis      TEXT
);

-- Einstellungen des Betriebs, etwa ob eine Selbstregistrierung offen ist.
CREATE TABLE IF NOT EXISTS {SCHEMA}.Einstellung (
    schluessel TEXT PRIMARY KEY,
    wert       TEXT NOT NULL
);
"""


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Verbindung
# --------------------------------------------------------------------------

def anhaengen(conn: sqlite3.Connection, pfad: Path | str | None = None) -> None:
    """Haengt die Nutzerdatenbank an eine bestehende Verbindung und legt sie an.

    Gefahrlos wiederholbar: ist das Schema bereits angehaengt, geschieht
    nichts. Damit kann der Aufruf im Verbindungsaufbau stehen.
    """
    if any(z[1] == SCHEMA for z in conn.execute("PRAGMA database_list")):
        return

    ziel = Path(pfad) if pfad else NUTZER_DB_PFAD
    if str(ziel) != ":memory:":
        datenverzeichnis_anlegen()
        ziel.parent.mkdir(parents=True, exist_ok=True)

    conn.execute("ATTACH DATABASE ? AS " + SCHEMA, (str(ziel),))
    conn.executescript(NUTZER_DDL)
    conn.commit()


# --------------------------------------------------------------------------
# Passwoerter
# --------------------------------------------------------------------------

def _hash(passwort: str, salz: str, iterationen: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", passwort.encode("utf-8"), bytes.fromhex(salz), iterationen).hex()


def passwort_regeln(passwort: str) -> list[str]:
    """Prueft ein Passwort gegen die Mindestanforderungen.

    Bewusst schlicht: Laenge schlaegt Zeichenklassen. Erzwungene Sonderzeichen
    fuehren erfahrungsgemaess zu kuerzeren, schlechter merkbaren Passwoertern --
    die Empfehlungen des BSI und des NIST gehen deshalb denselben Weg.
    """
    verstoesse = []
    if len(passwort) < 10:
        verstoesse.append("Das Passwort muss mindestens 10 Zeichen lang sein.")
    if passwort.strip() != passwort:
        verstoesse.append("Das Passwort darf nicht mit einem Leerzeichen beginnen oder enden.")
    if passwort.lower() in {"passwort12", "passwort123", "1234567890", "pokemon123"}:
        verstoesse.append("Dieses Passwort ist zu gebraeuchlich.")
    return verstoesse


@dataclass(frozen=True)
class Nutzer:
    """Ein angemeldeter Nutzer."""

    nutzer_id: int
    benutzername: str
    anzeigename: str
    rolle: str

    @property
    def ist_verwaltung(self) -> bool:
        return self.rolle == "verwaltung"


def anzahl_nutzer(conn: sqlite3.Connection) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {SCHEMA}.Nutzer").fetchone()[0])


def anlegen(conn: sqlite3.Connection, benutzername: str, passwort: str,
            anzeigename: str | None = None, rolle: str | None = None) -> Nutzer:
    """Legt ein Konto an.

    Das **erste** Konto erhaelt die Rolle *verwaltung*: irgendjemand muss die
    Einrichtung vornehmen koennen, und ein fest verdrahtetes Startpasswort
    waere die schlechtere Loesung.
    """
    benutzername = benutzername.strip()
    if not benutzername:
        raise ValueError("Der Benutzername darf nicht leer sein.")
    if len(benutzername) > 40:
        raise ValueError("Der Benutzername ist zu lang (hoechstens 40 Zeichen).")

    verstoesse = passwort_regeln(passwort)
    if verstoesse:
        raise ValueError(" ".join(verstoesse))

    if conn.execute(f"SELECT 1 FROM {SCHEMA}.Nutzer WHERE benutzername = ?",
                    (benutzername,)).fetchone():
        raise ValueError("Dieser Benutzername ist bereits vergeben.")

    salz = secrets.token_bytes(16).hex()
    rolle = rolle or ("verwaltung" if anzahl_nutzer(conn) == 0 else "spieler")
    if rolle not in ROLLEN:
        raise ValueError(f"Unbekannte Rolle: {rolle}")

    cursor = conn.execute(
        f"""INSERT INTO {SCHEMA}.Nutzer
                (benutzername, anzeigename, passwort_hash, salz, iterationen,
                 rolle, angelegt_am)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (benutzername, (anzeigename or benutzername).strip(),
         _hash(passwort, salz, PBKDF2_ITERATIONEN), salz, PBKDF2_ITERATIONEN,
         rolle, _jetzt()),
    )
    conn.commit()
    return Nutzer(int(cursor.lastrowid), benutzername, anzeigename or benutzername, rolle)


def anmelden(conn: sqlite3.Connection, benutzername: str, passwort: str) -> Nutzer | None:
    """Prueft die Zugangsdaten und liefert den Nutzer oder ``None``.

    Bei unbekanntem Benutzernamen wird trotzdem ein Hash gerechnet. Ohne diesen
    Leerlauf waere an der Antwortzeit ablesbar, welche Benutzernamen existieren.
    """
    zeile = conn.execute(
        f"""SELECT nutzer_id, benutzername, anzeigename, passwort_hash, salz,
                   iterationen, rolle, ist_aktiv
            FROM {SCHEMA}.Nutzer WHERE benutzername = ?""",
        (benutzername.strip(),)).fetchone()

    if zeile is None:
        _hash(passwort, secrets.token_bytes(16).hex(), PBKDF2_ITERATIONEN)
        _protokolliere(conn, benutzername, False, "Unbekannter Benutzername")
        return None

    stimmt = hmac.compare_digest(
        _hash(passwort, zeile["salz"], int(zeile["iterationen"])), zeile["passwort_hash"])
    if not stimmt:
        _protokolliere(conn, benutzername, False, "Falsches Passwort")
        return None
    if not zeile["ist_aktiv"]:
        _protokolliere(conn, benutzername, False, "Konto ist gesperrt")
        return None

    # Aufwand nachziehen, falls die Iterationszahl inzwischen angehoben wurde.
    if int(zeile["iterationen"]) < PBKDF2_ITERATIONEN:
        salz = secrets.token_bytes(16).hex()
        conn.execute(
            f"""UPDATE {SCHEMA}.Nutzer
                   SET passwort_hash = ?, salz = ?, iterationen = ?
                 WHERE nutzer_id = ?""",
            (_hash(passwort, salz, PBKDF2_ITERATIONEN), salz, PBKDF2_ITERATIONEN,
             zeile["nutzer_id"]))

    conn.execute(f"UPDATE {SCHEMA}.Nutzer SET letzte_anmeldung = ? WHERE nutzer_id = ?",
                 (_jetzt(), zeile["nutzer_id"]))
    _protokolliere(conn, benutzername, True, None)
    conn.commit()
    return Nutzer(int(zeile["nutzer_id"]), zeile["benutzername"],
                  zeile["anzeigename"], zeile["rolle"])


def passwort_aendern(conn: sqlite3.Connection, nutzer_id: int, altes: str,
                     neues: str) -> None:
    """Aendert ein Passwort nach Pruefung des bisherigen."""
    zeile = conn.execute(
        f"SELECT benutzername, passwort_hash, salz, iterationen FROM {SCHEMA}.Nutzer "
        f"WHERE nutzer_id = ?", (nutzer_id,)).fetchone()
    if zeile is None:
        raise ValueError("Konto nicht gefunden.")
    if not hmac.compare_digest(
            _hash(altes, zeile["salz"], int(zeile["iterationen"])), zeile["passwort_hash"]):
        raise ValueError("Das bisherige Passwort stimmt nicht.")

    verstoesse = passwort_regeln(neues)
    if verstoesse:
        raise ValueError(" ".join(verstoesse))

    salz = secrets.token_bytes(16).hex()
    conn.execute(
        f"UPDATE {SCHEMA}.Nutzer SET passwort_hash = ?, salz = ?, iterationen = ? "
        f"WHERE nutzer_id = ?",
        (_hash(neues, salz, PBKDF2_ITERATIONEN), salz, PBKDF2_ITERATIONEN, nutzer_id))
    conn.commit()


def _protokolliere(conn: sqlite3.Connection, benutzername: str, erfolgreich: bool,
                   hinweis: str | None) -> None:
    conn.execute(
        f"""INSERT INTO {SCHEMA}.Anmeldeprotokoll
                (benutzername, erfolgreich, zeitpunkt, hinweis) VALUES (?, ?, ?, ?)""",
        (benutzername[:40], int(erfolgreich), _jetzt(), hinweis))
    conn.commit()


def fehlversuche_seit(conn: sqlite3.Connection, benutzername: str,
                      zeitpunkt: str) -> int:
    """Fehlversuche eines Kontos seit einem Zeitpunkt -- Grundlage der Sperre."""
    return int(conn.execute(
        f"""SELECT COUNT(*) FROM {SCHEMA}.Anmeldeprotokoll
             WHERE benutzername = ? AND erfolgreich = 0 AND zeitpunkt >= ?""",
        (benutzername.strip(), zeitpunkt)).fetchone()[0])


# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------

def einstellung(conn: sqlite3.Connection, schluessel: str, standard: str = "") -> str:
    zeile = conn.execute(
        f"SELECT wert FROM {SCHEMA}.Einstellung WHERE schluessel = ?",
        (schluessel,)).fetchone()
    return zeile["wert"] if zeile else standard


def setze_einstellung(conn: sqlite3.Connection, schluessel: str, wert: str) -> None:
    conn.execute(
        f"""INSERT INTO {SCHEMA}.Einstellung (schluessel, wert) VALUES (?, ?)
            ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert""",
        (schluessel, wert))
    conn.commit()


# --------------------------------------------------------------------------
# PC-System
# --------------------------------------------------------------------------

BOX_FELDER = (
    "slug", "spitzname", "item_slug", "faehigkeit_slug", "wesen",
    "punkte_hp", "punkte_attack", "punkte_defense",
    "punkte_sp_attack", "punkte_sp_defense", "punkte_speed",
    "attacken", "notiz",
)


def box_speichern(conn: sqlite3.Connection, nutzer_id: int, satz: dict[str, Any],
                  box_id: int | None = None) -> int:
    """Legt einen Box-Eintrag an oder aktualisiert ihn.

    Die Attackenliste wird als JSON abgelegt. Eine eigene Tabelle waere sauberer
    normalisiert, brächte aber nichts: die Zahl der Attacken ist durch die
    Spielregeln auf vier festgelegt, und ausgewertet wird die Liste stets als
    Ganzes.
    """
    werte = {feld: satz.get(feld) for feld in BOX_FELDER}
    if not werte["slug"]:
        raise ValueError("Ohne Pokemon kein Box-Eintrag.")
    if isinstance(werte["attacken"], (list, tuple)):
        werte["attacken"] = json.dumps(list(werte["attacken"])[:4])
    werte["attacken"] = werte["attacken"] or "[]"
    werte["wesen"] = werte["wesen"] or "Hardy"
    for feld in BOX_FELDER:
        if feld.startswith("punkte_"):
            werte[feld] = int(werte[feld] or 0)

    jetzt = _jetzt()
    if box_id is None:
        spalten = ", ".join(BOX_FELDER)
        platzhalter = ", ".join("?" * len(BOX_FELDER))
        cursor = conn.execute(
            f"""INSERT INTO {SCHEMA}.Box_Pokemon
                    (nutzer_id, {spalten}, angelegt_am, geaendert_am)
                VALUES (?, {platzhalter}, ?, ?)""",
            (nutzer_id, *(werte[f] for f in BOX_FELDER), jetzt, jetzt))
        conn.commit()
        return int(cursor.lastrowid)

    zuweisung = ", ".join(f"{f} = ?" for f in BOX_FELDER)
    conn.execute(
        f"""UPDATE {SCHEMA}.Box_Pokemon SET {zuweisung}, geaendert_am = ?
             WHERE box_id = ? AND nutzer_id = ?""",
        (*(werte[f] for f in BOX_FELDER), jetzt, box_id, nutzer_id))
    conn.commit()
    return box_id


def box_lesen(conn: sqlite3.Connection, nutzer_id: int) -> list[dict[str, Any]]:
    """Liest das PC-System eines Nutzers, angereichert aus den Stammdaten.

    Der Verbund laeuft ueber den natuerlichen Schluessel und ueber Schemagrenzen
    hinweg -- genau der Fall, fuer den die Nutzerdatenbank angehaengt wird.
    Fehlt ein Pokemon in der Dimension (etwa weil das Warehouse noch leer ist),
    bleibt der Eintrag erhalten; nur die Anreicherung fehlt.
    """
    zeilen = conn.execute(f"""
        SELECT b.*, p.anzeigename, p.pokedex_id, p.typ1, p.typ2, p.generation,
               p.hp, p.attack, p.defense, p.sp_attack, p.sp_defense, p.speed,
               p.basiswert_summe, p.rolle AS pokemon_rolle,
               i.anzeigename AS item_name, i.wirkung_klasse AS item_klasse,
               f.anzeigename AS faehigkeit_name, f.wirkung_klasse AS faehigkeit_klasse
          FROM {SCHEMA}.Box_Pokemon b
          LEFT JOIN Dim_Pokemon    p ON p.slug = b.slug AND p.ist_aktuell = 1
          LEFT JOIN Dim_Item       i ON i.slug = b.item_slug
          LEFT JOIN Dim_Faehigkeit f ON f.slug = b.faehigkeit_slug
         WHERE b.nutzer_id = ?
         ORDER BY b.box_id
    """, (nutzer_id,)).fetchall()

    saetze = []
    for zeile in zeilen:
        satz = dict(zeile)
        try:
            satz["attacken"] = json.loads(satz.get("attacken") or "[]")
        except json.JSONDecodeError:
            satz["attacken"] = []
        saetze.append(satz)
    return saetze


def box_loeschen(conn: sqlite3.Connection, nutzer_id: int, box_id: int) -> None:
    """Entfernt einen Box-Eintrag samt seiner Teamzuordnungen."""
    conn.execute(f"DELETE FROM {SCHEMA}.Team_Mitglied WHERE box_id = ?", (box_id,))
    conn.execute(f"DELETE FROM {SCHEMA}.Box_Pokemon WHERE box_id = ? AND nutzer_id = ?",
                 (box_id, nutzer_id))
    conn.commit()


# --------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------

def team_speichern(conn: sqlite3.Connection, nutzer_id: int, name: str,
                   box_ids: list[int], kampfformat: str = "Doubles",
                   notiz: str | None = None, team_id: int | None = None) -> int:
    """Legt ein Team an oder aktualisiert es.

    Ein Team fasst hoechstens sechs Box-Eintraege zusammen -- die Zahl, die im
    Turnier mitgebracht wird. Welche vier davon im Team-Preview mitgehen,
    entscheidet der Preview-Advisor.
    """
    if not name.strip():
        raise ValueError("Das Team braucht einen Namen.")
    if len(box_ids) > 6:
        raise ValueError("Ein Team umfasst hoechstens sechs Pokemon.")

    jetzt = _jetzt()
    if team_id is None:
        cursor = conn.execute(
            f"""INSERT INTO {SCHEMA}.Team
                    (nutzer_id, name, kampfformat, notiz, angelegt_am, geaendert_am)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (nutzer_id, name.strip(), kampfformat, notiz, jetzt, jetzt))
        team_id = int(cursor.lastrowid)
    else:
        conn.execute(
            f"""UPDATE {SCHEMA}.Team SET name = ?, kampfformat = ?, notiz = ?,
                       geaendert_am = ?
                 WHERE team_id = ? AND nutzer_id = ?""",
            (name.strip(), kampfformat, notiz, jetzt, team_id, nutzer_id))
        conn.execute(f"DELETE FROM {SCHEMA}.Team_Mitglied WHERE team_id = ?", (team_id,))

    conn.executemany(
        f"INSERT INTO {SCHEMA}.Team_Mitglied (team_id, box_id, position) VALUES (?, ?, ?)",
        [(team_id, box_id, position) for position, box_id in enumerate(box_ids, start=1)])
    conn.commit()
    return team_id


def teams_lesen(conn: sqlite3.Connection, nutzer_id: int) -> list[dict[str, Any]]:
    """Liest die Teams eines Nutzers samt ihrer Mitglieder."""
    teams = [dict(z) for z in conn.execute(
        f"SELECT * FROM {SCHEMA}.Team WHERE nutzer_id = ? ORDER BY name", (nutzer_id,))]
    for team in teams:
        team["mitglieder"] = [dict(z) for z in conn.execute(f"""
            SELECT m.position, b.box_id, b.slug, b.spitzname, b.item_slug,
                   p.anzeigename, p.pokedex_id, p.typ1, p.typ2
              FROM {SCHEMA}.Team_Mitglied m
              JOIN {SCHEMA}.Box_Pokemon b ON b.box_id = m.box_id
              LEFT JOIN Dim_Pokemon p ON p.slug = b.slug AND p.ist_aktuell = 1
             WHERE m.team_id = ?
             ORDER BY m.position
        """, (team["team_id"],))]
    return teams


def team_loeschen(conn: sqlite3.Connection, nutzer_id: int, team_id: int) -> None:
    conn.execute(f"DELETE FROM {SCHEMA}.Team_Mitglied WHERE team_id = ?", (team_id,))
    conn.execute(f"DELETE FROM {SCHEMA}.Team WHERE team_id = ? AND nutzer_id = ?",
                 (team_id, nutzer_id))
    conn.commit()


def bestand(conn: sqlite3.Connection) -> dict[str, int]:
    """Umfang der eigenen Datenhaltung -- fuer die Betriebsuebersicht."""
    def zaehle(tabelle: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{tabelle}").fetchone()[0])

    return {
        "nutzer": zaehle("Nutzer"),
        "box_eintraege": zaehle("Box_Pokemon"),
        "teams": zaehle("Team"),
        "anmeldungen": zaehle("Anmeldeprotokoll"),
    }

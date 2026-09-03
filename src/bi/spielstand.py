"""Spielstaende der Hauptspiele: Durchspielen und Nuzlocke.

Ein **Lauf** ist ein Durchgang durch eine Edition -- mit Orden, einem Team
und allem, was unterwegs begegnet ist. Ein Nuzlocke-Lauf ist derselbe Lauf
unter drei zusaetzlichen Regeln, die die Gemeinde seit 2010 so spielt:

1. Je Ort zaehlt nur die **erste Begegnung**. Entkommt sie oder wird sie
   besiegt, bleibt der Ort leer.
2. Ein besiegtes Pokemon gilt als **tot** und wird nicht mehr eingesetzt.
3. Jedes gefangene Pokemon bekommt einen **Spitznamen**.

Die Regeln liegen nicht im Code verteilt, sondern als Liste am Lauf: ein
Lauf behaelt die Regeln, unter denen er begonnen wurde. Geprueft wird nur die
erste -- sie ist die einzige, die sich aus den Daten pruefen laesst. Die
zweite ist ein Status, den der Spieler setzt; die dritte eine Erinnerung.

Die Auswertung eines Laufs bleibt bei Zaehlungen (Begegnungen, Verluste,
Orden) und bei der Typenlehre aus :mod:`bi.typechart`: welche Angriffstypen
das Team gemeinsam verwundbar machen. Genau das ist die Frage vor jedem
Arenaleiter -- und sie braucht keine Ranked-Daten.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from .config import ALLE_TYPEN
from .nutzerdaten import SCHEMA, _jetzt
from .typechart import defensivprofil

ARTEN = ("normal", "nuzlocke")

# Bezeichnungen fuer die Oberflaeche.
ART_NAME = {"normal": "Durchspielen", "nuzlocke": "Nuzlocke"}

STATUS = ("team", "box", "tot", "entkommen", "besiegt")
STATUS_NAME = {
    "team": "Im Team", "box": "In der Box", "tot": "Gefallen",
    "entkommen": "Entkommen", "besiegt": "Besiegt (nicht gefangen)",
}
# Was als "gefangen" zaehlt: alles, was jemals in Team oder Box lag.
GEFANGEN = ("team", "box", "tot")

LAUF_STATUS = ("laeuft", "abgeschlossen", "gescheitert")

TEAMGROESSE = 6

# Regeln des Nuzlocke, mit Schluessel fuer die Ablage am Lauf.
NUZLOCKE_REGELN: dict[str, str] = {
    "erste_begegnung": "Je Ort zaehlt nur die erste Begegnung.",
    "tod": "Ein besiegtes Pokemon gilt als gefallen und wird nicht mehr eingesetzt.",
    "spitzname": "Jedes gefangene Pokemon bekommt einen Spitznamen.",
}

# Editionen der Hauptspiele, je Generation. Bewusst eine Auswahlliste und
# kein Freitext: sonst stuenden "Platin", "platin" und "Pokemon Platin"
# nebeneinander, und keine Auswertung koennte sie zusammenfassen.
EDITIONEN: dict[int, tuple[str, ...]] = {
    1: ("Rot", "Blau", "Gelb"),
    2: ("Gold", "Silber", "Kristall"),
    3: ("Rubin", "Saphir", "Smaragd", "Feuerrot", "Blattgruen"),
    4: ("Diamant", "Perl", "Platin", "HeartGold", "SoulSilver"),
    5: ("Schwarz", "Weiss", "Schwarz 2", "Weiss 2"),
    6: ("X", "Y", "Omega Rubin", "Alpha Saphir"),
    7: ("Sonne", "Mond", "Ultrasonne", "Ultramond", "Let's Go Pikachu", "Let's Go Evoli"),
    8: ("Schwert", "Schild", "Strahlender Diamant", "Leuchtende Perle", "Legenden: Arceus"),
    9: ("Karmesin", "Purpur", "Legenden: Z-A"),
}

ALLE_EDITIONEN = tuple(e for editionen in EDITIONEN.values() for e in editionen)


# --------------------------------------------------------------------------
# Laeufe
# --------------------------------------------------------------------------

def lauf_anlegen(conn: sqlite3.Connection, nutzer_id: int, name: str, spiel: str,
                 art: str = "normal", regeln: list[str] | None = None,
                 notiz: str | None = None) -> int:
    if not name.strip():
        raise ValueError("Der Lauf braucht einen Namen.")
    if art not in ARTEN:
        raise ValueError(f"Unbekannte Art: {art}")
    if spiel not in ALLE_EDITIONEN:
        raise ValueError(f"Unbekannte Edition: {spiel}")
    if regeln is None:
        regeln = list(NUZLOCKE_REGELN) if art == "nuzlocke" else []
    unbekannt = [r for r in regeln if r not in NUZLOCKE_REGELN]
    if unbekannt:
        raise ValueError(f"Unbekannte Regel: {', '.join(unbekannt)}")
    if conn.execute(f"SELECT 1 FROM {SCHEMA}.Spielstand_Lauf WHERE nutzer_id = ? AND name = ?",
                    (nutzer_id, name.strip())).fetchone():
        raise ValueError("Ein Lauf mit diesem Namen existiert bereits.")

    jetzt = _jetzt()
    cursor = conn.execute(
        f"""INSERT INTO {SCHEMA}.Spielstand_Lauf
                (nutzer_id, name, spiel, art, regeln, notiz, angelegt_am, geaendert_am)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (nutzer_id, name.strip(), spiel, art, json.dumps(regeln), notiz, jetzt, jetzt))
    conn.commit()
    return int(cursor.lastrowid)


def laeufe_lesen(conn: sqlite3.Connection, nutzer_id: int,
                 art: str | None = None) -> list[dict[str, Any]]:
    """Alle Laeufe eines Nutzers, laufende zuerst."""
    sql = f"SELECT * FROM {SCHEMA}.Spielstand_Lauf WHERE nutzer_id = ?"
    parameter: list[Any] = [nutzer_id]
    if art:
        sql += " AND art = ?"
        parameter.append(art)
    sql += " ORDER BY CASE status WHEN 'laeuft' THEN 0 ELSE 1 END, geaendert_am DESC"
    laeufe = []
    for zeile in conn.execute(sql, parameter):
        lauf = dict(zeile)
        try:
            lauf["regeln"] = json.loads(lauf.get("regeln") or "[]")
        except json.JSONDecodeError:
            lauf["regeln"] = []
        laeufe.append(lauf)
    return laeufe


def lauf_aktualisieren(conn: sqlite3.Connection, nutzer_id: int, lauf_id: int,
                       orden: int | None = None, status: str | None = None,
                       notiz: str | None = None) -> None:
    if status is not None and status not in LAUF_STATUS:
        raise ValueError(f"Unbekannter Status: {status}")
    if orden is not None and not 0 <= orden <= 16:
        raise ValueError("Orden liegen zwischen 0 und 16.")
    zuweisungen, werte = ["geaendert_am = ?"], [_jetzt()]
    if orden is not None:
        zuweisungen.append("orden = ?")
        werte.append(int(orden))
    if status is not None:
        zuweisungen.append("status = ?")
        werte.append(status)
    if notiz is not None:
        zuweisungen.append("notiz = ?")
        werte.append(notiz)
    conn.execute(
        f"UPDATE {SCHEMA}.Spielstand_Lauf SET {', '.join(zuweisungen)} "
        f"WHERE lauf_id = ? AND nutzer_id = ?", (*werte, lauf_id, nutzer_id))
    conn.commit()


def lauf_loeschen(conn: sqlite3.Connection, nutzer_id: int, lauf_id: int) -> None:
    if not _gehoert(conn, nutzer_id, lauf_id):
        return
    conn.execute(f"DELETE FROM {SCHEMA}.Spielstand_Begegnung WHERE lauf_id = ?", (lauf_id,))
    conn.execute(f"DELETE FROM {SCHEMA}.Spielstand_Lauf WHERE lauf_id = ?", (lauf_id,))
    conn.commit()


def _gehoert(conn: sqlite3.Connection, nutzer_id: int, lauf_id: int) -> dict[str, Any] | None:
    zeile = conn.execute(
        f"SELECT * FROM {SCHEMA}.Spielstand_Lauf WHERE lauf_id = ? AND nutzer_id = ?",
        (lauf_id, nutzer_id)).fetchone()
    return dict(zeile) if zeile else None


# --------------------------------------------------------------------------
# Begegnungen
# --------------------------------------------------------------------------

def begegnung_speichern(conn: sqlite3.Connection, nutzer_id: int, lauf_id: int,
                        ort: str, slug: str, status: str = "team",
                        spitzname: str | None = None, stufe: int | None = None,
                        notiz: str | None = None) -> int:
    """Traegt eine Begegnung ein und prueft die Regeln des Laufs.

    Die Eindeutigkeit je Ort ist eine Regel des Nuzlocke und keine der
    Tabelle: in einem gewoehnlichen Durchgang darf dieselbe Route beliebig oft
    vorkommen.
    """
    lauf = _gehoert(conn, nutzer_id, lauf_id)
    if lauf is None:
        raise ValueError("Lauf nicht gefunden.")
    if not ort.strip():
        raise ValueError("Die Begegnung braucht einen Ort.")
    if not slug:
        raise ValueError("Die Begegnung braucht ein Pokemon.")
    if status not in STATUS:
        raise ValueError(f"Unbekannter Status: {status}")

    regeln = json.loads(lauf.get("regeln") or "[]")
    if "erste_begegnung" in regeln and conn.execute(
            f"SELECT 1 FROM {SCHEMA}.Spielstand_Begegnung WHERE lauf_id = ? AND ort = ?",
            (lauf_id, ort.strip())).fetchone():
        raise ValueError(
            f"Nuzlocke-Regel: an '{ort.strip()}' gab es schon eine Begegnung -- "
            "nur die erste zaehlt.")
    if "spitzname" in regeln and status in GEFANGEN and not (spitzname or "").strip():
        raise ValueError("Nuzlocke-Regel: ein gefangenes Pokemon bekommt einen Spitznamen.")
    if status == "team":
        _pruefe_teamgroesse(conn, lauf_id)

    jetzt = _jetzt()
    naechste = conn.execute(
        f"SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM {SCHEMA}.Spielstand_Begegnung "
        f"WHERE lauf_id = ?", (lauf_id,)).fetchone()[0]
    cursor = conn.execute(
        f"""INSERT INTO {SCHEMA}.Spielstand_Begegnung
                (lauf_id, ort, slug, spitzname, stufe, status, reihenfolge, notiz,
                 angelegt_am, geaendert_am)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (lauf_id, ort.strip(), slug, (spitzname or "").strip() or None,
         int(stufe) if stufe else None, status, int(naechste), notiz, jetzt, jetzt))
    conn.execute(f"UPDATE {SCHEMA}.Spielstand_Lauf SET geaendert_am = ? WHERE lauf_id = ?",
                 (jetzt, lauf_id))
    conn.commit()
    return int(cursor.lastrowid)


def _pruefe_teamgroesse(conn: sqlite3.Connection, lauf_id: int,
                        ausser: int | None = None) -> None:
    sql = (f"SELECT COUNT(*) FROM {SCHEMA}.Spielstand_Begegnung "
           f"WHERE lauf_id = ? AND status = 'team'")
    parameter: list[Any] = [lauf_id]
    if ausser is not None:
        sql += " AND begegnung_id <> ?"
        parameter.append(ausser)
    if int(conn.execute(sql, parameter).fetchone()[0]) >= TEAMGROESSE:
        raise ValueError(f"Das Team ist voll ({TEAMGROESSE} Pokemon). Erst eines in die Box.")


def begegnung_status_setzen(conn: sqlite3.Connection, nutzer_id: int, begegnung_id: int,
                            status: str) -> None:
    """Wechselt den Status -- Team, Box oder gefallen.

    Ein gefallenes Pokemon kommt in einem Nuzlocke nicht zurueck: der Wechsel
    von ``tot`` zu etwas anderem wird dort verweigert.
    """
    if status not in STATUS:
        raise ValueError(f"Unbekannter Status: {status}")
    zeile = conn.execute(f"""
        SELECT b.begegnung_id, b.lauf_id, b.status, l.regeln
          FROM {SCHEMA}.Spielstand_Begegnung b
          JOIN {SCHEMA}.Spielstand_Lauf l ON l.lauf_id = b.lauf_id
         WHERE b.begegnung_id = ? AND l.nutzer_id = ?""", (begegnung_id, nutzer_id)).fetchone()
    if zeile is None:
        raise ValueError("Begegnung nicht gefunden.")
    regeln = json.loads(zeile["regeln"] or "[]")
    if zeile["status"] == "tot" and "tod" in regeln and status != "tot":
        raise ValueError("Nuzlocke-Regel: ein gefallenes Pokemon kehrt nicht zurueck.")
    if status == "team":
        _pruefe_teamgroesse(conn, int(zeile["lauf_id"]), ausser=begegnung_id)
    jetzt = _jetzt()
    conn.execute(
        f"UPDATE {SCHEMA}.Spielstand_Begegnung SET status = ?, geaendert_am = ? "
        f"WHERE begegnung_id = ?", (status, jetzt, begegnung_id))
    conn.execute(f"UPDATE {SCHEMA}.Spielstand_Lauf SET geaendert_am = ? WHERE lauf_id = ?",
                 (jetzt, zeile["lauf_id"]))
    conn.commit()


def begegnung_loeschen(conn: sqlite3.Connection, nutzer_id: int, begegnung_id: int) -> None:
    conn.execute(f"""
        DELETE FROM {SCHEMA}.Spielstand_Begegnung
         WHERE begegnung_id = ?
           AND lauf_id IN (SELECT lauf_id FROM {SCHEMA}.Spielstand_Lauf WHERE nutzer_id = ?)
    """, (begegnung_id, nutzer_id))
    conn.commit()


def begegnungen_lesen(conn: sqlite3.Connection, nutzer_id: int,
                      lauf_id: int) -> list[dict[str, Any]]:
    """Die Begegnungen eines Laufs in Reihenfolge, angereichert aus den Stammdaten."""
    zeilen = conn.execute(f"""
        SELECT b.*, p.anzeigename, p.name_de, p.pokedex_id, p.typ1, p.typ2,
               p.basiswert_summe
          FROM {SCHEMA}.Spielstand_Begegnung b
          JOIN {SCHEMA}.Spielstand_Lauf l ON l.lauf_id = b.lauf_id
          LEFT JOIN Dim_Pokemon p ON p.slug = b.slug AND p.ist_aktuell = 1
         WHERE b.lauf_id = ? AND l.nutzer_id = ?
         ORDER BY b.reihenfolge
    """, (lauf_id, nutzer_id)).fetchall()
    return [dict(z) for z in zeilen]


# --------------------------------------------------------------------------
# Auswertung
# --------------------------------------------------------------------------

def bilanz(begegnungen: list[dict[str, Any]]) -> dict[str, int]:
    """Zaehlungen ueber einen Lauf. Alles hier sind Anzahlen -- summierbar."""
    zaehler = Counter(b["status"] for b in begegnungen)
    gefangen = sum(zaehler[s] for s in GEFANGEN)
    return {
        "begegnungen": len(begegnungen),
        "gefangen": gefangen,
        "team": zaehler["team"],
        "box": zaehler["box"],
        "gefallen": zaehler["tot"],
        "verpasst": zaehler["entkommen"] + zaehler["besiegt"],
        "orte": len({b["ort"] for b in begegnungen}),
    }


def team_schwaechen(team: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Welche Angriffstypen das Team gemeinsam treffen -- und wer sie abfaengt.

    Fuer jeden der 18 Typen: wie viele Teammitglieder ihn doppelt nehmen, wie
    viele ihn widerstehen. Ein Typ, der mehr Mitglieder trifft als abgefangen
    wird, ist eine Luecke -- die Frage vor jedem Arenaleiter.
    """
    profile = [defensivprofil(m.get("typ1"), m.get("typ2")) for m in team
               if m.get("typ1")]
    ergebnis = []
    for typ in ALLE_TYPEN:
        schwach = sum(1 for p in profile if p[typ] >= 2)
        widerstand = sum(1 for p in profile if p[typ] < 1)
        ergebnis.append({
            "typ": typ, "schwach": schwach, "widerstand": widerstand,
            "bilanz": widerstand - schwach,
        })
    return sorted(ergebnis, key=lambda e: (e["bilanz"], -e["schwach"]))

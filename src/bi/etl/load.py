"""LOAD -- Ueberfuehrung der transformierten Daten in das Core Data Warehouse.

Zwei grundlegend verschiedene Ladestrategien:

**Dimensionen** werden bi-temporal historisiert. Aendert sich ein fachlich
relevantes Attribut (erkannt ueber ``row_hash``), wird der bisherige Satz zum
Vortag abgegrenzt und ein neuer Satz eroeffnet. Der alte Zustand bleibt erhalten
und bleibt fuer Auswertungen zu einem historischen Stichtag verfuegbar. Damit
sind Balance-Anpassungen zwischen Saisons nachvollziehbar.

**Fakten** werden ausschliesslich eingefuegt beziehungsweise idempotent
aktualisiert. Es wird nichts geloescht: ein erneuter Lauf desselben Tages
ueberschreibt genau die Kennzahlen dieses Tages, alle uebrigen Tage der Zeitreihe
bleiben unberuehrt. Damit ist die Nicht-Volatilitaet nach Inmon gewahrt und der
Ladelauf beliebig wiederholbar.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from ..config import KAMPFFORMATE, MITNAHME, QUELLE_VORHALTUNG_TAGE
from ..stats import STATUSWERTE
from ..warehouse import UNENDLICH
from .transform import Befund, zeitdimension


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Metadaten: ETL-Protokollierung
# --------------------------------------------------------------------------

def lauf_beginnen(conn: sqlite3.Connection, quelle: str, parameter: str) -> int:
    """Legt einen Protokolleintrag an und liefert dessen Lauf-ID."""
    cur = conn.execute(
        "INSERT INTO ETL_Lauf (gestartet_am, quelle, parameter, status) VALUES (?, ?, ?, 'laeuft')",
        (_jetzt(), quelle, parameter),
    )
    conn.commit()
    return int(cur.lastrowid)


def lauf_abschliessen(conn: sqlite3.Connection, lauf_id: int, status: str,
                      gelesen: int = 0, geladen: int = 0, abgewiesen: int = 0,
                      meldung: str | None = None) -> None:
    """Schliesst einen Protokolleintrag ab und berechnet die Laufzeit."""
    start = conn.execute("SELECT gestartet_am FROM ETL_Lauf WHERE lauf_id = ?",
                         (lauf_id,)).fetchone()[0]
    dauer = (datetime.now() - datetime.fromisoformat(start)).total_seconds()
    conn.execute(
        """UPDATE ETL_Lauf
              SET beendet_am = ?, status = ?, zeilen_gelesen = ?, zeilen_geladen = ?,
                  zeilen_abgewiesen = ?, dauer_sekunden = ?, meldung = ?
            WHERE lauf_id = ?""",
        (_jetzt(), status, gelesen, geladen, abgewiesen, round(dauer, 2), meldung, lauf_id),
    )
    conn.commit()


def befunde_protokollieren(conn: sqlite3.Connection, lauf_id: int,
                           befunde: list[Befund]) -> None:
    """Schreibt Datenqualitaetsbefunde in die Metadatenschicht."""
    if not befunde:
        return
    conn.executemany(
        """INSERT INTO DQ_Befund
               (lauf_id, regel, dimension, klasse, schweregrad, entitaet, schluessel,
                meldung, erfasst_am)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (lauf_id, b.regel, b.dimension, b.klasse,
             "Fehler" if b.klasse == "Mangel 1. Klasse" else ("Warnung" if b.verworfen else "Info"),
             b.entitaet, b.schluessel, b.meldung, _jetzt())
            for b in befunde
        ],
    )
    conn.commit()


# --------------------------------------------------------------------------
# Dimensionen
# --------------------------------------------------------------------------

_POKEMON_SPALTEN = (
    "pokedex_id", "slug", "anzeigename", "spezies", "generation", "typ1", "typ2",
    "typ_kombination", *STATUSWERTE,
    *(f"stufe50_{name}" for name in STATUSWERTE),
    "basiswert_summe", "offensiv_profil", "rolle", "speed_klasse", "resistenz_wert",
    "row_hash",
)


def lade_pokemon_dimension(conn: sqlite3.Connection, saetze: list[dict[str, Any]],
                           stichtag: str | None = None) -> dict[str, int]:
    """Laedt ``Dim_Pokemon`` bi-temporal historisiert.

    Rueckgabe: Zaehler ueber ``neu``, ``geaendert`` und ``unveraendert``.
    """
    gueltig_ab = stichtag or date.today().isoformat()
    vortag = (date.fromisoformat(gueltig_ab) - timedelta(days=1)).isoformat()
    jetzt = _jetzt()

    bestand = {
        zeile["slug"]: (zeile["pokemon_sk"], zeile["row_hash"], zeile["gueltig_ab"])
        for zeile in conn.execute(
            "SELECT pokemon_sk, slug, row_hash, gueltig_ab FROM Dim_Pokemon WHERE ist_aktuell = 1"
        )
    }

    zaehler = {"neu": 0, "geaendert": 0, "unveraendert": 0}
    einfuegen: list[tuple[Any, ...]] = []
    abgrenzen: list[tuple[str, int]] = []

    for satz in saetze:
        alt = bestand.get(satz["slug"])

        if alt is None:
            zaehler["neu"] += 1
        elif alt[1] == satz["row_hash"]:
            zaehler["unveraendert"] += 1
            continue
        else:
            # Der bisherige Satz wird zum Vortag abgegrenzt. Faellt die Aenderung
            # auf denselben Tag wie der Beginn seiner Gueltigkeit, wuerde ein leeres
            # Intervall entstehen -- dann wird der Beginn als Ende verwendet.
            abgrenzen.append((max(vortag, alt[2]), alt[0]))
            zaehler["geaendert"] += 1

        einfuegen.append(
            tuple(satz[spalte] for spalte in _POKEMON_SPALTEN)
            + (gueltig_ab, UNENDLICH, 1, jetzt)
        )

    if abgrenzen:
        conn.executemany(
            "UPDATE Dim_Pokemon SET gueltig_bis = ?, ist_aktuell = 0 WHERE pokemon_sk = ?",
            abgrenzen,
        )

    if einfuegen:
        platzhalter = ", ".join("?" * (len(_POKEMON_SPALTEN) + 4))
        spalten = (", ".join(_POKEMON_SPALTEN)
                   + ", gueltig_ab, gueltig_bis, ist_aktuell, dwh_geladen_am")
        conn.executemany(
            f"INSERT OR REPLACE INTO Dim_Pokemon ({spalten}) VALUES ({platzhalter})",  # noqa: S608
            einfuegen,
        )

    conn.commit()
    return zaehler


def _sichere_dimension(conn: sqlite3.Connection, tabelle: str, schluessel_spalte: str,
                       saetze: list[dict[str, Any]]) -> None:
    """Fuegt fehlende Auspraegungen einer einfachen Dimension hinzu (Upsert).

    Diese Dimensionen sind nicht historisiert: ihre Attribute sind Stammdaten ohne
    fachliche Aenderungshistorie im Betrachtungszeitraum.
    """
    if not saetze:
        return
    spalten = list(saetze[0].keys())
    platzhalter = ", ".join("?" * len(spalten))
    weitere = [s for s in spalten if s != schluessel_spalte]
    konflikt = (
        f"DO UPDATE SET {', '.join(f'{s} = excluded.{s}' for s in weitere)}"
        if weitere else "DO NOTHING"
    )
    conn.executemany(
        f"""INSERT INTO {tabelle} ({', '.join(spalten)}) VALUES ({platzhalter})
            ON CONFLICT({schluessel_spalte}) {konflikt}""",  # noqa: S608
        [tuple(satz[s] for s in spalten) for satz in saetze],
    )
    conn.commit()


def lade_zeit(conn: sqlite3.Connection, tage: list[str]) -> dict[str, int]:
    """Legt Tagessaetze an und markiert den juengsten Tag."""
    for satz in (zeitdimension(t) for t in sorted(set(tage))):
        conn.execute(
            """INSERT INTO Dim_Zeit
                   (zeit_sk, datum_iso, jahr, quartal, monat, tag, monat_iso,
                    monat_name, quartal_label, tag_label, wochentag)
               VALUES (:zeit_sk, :datum_iso, :jahr, :quartal, :monat, :tag, :monat_iso,
                       :monat_name, :quartal_label, :tag_label, :wochentag)
               ON CONFLICT(datum_iso) DO NOTHING""",
            satz,
        )

    conn.execute("UPDATE Dim_Zeit SET ist_letzter_tag = 0")
    conn.execute(
        "UPDATE Dim_Zeit SET ist_letzter_tag = 1 "
        "WHERE datum_iso = (SELECT MAX(datum_iso) FROM Dim_Zeit)"
    )
    conn.commit()
    return {z["datum_iso"]: z["zeit_sk"] for z in
            conn.execute("SELECT datum_iso, zeit_sk FROM Dim_Zeit")}


# Eigenschaften des Quellsystems. Sie stehen als Merkmale in der Dimension, damit
# die Auswertung pruefen kann, was die Quelle liefert, statt es fest zu verdrahten.
QUELLEN = {
    "champions": {
        "schluessel": "champions",
        "name": "Pokemon Champions Battle Data",
        "beschreibung": "Taegliche Auswertung der Ranked-Ladder von Pokemon Champions, "
                        "seit April 2026 die offizielle Wettkampfplattform. Liefert die "
                        "Nutzung als Rang, nicht als Quote, und haelt rund zwei Wochen vor.",
        "ist_offiziell": 1,
        "granularitaet_zeit": "Tag",
        "messniveau_nutzung": "ordinal",
        "hat_partner_gewicht": 0,
        "vorhaltung_tage": QUELLE_VORHALTUNG_TAGE,
    },
    "go_pvpoke": {
        "schluessel": "go_pvpoke",
        "name": "pvpoke.com (Pokemon GO PvP)",
        "beschreibung": "Simulationsgestuetzte PvP-Rangliste je Liga. Bewertet jedes "
                        "Pokemon mit einer Punktzahl von 0 bis 100 -- kardinal, im "
                        "Gegensatz zum Rang von Champions. Ueberschreibt den Stand "
                        "bei jeder Balance-Anpassung ohne eigene Historie.",
        "ist_offiziell": 0,
        "granularitaet_zeit": "Stand",
        "messniveau_nutzung": "kardinal",
        "hat_partner_gewicht": 0,
        "vorhaltung_tage": 0,
    },
    "tcg_limitless": {
        "schluessel": "tcg_limitless",
        "name": "Limitless (Pokemon TCG Turniere)",
        "beschreibung": "Turnierstandings des Sammelkartenspiels samt Land des "
                        "Spielers -- die Grundlage des Laendervergleichs. Gezaehlt "
                        "werden Spieler je Deck-Archetyp: kardinale Kennzahlen, "
                        "Summen und Anteile sind zulaessig.",
        "ist_offiziell": 0,
        "granularitaet_zeit": "Turnier",
        "messniveau_nutzung": "kardinal",
        "hat_partner_gewicht": 0,
        "vorhaltung_tage": None,
    },
    "pokeapi": {
        "schluessel": "pokeapi",
        "name": "PokeAPI",
        "beschreibung": "Stammdaten: Typen, Basiswerte und Attackeneigenschaften. "
                        "Ohne Zeitbezug, wird bei Bedarf neu abgezogen.",
        "ist_offiziell": 0,
        "granularitaet_zeit": "-",
        "messniveau_nutzung": "-",
        "hat_partner_gewicht": 0,
        "vorhaltung_tage": None,
    },
}


def lade_quelle(conn: sqlite3.Connection, schluessel: str) -> int:
    """Legt ein Quellsystem an oder liefert dessen Schluessel."""
    satz = QUELLEN[schluessel]
    spalten = ", ".join(satz)
    platzhalter = ", ".join(f":{s}" for s in satz)
    aktualisierung = ", ".join(f"{s} = excluded.{s}" for s in satz if s != "schluessel")
    conn.execute(
        f"""INSERT INTO Dim_Quelle ({spalten}) VALUES ({platzhalter})
            ON CONFLICT(schluessel) DO UPDATE SET {aktualisierung}""",  # noqa: S608
        satz,
    )
    conn.commit()
    return int(conn.execute("SELECT quelle_sk FROM Dim_Quelle WHERE schluessel = ?",
                            (schluessel,)).fetchone()[0])


def lade_kampfformat(conn: sqlite3.Connection, schluessel: str) -> int:
    """Legt ein Kampfformat an oder liefert dessen Schluessel."""
    satz = {
        "schluessel": schluessel,
        "bezeichnung": "Doppelkampf" if schluessel == "Doubles" else "Einzelkampf",
        "aktive_pokemon": 2 if schluessel == "Doubles" else 1,
        "mitnahme": MITNAHME[schluessel],
    }
    conn.execute(
        """INSERT INTO Dim_Kampfformat (schluessel, bezeichnung, aktive_pokemon, mitnahme)
           VALUES (:schluessel, :bezeichnung, :aktive_pokemon, :mitnahme)
           ON CONFLICT(schluessel) DO UPDATE SET bezeichnung = excluded.bezeichnung""",
        satz,
    )
    conn.commit()
    return int(conn.execute("SELECT kampfformat_sk FROM Dim_Kampfformat WHERE schluessel = ?",
                            (schluessel,)).fetchone()[0])


def lade_alle_kampfformate(conn: sqlite3.Connection) -> dict[str, int]:
    """Legt beide Kampfformate an und liefert deren Schluessel."""
    return {f: lade_kampfformat(conn, f) for f in KAMPFFORMATE}


def lade_saison(conn: sqlite3.Connection, schluessel: str, bezeichnung: str,
                quelle_sk: int, beobachtete_tage: list[str]) -> int:
    """Legt eine Saison an und fuehrt ihren beobachteten Zeitraum nach.

    Nur die zuletzt geladene Saison je Quelle gilt als aktuell. Damit lassen sich
    Auswertungen sauber auf den geltenden Regulationszeitraum begrenzen, ohne dass
    Pokemon aus abgelaufenen Saisons hineinwirken.
    """
    beginn = min(beobachtete_tage) if beobachtete_tage else None
    ende = max(beobachtete_tage) if beobachtete_tage else None

    conn.execute(
        """INSERT INTO Dim_Saison
               (schluessel, bezeichnung, quelle_sk, beginn, ende, ist_aktuell, erfasst_am)
           VALUES (?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(schluessel) DO UPDATE SET
               bezeichnung = excluded.bezeichnung,
               -- Der Zeitraum waechst mit jedem Lauf; frueher archivierte Tage
               -- bleiben Teil der Saison, auch wenn die Quelle sie nicht mehr fuehrt.
               beginn = MIN(COALESCE(Dim_Saison.beginn, excluded.beginn), excluded.beginn),
               ende   = MAX(COALESCE(Dim_Saison.ende, excluded.ende), excluded.ende)""",
        (schluessel, bezeichnung, quelle_sk, beginn, ende, _jetzt()),
    )
    # Genau eine Saison je Quelle traegt die Kennzeichnung "aktuell".
    conn.execute("UPDATE Dim_Saison SET ist_aktuell = 0 WHERE quelle_sk = ?", (quelle_sk,))
    conn.execute("UPDATE Dim_Saison SET ist_aktuell = 1 WHERE schluessel = ?", (schluessel,))
    conn.commit()
    return int(conn.execute("SELECT saison_sk FROM Dim_Saison WHERE schluessel = ?",
                            (schluessel,)).fetchone()[0])


def lade_attacken_dimension(conn: sqlite3.Connection, saetze: list[dict[str, Any]]) -> None:
    """Laedt die Attacken-Dimension."""
    _sichere_dimension(conn, "Dim_Attacke", "slug", saetze)


def lade_item_dimension(conn: sqlite3.Connection, saetze: list[dict[str, Any]]) -> None:
    """Laedt die Item-Dimension aus den Stammdaten der Hauptspiele."""
    _sichere_dimension(conn, "Dim_Item", "slug", saetze)


def lade_faehigkeit_dimension(conn: sqlite3.Connection, saetze: list[dict[str, Any]]) -> None:
    """Laedt die Faehigkeiten-Dimension aus den Stammdaten der Hauptspiele."""
    _sichere_dimension(conn, "Dim_Faehigkeit", "slug", saetze)


# Ligen von Pokemon GO. Die Wettkampfpunkte-Grenze ist der Parameter, der die
# Meta trennt: dieselben Pokemon, aber unterschiedlich wertvoll je Grenze.
LIGEN = {
    "great": {"schluessel": "great", "bezeichnung": "Superliga", "wp_grenze": 1500},
    "ultra": {"schluessel": "ultra", "bezeichnung": "Hyperliga", "wp_grenze": 2500},
    "master": {"schluessel": "master", "bezeichnung": "Meisterliga", "wp_grenze": None},
}


def lade_liga(conn: sqlite3.Connection, schluessel: str) -> int:
    """Legt eine Liga an oder liefert ihren Schluessel."""
    satz = LIGEN[schluessel]
    conn.execute(
        """INSERT INTO Dim_Liga (schluessel, bezeichnung, wp_grenze)
           VALUES (:schluessel, :bezeichnung, :wp_grenze)
           ON CONFLICT(schluessel) DO UPDATE SET bezeichnung = excluded.bezeichnung""",
        satz)
    conn.commit()
    return int(conn.execute("SELECT liga_sk FROM Dim_Liga WHERE schluessel = ?",
                            (schluessel,)).fetchone()[0])


# Zuordnung Land -> Region. Die Region ist die Konsolidierungsebene des
# Laendervergleichs: einzelne Laender sind in Turnierdaten oft zu duenn
# besetzt, um eine Verteilung zu tragen. Nicht gelistete Laender fallen in
# 'Uebrige' -- sichtbar, nicht verworfen.
REGIONEN = {
    "Europa": ["DE", "AT", "CH", "FR", "IT", "ES", "PT", "NL", "BE", "GB", "IE",
               "DK", "SE", "NO", "FI", "PL", "CZ", "SK", "HU", "GR", "RO", "BG",
               "HR", "SI", "LT", "LV", "EE", "LU", "MT", "CY", "IS", "UA", "RS"],
    "Nordamerika": ["US", "CA", "MX"],
    "Lateinamerika": ["BR", "AR", "CL", "CO", "PE", "EC", "UY", "PY", "BO", "VE",
                      "CR", "PA", "GT", "SV", "HN", "NI", "DO"],
    "Asien-Pazifik": ["JP", "KR", "TW", "HK", "SG", "MY", "TH", "PH", "ID", "VN",
                      "IN", "CN", "AU", "NZ"],
}

_REGION_JE_LAND = {land: region for region, laender in REGIONEN.items()
                   for land in laender}


def lade_markt(conn: sqlite3.Connection, iso2: str, name: str | None = None) -> int:
    """Legt einen Markt (Land) an oder liefert seinen Schluessel."""
    iso2 = iso2.upper()
    conn.execute(
        """INSERT INTO Dim_Markt (iso2, name, region) VALUES (?, ?, ?)
           ON CONFLICT(iso2) DO NOTHING""",
        (iso2, name or iso2, _REGION_JE_LAND.get(iso2, "Uebrige")))
    conn.commit()
    return int(conn.execute("SELECT markt_sk FROM Dim_Markt WHERE iso2 = ?",
                            (iso2,)).fetchone()[0])

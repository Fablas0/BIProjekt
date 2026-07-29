"""LOAD -- Ueberfuehrung der transformierten Daten in das Core Data Warehouse.

Zwei grundlegend verschiedene Ladestrategien:

**Dimensionen** werden bi-temporal historisiert. Aendert sich ein fachlich
relevantes Attribut (erkannt ueber ``row_hash``), wird der bisherige Satz zum
Vortag abgegrenzt (``gueltig_bis``, ``ist_aktuell = 0``) und ein neuer Satz
eroeffnet. Der alte Zustand bleibt erhalten und bleibt fuer Auswertungen zu einem
historischen Stichtag verfuegbar.

**Fakten** werden ausschliesslich eingefuegt beziehungsweise idempotent
aktualisiert. Es wird nichts geloescht: ein erneuter Lauf desselben Monats
ueberschreibt genau die Kennzahlen dieses Monats, alle uebrigen Monate der
Zeitreihe bleiben unberuehrt. Damit ist die Nicht-Volatilitaet nach Inmon
gewahrt und der Ladelauf beliebig wiederholbar.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from ..warehouse import UNENDLICH
from .transform import (
    Befund,
    UsageSatz,
    faehigkeit_klasse,
    item_kategorie,
    zeitdimension,
)


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
    "typ_kombination", "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
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
        slug = satz["slug"]
        alt = bestand.get(slug)

        if alt is None:
            zaehler["neu"] += 1
        elif alt[1] == satz["row_hash"]:
            zaehler["unveraendert"] += 1
            continue
        else:
            # Der bisherige Satz wird zum Vortag abgegrenzt. Faellt die Aenderung
            # auf denselben Tag wie der Beginn seiner Gueltigkeit, wuerde ein leeres
            # Intervall entstehen -- dann wird der Beginn als Ende verwendet.
            ende = max(vortag, alt[2])
            abgrenzen.append((ende, alt[0]))
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
        spalten = ", ".join(_POKEMON_SPALTEN) + ", gueltig_ab, gueltig_bis, ist_aktuell, dwh_geladen_am"
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
    # Besteht die Dimension nur aus ihrem Schluessel (z.B. Dim_Tera), gibt es
    # nichts zu aktualisieren -- dann waere eine leere SET-Klausel ein Syntaxfehler.
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


def lade_zeit(conn: sqlite3.Connection, monate: list[str]) -> dict[str, int]:
    """Legt die Zeitdimension an und markiert den jeweils juengsten Monat."""
    saetze = [zeitdimension(m) for m in sorted(set(monate))]
    for satz in saetze:
        conn.execute(
            """INSERT INTO Dim_Zeit
                   (zeit_sk, monat_iso, jahr, quartal, monat, monat_name, quartal_label)
               VALUES (:zeit_sk, :monat_iso, :jahr, :quartal, :monat, :monat_name, :quartal_label)
               ON CONFLICT(monat_iso) DO NOTHING""",
            satz,
        )
    conn.execute("UPDATE Dim_Zeit SET ist_letzter_monat = 0")
    conn.execute(
        "UPDATE Dim_Zeit SET ist_letzter_monat = 1 "
        "WHERE monat_iso = (SELECT MAX(monat_iso) FROM Dim_Zeit)"
    )
    conn.commit()
    return {zeile["monat_iso"]: zeile["zeit_sk"] for zeile in
            conn.execute("SELECT monat_iso, zeit_sk FROM Dim_Zeit")}


def lade_regulation(conn: sqlite3.Connection, format_code: str, regulation: str,
                    spielmodus: str, saison: str, generation: str, anzeige: str) -> int:
    """Legt eine Regulation an oder liefert deren bestehenden Schluessel."""
    conn.execute(
        """INSERT INTO Dim_Regulation
               (format_code, regulation, spielmodus, saison, generation, anzeige)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(format_code) DO UPDATE SET anzeige = excluded.anzeige""",
        (format_code, regulation, spielmodus, saison, generation, anzeige),
    )
    conn.commit()
    return int(conn.execute("SELECT regulation_sk FROM Dim_Regulation WHERE format_code = ?",
                            (format_code,)).fetchone()[0])


def lade_skill(conn: sqlite3.Connection, elo_cutoff: int, bezeichnung: str, stufe: int) -> int:
    """Legt eine Skill-Stufe an oder liefert deren bestehenden Schluessel."""
    conn.execute(
        """INSERT INTO Dim_Skill (elo_cutoff, bezeichnung, stufe) VALUES (?, ?, ?)
           ON CONFLICT(elo_cutoff) DO UPDATE SET bezeichnung = excluded.bezeichnung""",
        (elo_cutoff, bezeichnung, stufe),
    )
    conn.commit()
    return int(conn.execute("SELECT skill_sk FROM Dim_Skill WHERE elo_cutoff = ?",
                            (elo_cutoff,)).fetchone()[0])


def lade_attacken_dimension(conn: sqlite3.Connection, saetze: list[dict[str, Any]]) -> None:
    """Laedt die Attacken-Dimension."""
    _sichere_dimension(conn, "Dim_Attacke", "slug", saetze)


def lade_hilfsdimensionen(conn: sqlite3.Connection, items: set[str], faehigkeiten: set[str],
                          tera_typen: set[str],
                          anzeigenamen: dict[str, str] | None = None) -> None:
    """Legt Item-, Faehigkeits- und Tera-Dimension aus den beobachteten Werten an.

    Diese Auspraegungen stammen ausschliesslich aus den Bewegungsdaten; ein
    eigenes Stammdatensystem existiert dafuer nicht.

    ``anzeigenamen`` bildet Smogon-Slugs auf lesbare Bezeichnungen ab. Smogon
    schreibt Bezeichner ohne Trennzeichen (``grassysurge``), sodass die Wortgrenze
    ohne Referenzliste nicht rekonstruierbar ist.
    """
    lookup = anzeigenamen or {}

    def lesbar(slug: str) -> str:
        if slug in lookup:
            return " ".join(t.capitalize() for t in lookup[slug].split("-"))
        return " ".join(t.capitalize() for t in slug.replace("-", " ").split())

    _sichere_dimension(conn, "Dim_Item", "slug", [
        {"slug": s, "anzeigename": lesbar(s), "kategorie": item_kategorie(s)}
        for s in sorted(items)
    ])
    _sichere_dimension(conn, "Dim_Faehigkeit", "slug", [
        {"slug": s, "anzeigename": lesbar(s), "effekt_klasse": faehigkeit_klasse(s)}
        for s in sorted(faehigkeiten)
    ])
    _sichere_dimension(conn, "Dim_Tera", "typ", [
        {"typ": t.capitalize()} for t in sorted(tera_typen)
    ])


# --------------------------------------------------------------------------
# Fakten
# --------------------------------------------------------------------------

def _schluesselkarten(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Laedt die Ersatzschluessel aller Dimensionen fuer die Faktenzuordnung."""
    return {
        "pokemon": {z["slug"]: z["pokemon_sk"] for z in conn.execute(
            "SELECT slug, pokemon_sk FROM Dim_Pokemon WHERE ist_aktuell = 1")},
        "attacke": {z["slug"]: z["attacke_sk"] for z in conn.execute(
            "SELECT slug, attacke_sk FROM Dim_Attacke")},
        "item": {z["slug"]: z["item_sk"] for z in conn.execute(
            "SELECT slug, item_sk FROM Dim_Item")},
        "faehigkeit": {z["slug"]: z["faehigkeit_sk"] for z in conn.execute(
            "SELECT slug, faehigkeit_sk FROM Dim_Faehigkeit")},
        "tera": {z["typ"].lower(): z["tera_sk"] for z in conn.execute(
            "SELECT typ, tera_sk FROM Dim_Tera")},
    }


def lade_fakten(conn: sqlite3.Connection, saetze: list[UsageSatz], zeit_sk: int,
                regulation_sk: int, skill_sk: int, partien_gesamt: int,
                lauf_id: int) -> tuple[int, list[Befund]]:
    """Schreibt alle sechs Faktentabellen fuer einen Monat.

    Der Ladevorgang ist idempotent: ``ON CONFLICT ... DO UPDATE`` auf dem
    fachlichen Schluessel aktualisiert einen bereits geladenen Monat, statt
    Dubletten anzulegen oder Historie zu loeschen.
    """
    karten = _schluesselkarten(conn)
    befunde: list[Befund] = []

    usage_zeilen: list[tuple[Any, ...]] = []
    attacken_zeilen: list[tuple[Any, ...]] = []
    item_zeilen: list[tuple[Any, ...]] = []
    faehigkeit_zeilen: list[tuple[Any, ...]] = []
    tera_zeilen: list[tuple[Any, ...]] = []
    partner_zeilen: list[tuple[Any, ...]] = []

    for satz in saetze:
        pokemon_sk = karten["pokemon"].get(satz.slug)
        if pokemon_sk is None:
            befunde.append(Befund(
                "Fact_Usage", satz.slug, "Referenzielle Integritaet",
                "Kein aktueller Eintrag in Dim_Pokemon -- Fakt nicht ladbar",
                klasse="Mangel 1. Klasse", dimension="Referenzielle Integritaet"))
            continue

        usage_zeilen.append((
            pokemon_sk, zeit_sk, regulation_sk, skill_sk, satz.usage_rate, satz.raw_count,
            partien_gesamt, satz.gxe_top, satz.gxe_p75, satz.gxe_p50, satz.rang, lauf_id,
        ))

        basis = (pokemon_sk, zeit_sk, regulation_sk, skill_sk)

        for slug, anteil, rang in satz.attacken:
            attacke_sk = karten["attacke"].get(slug)
            if attacke_sk is None:
                befunde.append(Befund(
                    "Fact_Attacken_Nutzung", f"{satz.slug}/{slug}", "Referenzielle Integritaet",
                    f"Attacke '{slug}' fehlt in Dim_Attacke -- Detailfakt uebersprungen",
                    klasse="Mangel 2. Klasse", dimension="Referenzielle Integritaet"))
                continue
            attacken_zeilen.append((*basis, attacke_sk, anteil, rang))

        for slug, anteil, rang in satz.items:
            if (sk := karten["item"].get(slug)) is not None:
                item_zeilen.append((*basis, sk, anteil, rang))

        for slug, anteil, rang in satz.faehigkeiten:
            if (sk := karten["faehigkeit"].get(slug)) is not None:
                faehigkeit_zeilen.append((*basis, sk, anteil, rang))

        for slug, anteil, rang in satz.tera_typen:
            if (sk := karten["tera"].get(slug.lower())) is not None:
                tera_zeilen.append((*basis, sk, anteil, rang))

        for partner_slug, anteil, rang in satz.partner:
            if (sk := karten["pokemon"].get(partner_slug)) is not None:
                partner_zeilen.append((pokemon_sk, sk, zeit_sk, regulation_sk, skill_sk,
                                       anteil, rang))

    conn.executemany(
        """INSERT INTO Fact_Usage
               (pokemon_sk, zeit_sk, regulation_sk, skill_sk, usage_rate, raw_count,
                partien_gesamt, gxe_top, gxe_p75, gxe_p50, rang, etl_lauf_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(pokemon_sk, zeit_sk, regulation_sk, skill_sk) DO UPDATE SET
               usage_rate = excluded.usage_rate, raw_count = excluded.raw_count,
               partien_gesamt = excluded.partien_gesamt, gxe_top = excluded.gxe_top,
               gxe_p75 = excluded.gxe_p75, gxe_p50 = excluded.gxe_p50,
               rang = excluded.rang, etl_lauf_id = excluded.etl_lauf_id""",
        usage_zeilen,
    )

    for tabelle, schluessel, zeilen in (
        ("Fact_Attacken_Nutzung", "attacke_sk", attacken_zeilen),
        ("Fact_Item_Nutzung", "item_sk", item_zeilen),
        ("Fact_Faehigkeit_Nutzung", "faehigkeit_sk", faehigkeit_zeilen),
        ("Fact_Tera_Nutzung", "tera_sk", tera_zeilen),
    ):
        conn.executemany(
            f"""INSERT INTO {tabelle}
                    (pokemon_sk, zeit_sk, regulation_sk, skill_sk, {schluessel}, anteil, rang)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pokemon_sk, zeit_sk, regulation_sk, skill_sk, {schluessel})
                DO UPDATE SET anteil = excluded.anteil, rang = excluded.rang""",  # noqa: S608
            zeilen,
        )

    conn.executemany(
        """INSERT INTO Fact_Teampartner
               (pokemon_sk, partner_sk, zeit_sk, regulation_sk, skill_sk, synergie_wert, rang)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(pokemon_sk, partner_sk, zeit_sk, regulation_sk, skill_sk)
           DO UPDATE SET synergie_wert = excluded.synergie_wert, rang = excluded.rang""",
        partner_zeilen,
    )

    conn.commit()
    return len(usage_zeilen), befunde


# --------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------

def staging_smogon(conn: sqlite3.Connection, lauf_id: int, format_code: str, elo_cutoff: int,
                   monat_iso: str, dump: dict[str, Any], grenze: int = 400) -> None:
    """Legt die Rohnutzlast in der Staging-Schicht ab.

    Beschraenkt auf die ersten ``grenze`` Eintraege: die Schicht dient der
    Nachvollziehbarkeit einzelner Saetze, nicht als Volldatenarchiv -- ein
    kompletter Chaos-Dump umfasst je Monat mehrere Megabyte.
    """
    import json

    jetzt = _jetzt()
    conn.executemany(
        """INSERT OR REPLACE INTO Stage_Smogon
               (lauf_id, format_code, elo_cutoff, monat_iso, quell_name, nutzlast, geladen_am)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (lauf_id, format_code, elo_cutoff, monat_iso, name,
             json.dumps(inhalt, separators=(",", ":")), jetzt)
            for name, inhalt in list((dump.get("data") or {}).items())[:grenze]
        ],
    )
    conn.commit()


def staging_bereinigen(conn: sqlite3.Connection, behalte_laeufe: int = 2) -> None:
    """Haelt die Staging-Schicht auf den letzten ``behalte_laeufe`` Laeufen.

    Die Schicht ist ein Zwischenspeicher, kein Archiv -- ohne Bereinigung waechst
    sie mit jedem Lauf unbegrenzt.
    """
    for tabelle in ("Stage_Smogon", "Stage_Pokeapi"):
        conn.execute(
            f"""DELETE FROM {tabelle} WHERE lauf_id NOT IN (
                    SELECT DISTINCT lauf_id FROM {tabelle} ORDER BY lauf_id DESC LIMIT ?)""",  # noqa: S608
            (behalte_laeufe,),
        )
    conn.commit()

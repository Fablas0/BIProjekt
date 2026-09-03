"""Kartensammlung des Sammelkartenspiels.

Es gibt im Projekt keine Kartenstammdaten: die Limitless-Strecke liefert
Turnier-Standings mit Deck-Archetypen, keine Kartenliste, und eine
Kartendatenbank als fuenfte Quelle waere fuer eine Sammlungsliste
unverhaeltnismaessig. Satz, Nummer und Name sind deshalb Freitext.

Was die Sammlung trotzdem an die Auswertung anschliesst, ist der optionale
Pokemon-Schluessel: eine Karte, die einem Pokemon der konformen Dimension
zugeordnet ist, laesst sich gegen die Leit-Pokemon der Turnierdecks halten --
und beantwortet damit die Frage, ob eine Karte aus der eigenen Sammlung
gerade ein Meta-Deck anfuehrt.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .nutzerdaten import SCHEMA, _jetzt

SELTENHEITEN = ("Common", "Uncommon", "Rare", "Double Rare", "Ultra Rare",
                "Illustration Rare", "Special Illustration Rare", "Hyper Rare", "Promo")
ZUSTAENDE = ("Mint", "Near Mint", "Excellent", "Good", "Played", "Poor")

KARTEN_FELDER = ("satz", "nummer", "name", "slug", "anzahl", "seltenheit", "zustand", "notiz")


def karte_speichern(conn: sqlite3.Connection, nutzer_id: int, satz: dict[str, Any],
                    karte_id: int | None = None) -> int:
    werte = {feld: satz.get(feld) for feld in KARTEN_FELDER}
    if not (werte["satz"] or "").strip():
        raise ValueError("Die Karte braucht einen Satz (Erweiterung).")
    if not (werte["name"] or "").strip():
        raise ValueError("Die Karte braucht einen Namen.")
    werte["satz"] = werte["satz"].strip()
    werte["name"] = werte["name"].strip()
    werte["anzahl"] = max(1, int(werte["anzahl"] or 1))
    if werte["seltenheit"] and werte["seltenheit"] not in SELTENHEITEN:
        raise ValueError(f"Unbekannte Seltenheit: {werte['seltenheit']}")
    if werte["zustand"] and werte["zustand"] not in ZUSTAENDE:
        raise ValueError(f"Unbekannter Zustand: {werte['zustand']}")

    jetzt = _jetzt()
    if karte_id is None:
        spalten = ", ".join(KARTEN_FELDER)
        platzhalter = ", ".join("?" * len(KARTEN_FELDER))
        cursor = conn.execute(
            f"""INSERT INTO {SCHEMA}.Karte (nutzer_id, {spalten}, angelegt_am, geaendert_am)
                VALUES (?, {platzhalter}, ?, ?)""",
            (nutzer_id, *(werte[f] for f in KARTEN_FELDER), jetzt, jetzt))
        conn.commit()
        return int(cursor.lastrowid)

    zuweisung = ", ".join(f"{f} = ?" for f in KARTEN_FELDER)
    conn.execute(
        f"UPDATE {SCHEMA}.Karte SET {zuweisung}, geaendert_am = ? "
        f"WHERE karte_id = ? AND nutzer_id = ?",
        (*(werte[f] for f in KARTEN_FELDER), jetzt, karte_id, nutzer_id))
    conn.commit()
    return karte_id


def karten_lesen(conn: sqlite3.Connection, nutzer_id: int) -> list[dict[str, Any]]:
    """Die Sammlung eines Nutzers, angereichert um Pokemon und Meta-Bezug.

    ``meta_decks`` nennt die Turnierdecks, deren Leit-Pokemon die Karte ist --
    ueber die konforme Dimension, sofern die TCG-Strecke geladen ist.
    """
    zeilen = conn.execute(f"""
        SELECT k.*, p.anzeigename, p.name_de, p.pokedex_id, p.typ1, p.typ2,
               (SELECT GROUP_CONCAT(d.anzeigename, ' · ')
                  FROM Dim_TCG_Deck d
                 WHERE d.leit_slug = k.slug
                   AND EXISTS (SELECT 1 FROM Fact_TCG_Meta f WHERE f.deck_sk = d.deck_sk)
               ) AS meta_decks
          FROM {SCHEMA}.Karte k
          LEFT JOIN Dim_Pokemon p ON p.slug = k.slug AND p.ist_aktuell = 1
         WHERE k.nutzer_id = ?
         ORDER BY k.satz, k.nummer, k.name
    """, (nutzer_id,)).fetchall()
    return [dict(z) for z in zeilen]


def karte_loeschen(conn: sqlite3.Connection, nutzer_id: int, karte_id: int) -> None:
    conn.execute(f"DELETE FROM {SCHEMA}.Karte WHERE karte_id = ? AND nutzer_id = ?",
                 (karte_id, nutzer_id))
    conn.commit()


def bilanz(karten: list[dict[str, Any]]) -> dict[str, int]:
    """Zaehlungen ueber die Sammlung: Karten, Exemplare, Saetze, Meta-Bezug."""
    return {
        "karten": len(karten),
        "exemplare": sum(int(k["anzahl"]) for k in karten),
        "saetze": len({k["satz"] for k in karten}),
        "im_meta": sum(1 for k in karten if k.get("meta_decks")),
    }

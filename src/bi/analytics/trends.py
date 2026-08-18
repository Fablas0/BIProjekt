"""Trendanalysen: Typen, Items, Neuzugaenge und Spitzenreiter im Zeitverlauf.

Vier Fragen, eine Regel
-----------------------
Jede Auswertung hier laeuft ueber die Zeitachse -- und jede haelt sich an das
Messniveau ihrer Kennzahl:

=============================  ======================  ==========================
Frage                          Kennzahl                Warum zulaessig
=============================  ======================  ==========================
Welche Typen tragen die Meta?  Anzahl Vertreter in     reine Mengenoperation
                               den besten N je Tag     auf Raengen
Welche Items setzen sich       mittlerer Trageanteil   echte Anteile auf der
durch?                         je Tag                  Merkmalsebene
Wer ist neu in der Meta?       erster Tag in den       Zaehlung, kein Rechnen
                               besten N                mit Raengen
Wer traegt dauerhaft?          Verweildauer plus       Zaehlung plus Minimum --
                               bester Rang             beides rangfest
=============================  ======================  ==========================

Der Typenverlauf zaehlt bewusst Vertreter statt Raenge zu mitteln: ein
"mittlerer Rang je Typ" waere eine Rechnung auf ordinalen Daten und damit genau
der Fehler, gegen den sich der Kennzahlenkatalog des Projekts abgrenzt.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import META_RANGGRENZE, STANDARD_KAMPFFORMAT
from . import kpi, saison


def _lese(conn: sqlite3.Connection, sql: str, parameter: tuple = ()) -> pd.DataFrame:
    return pd.read_sql(saison.anwenden(sql, conn), conn, params=parameter)


# --------------------------------------------------------------------------
# Starke Typen ueber die Zeit
# --------------------------------------------------------------------------

def typenstaerke_verlauf(conn: sqlite3.Connection, n: int = META_RANGGRENZE,
                         kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Vertreter je Primaertyp in den besten N, je Tag.

    Rueckgabe: eine Zeile je Tag und Typ mit der Anzahl der Vertreter. Die
    Zaehlung ist eine Mengenoperation und auf Rangdaten uneingeschraenkt
    zulaessig -- anders als ein Mittelwert ueber Raenge.
    """
    return _lese(conn, """
        SELECT datum_iso, typ1 AS typ, COUNT(*) AS vertreter
        FROM V_Usage
        WHERE kampfformat = ? AND saison_aktuell = 1 AND rang <= ?
        GROUP BY datum_iso, typ1
        ORDER BY datum_iso, typ1
    """, (kampfformat, n))


def typen_bewegung(conn: sqlite3.Connection, n: int = META_RANGGRENZE,
                   kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Auf- und Absteiger unter den Typen: erster gegen letzter geladener Tag."""
    verlauf = typenstaerke_verlauf(conn, n, kampfformat)
    if verlauf.empty:
        return pd.DataFrame(columns=["typ", "beginn", "ende", "veraenderung"])

    erster, letzter = verlauf["datum_iso"].min(), verlauf["datum_iso"].max()
    beginn = verlauf.loc[verlauf["datum_iso"] == erster].set_index("typ")["vertreter"]
    ende = verlauf.loc[verlauf["datum_iso"] == letzter].set_index("typ")["vertreter"]

    df = pd.concat([beginn.rename("beginn"), ende.rename("ende")], axis=1).fillna(0)
    df["veraenderung"] = (df["ende"] - df["beginn"]).astype(int)
    return (df.astype({"beginn": int, "ende": int}).reset_index()
            .sort_values("veraenderung", ascending=False).reset_index(drop=True))


# --------------------------------------------------------------------------
# Item-Nutzung
# --------------------------------------------------------------------------

def item_nutzung(conn: sqlite3.Connection,
                 kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Meistgetragene Items am juengsten Tag, mit Wirkungsklasse.

    Gezaehlt wird, bei wie vielen Pokemon das Item an erster Stelle steht
    (``traeger``), dazu der mittlere Trageanteil ueber diese Traeger --
    letzteres ist zulaessig, weil die Merkmalsanteile echte Anteile sind.
    """
    tag = kpi.aktueller_tag(conn, kampfformat)
    if not tag:
        return pd.DataFrame(columns=["bezeichnung", "wirkung_klasse", "traeger",
                                     "mittlerer_anteil"])
    return _lese(conn, """
        SELECT bezeichnung,
               COALESCE(item_klasse, 'Nicht verknuepft') AS wirkung_klasse,
               COUNT(*) AS traeger,
               ROUND(AVG(anteil), 1) AS mittlerer_anteil
        FROM V_Merkmal
        WHERE kategorie = 'held_item' AND rang = 1
          AND datum_iso = ? AND kampfformat = ? AND saison_aktuell = 1
        GROUP BY bezeichnung, item_klasse
        ORDER BY traeger DESC
    """, (tag, kampfformat))


def item_nutzung_verlauf(conn: sqlite3.Connection, top: int = 8,
                         kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Traegerzahl der meistgetragenen Items ueber alle Tage."""
    df = _lese(conn, """
        SELECT datum_iso, bezeichnung, COUNT(*) AS traeger
        FROM V_Merkmal
        WHERE kategorie = 'held_item' AND rang = 1
          AND kampfformat = ? AND saison_aktuell = 1
        GROUP BY datum_iso, bezeichnung
    """, (kampfformat,))
    if df.empty:
        return df
    haeufigste = df.groupby("bezeichnung")["traeger"].sum().nlargest(top).index
    return df.loc[df["bezeichnung"].isin(haeufigste)].reset_index(drop=True)


# --------------------------------------------------------------------------
# Neuzugaenge
# --------------------------------------------------------------------------

def neuzugaenge(conn: sqlite3.Connection, n: int = META_RANGGRENZE,
                kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Pokemon, die erst im Verlauf in die besten N aufgestiegen sind.

    Ein Pokemon zaehlt als Neuzugang, wenn sein erster Tag in den besten N
    **nach** dem ersten geladenen Tag liegt -- wer von Anfang an oben stand,
    ist etabliert, nicht neu. Je juenger der Aufstieg, desto weiter oben in
    der Rueckgabe.
    """
    tage = kpi.verfuegbare_tage(conn, kampfformat)
    if len(tage) < 2:
        return pd.DataFrame(columns=["anzeigename", "erster_tag_oben",
                                     "aktueller_rang", "bester_rang"])

    df = _lese(conn, """
        SELECT anzeigename, pokedex_id, typ1, typ2, datum_iso, rang
        FROM V_Usage
        WHERE kampfformat = ? AND saison_aktuell = 1 AND rang <= ?
    """, (kampfformat, n))
    if df.empty:
        return pd.DataFrame(columns=["anzeigename", "erster_tag_oben",
                                     "aktueller_rang", "bester_rang"])

    erster_tag = df.groupby(["anzeigename", "pokedex_id", "typ1", "typ2"],
                            dropna=False).agg(
        erster_tag_oben=("datum_iso", "min"),
        bester_rang=("rang", "min"),
    ).reset_index()

    neu = erster_tag.loc[erster_tag["erster_tag_oben"] > tage[0]].copy()
    aktuell = df.loc[df["datum_iso"] == tage[-1]].set_index("anzeigename")["rang"]
    neu["aktueller_rang"] = neu["anzeigename"].map(aktuell).astype("Int64")
    neu["noch_oben"] = neu["aktueller_rang"].notna()
    return (neu.sort_values("erster_tag_oben", ascending=False)
            .reset_index(drop=True))


# --------------------------------------------------------------------------
# Dauerhaft starke Pokemon
# --------------------------------------------------------------------------

def spitzenreiter(conn: sqlite3.Connection, n: int = 10,
                  kampfformat: str = STANDARD_KAMPFFORMAT) -> pd.DataFrame:
    """Die Dauerbrenner der Spitzengruppe -- delegiert an die Verweildauer.

    Eigene Logik braucht es hier nicht: die Verweildauer in den besten N ist
    genau die rangfeste Kennzahl fuer "dauerhaft stark". Die Funktion existiert,
    damit die Trend-Seite eine vollstaendige Schnittstelle hat.
    """
    return kpi.verweildauer(conn, n, kampfformat)

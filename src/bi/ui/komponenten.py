"""Wiederverwendbare Bausteine der Oberflaeche.

Buendelt Darstellung und Datenzugriff, die von mehreren Seiten gebraucht werden.
Der Datenzugriff ist ueber ``st.cache_data`` zwischengespeichert: die Seiten
werden bei jeder Interaktion vollstaendig neu ausgefuehrt, ohne Zwischenspeicher
liefe daher jede Auswahl erneut gegen die Datenbank.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from .. import bootstrap
from ..analytics import kpi
from ..config import STANDARD_KAMPFFORMAT, TYP_DEUTSCH, TYP_FARBEN, sprite_url
from ..warehouse import ist_befuellt, verbindung


@st.cache_resource
def hole_verbindung() -> sqlite3.Connection:
    """Eine gemeinsam genutzte DWH-Verbindung fuer die gesamte Sitzung.

    Beim ersten Aufruf in einem Behaelter wird das Data Warehouse aus dem
    mitversionierten Archiv aufgebaut. Das ist keine Bequemlichkeit, sondern
    Voraussetzung fuer den Betrieb in der Cloud: das Datenverzeichnis ist nicht
    versioniert, und Streamlit Community Cloud setzt bei jedem Deployment einen
    frischen Behaelter auf. Ohne diesen Schritt stuende die Anwendung dort
    taeglich wieder ohne Daten da.

    Dank ``cache_resource`` geschieht das genau einmal je Behaelter.
    """
    conn = verbindung()
    if ist_befuellt(conn) or not bootstrap.ist_aufbau_moeglich():
        return conn

    anzeige = st.empty()
    with anzeige.container():
        st.info("Das Data Warehouse wird aus dem Archiv aufgebaut. "
                "Das geschieht einmalig und dauert einige Sekunden.")
        balken = st.progress(0.0)
        beschriftung = st.empty()

        def melde(anteil: float, meldung: str) -> None:
            balken.progress(min(1.0, max(0.0, anteil)))
            beschriftung.caption(meldung)

        bootstrap.sicherstellen(conn, fortschritt=melde)

    # Die Meldung wieder abraeumen: sie gehoert zum Aufbau, nicht zur Anwendung.
    anzeige.empty()
    return conn


@st.cache_data(ttl=300)
def abfrage(sql: str, parameter: tuple = ()) -> pd.DataFrame:
    """Zwischengespeicherte Leseabfrage."""
    return pd.read_sql(sql, hole_verbindung(), params=parameter)


def zwischenspeicher_leeren() -> None:
    """Verwirft alle zwischengespeicherten Abfrageergebnisse."""
    abfrage.clear()


# --------------------------------------------------------------------------
# Auswahlfelder
# --------------------------------------------------------------------------

def kopfauswahl(conn, schluessel: str, mit_tag: bool = True) -> tuple[str, str | None]:
    """Einheitliche Auswahl von Kampfformat und Berichtstag.

    Beide Formate liegen getrennt vor; die Auswahl gehoert daher auf jede Seite,
    die Bewegungsdaten auswertet.
    """
    formate = kpi.verfuegbare_formate(conn) or [STANDARD_KAMPFFORMAT]
    spalten = st.columns([1, 1]) if mit_tag else [st.container()]

    with spalten[0]:
        kampfformat = st.selectbox(
            "Kampfformat", formate,
            index=formate.index(STANDARD_KAMPFFORMAT) if STANDARD_KAMPFFORMAT in formate else 0,
            key=f"{schluessel}_format",
            help="Doppelkampf: vier von sechs im Team-Preview. Einzelkampf: drei von sechs.",
        )

    tag = None
    if mit_tag:
        tage = kpi.verfuegbare_tage(conn, kampfformat)
        with spalten[1]:
            tag = st.selectbox(
                "Berichtstag", list(reversed(tage)), index=0, key=f"{schluessel}_tag",
            ) if tage else None

    return kampfformat, tag


# --------------------------------------------------------------------------
# Darstellung
# --------------------------------------------------------------------------

def typ_abzeichen(typ: str | None) -> str:
    """HTML-Abzeichen fuer einen Pokemon-Typ in der zugehoerigen Farbe."""
    if not typ or pd.isna(typ):
        return ""
    farbe = TYP_FARBEN.get(typ, "#777")
    beschriftung = TYP_DEUTSCH.get(typ, typ)
    return (
        f"<span style='background:{farbe};color:#fff;padding:2px 9px;border-radius:10px;"
        f"font-size:0.72rem;font-weight:600;margin-right:4px;white-space:nowrap;'>"
        f"{beschriftung}</span>"
    )


def typ_abzeichen_paar(typ1: str | None, typ2: str | None = None) -> str:
    """Abzeichen fuer ein Typenpaar."""
    return typ_abzeichen(typ1) + (typ_abzeichen(typ2) if typ2 and not pd.isna(typ2) else "")


def pokemon_karte(zeile: pd.Series, zusatz: str = "") -> str:
    """Kompakte Kartendarstellung eines Pokemon fuer Uebersichten."""
    return (
        "<div style='text-align:center;padding:10px 6px;border-radius:12px;"
        "background:rgba(128,128,128,0.08);height:100%;'>"
        f"<img src='{sprite_url(int(zeile['pokedex_id']))}' width='104' "
        "style='display:block;margin:0 auto;'>"
        f"<div style='font-weight:600;margin:4px 0 6px;font-size:0.95rem;'>"
        f"{zeile['anzeigename']}</div>"
        f"<div style='margin-bottom:6px;'>{typ_abzeichen_paar(zeile.get('typ1'), zeile.get('typ2'))}</div>"
        f"{zusatz}</div>"
    )


def kennzahl_kachel(beschriftung: str, wert: str, hinweis: str = "",
                    farbe: str = "#EF553B") -> str:
    """Kachel fuer eine einzelne Kennzahl."""
    return (
        "<div style='padding:14px 16px;border-radius:12px;background:rgba(128,128,128,0.08);"
        f"border-left:4px solid {farbe};height:100%;'>"
        f"<div style='font-size:0.75rem;opacity:0.7;text-transform:uppercase;"
        f"letter-spacing:0.04em;'>{beschriftung}</div>"
        f"<div style='font-size:1.7rem;font-weight:700;line-height:1.25;'>{wert}</div>"
        f"<div style='font-size:0.78rem;opacity:0.65;'>{hinweis}</div></div>"
    )


AMPEL_FARBEN = {"gruen": "#2ecc71", "gelb": "#f1c40f", "rot": "#e74c3c"}


def ampel(stufe: str, text: str) -> str:
    """Ampelzeile fuer den Qualitaetsbericht."""
    farbe = AMPEL_FARBEN.get(stufe, "#95a5a6")
    return f"<span style='color:{farbe};font-size:1.1rem;'>●</span> {text}"


def hinweis_leere_datenbank() -> None:
    """Einheitlicher Hinweis, wenn noch keine Daten geladen sind."""
    st.info(
        "**Das Data Warehouse ist noch leer.**\n\n"
        "Wechsle in der Navigation zu *ETL & Datenqualitaet* und starte dort "
        "zuerst den Stammdaten- und anschliessend den Champions-Ladelauf. "
        "Der vollstaendige Aufbau dauert etwa 30 Sekunden."
    )


def hinweis_messniveau() -> None:
    """Erlaeuterung, warum es keine Nutzungsquote gibt.

    Steht auf jeder Seite, die Raenge zeigt -- die Einschraenkung ist zentral
    fuer das Verstaendnis der Kennzahlen.
    """
    st.caption(
        "Pokemon Champions veroeffentlicht die Nutzung als **Rang**, nicht als "
        "Anteil in Prozent. Ausgewiesen werden deshalb Raenge und daraus "
        "abgeleitete Groessen; eine Nutzungsquote wird nicht vorgetaeuscht."
    )

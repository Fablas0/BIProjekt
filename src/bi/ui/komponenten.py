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

from ..config import TYP_DEUTSCH, TYP_FARBEN, sprite_url
from ..warehouse import verbindung


@st.cache_resource
def hole_verbindung() -> sqlite3.Connection:
    """Eine gemeinsam genutzte DWH-Verbindung fuer die gesamte Sitzung."""
    return verbindung()


@st.cache_data(ttl=300)
def abfrage(sql: str, parameter: tuple = ()) -> pd.DataFrame:
    """Zwischengespeicherte Leseabfrage.

    Der Zwischenspeicher wird nach jedem Ladelauf ueber :func:`zwischenspeicher_leeren`
    verworfen, damit neue Daten sofort sichtbar werden.
    """
    return pd.read_sql(sql, hole_verbindung(), params=parameter)


def zwischenspeicher_leeren() -> None:
    """Verwirft alle zwischengespeicherten Abfrageergebnisse."""
    abfrage.clear()


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
AMPEL_ZEICHEN = {"gruen": "●", "gelb": "●", "rot": "●"}


def ampel(stufe: str, text: str) -> str:
    """Ampelzeile fuer den Qualitaetsbericht."""
    farbe = AMPEL_FARBEN.get(stufe, "#95a5a6")
    return (f"<span style='color:{farbe};font-size:1.1rem;'>{AMPEL_ZEICHEN.get(stufe, '●')}</span> "
            f"{text}")


def hinweis_leere_datenbank() -> None:
    """Einheitlicher Hinweis, wenn noch keine Daten geladen sind."""
    st.info(
        "**Das Data Warehouse ist noch leer.**\n\n"
        "Wechsle in der Navigation zu *ETL & Datenqualitaet* und starte dort "
        "zuerst den Stammdaten- und anschliessend den Bewegungsdaten-Ladelauf. "
        "Der vollstaendige Aufbau dauert etwa 20 Sekunden."
    )


def monatsauswahl(monate: list[str], schluessel: str, beschriftung: str = "Berichtsmonat") -> str:
    """Auswahlfeld fuer den Berichtsmonat, standardmaessig der juengste."""
    return st.selectbox(beschriftung, options=list(reversed(monate)), index=0, key=schluessel)

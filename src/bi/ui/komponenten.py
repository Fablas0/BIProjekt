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
from . import design


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
# Deutsche Namen
# --------------------------------------------------------------------------
# Champions und die Analyse arbeiten mit den englischen Anzeigenamen -- sie
# sind der Schluessel zwischen den Quellsystemen und bleiben es. Fuer die
# Bedienung zaehlt aber, dass jemand "Vulnona" eintippen kann, ohne den
# englischen Namen zu kennen: die Auswahlfelder zeigen deshalb beide Namen an
# und finden damit auch beide (Streamlit sucht im angezeigten Text).

@st.cache_data(ttl=3600)
def _uebersetzungen(tabelle: str) -> dict[str, str]:
    """Anzeigename -> deutscher Name einer Stammdatentabelle.

    Nur echte Unterschiede werden gefuehrt; "Pikachu · Pikachu" waere Laerm.
    """
    df = abfrage(
        f"SELECT DISTINCT anzeigename, name_de FROM {tabelle} "  # noqa: S608 -- fester Tabellenname
        "WHERE name_de IS NOT NULL AND name_de <> anzeigename"
    )
    return dict(zip(df["anzeigename"], df["name_de"], strict=True))


def name_mit_deutsch(anzeigename: str) -> str:
    """Beschriftung eines Pokemon-Auswahlfelds: englisch, deutsch dahinter.

    Als ``format_func`` gedacht: der Wert des Felds bleibt der englische
    Anzeigename, nur die Beschriftung traegt die Uebersetzung mit.
    """
    deutsch = _uebersetzungen("Dim_Pokemon").get(anzeigename)
    return f"{anzeigename} · {deutsch}" if deutsch else anzeigename


def attacke_mit_deutsch(anzeigename: str) -> str:
    """Beschriftung eines Attacken-Auswahlfelds, deutsch dahinter."""
    deutsch = _uebersetzungen("Dim_Attacke").get(anzeigename)
    return f"{anzeigename} · {deutsch}" if deutsch else anzeigename


def item_mit_deutsch(anzeigename: str) -> str:
    """Beschriftung eines Item-Auswahlfelds, deutsch dahinter."""
    deutsch = _uebersetzungen("Dim_Item").get(anzeigename)
    return f"{anzeigename} · {deutsch}" if deutsch else anzeigename


def faehigkeit_mit_deutsch(anzeigename: str) -> str:
    """Beschriftung eines Faehigkeiten-Auswahlfelds, deutsch dahinter."""
    deutsch = _uebersetzungen("Dim_Faehigkeit").get(anzeigename)
    return f"{anzeigename} · {deutsch}" if deutsch else anzeigename


def deutscher_pokemonname(anzeigename: str) -> str | None:
    """Der deutsche Name eines Pokemon, ``None`` ohne abweichende Uebersetzung."""
    return _uebersetzungen("Dim_Pokemon").get(anzeigename)


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
    farbe = TYP_FARBEN.get(typ, design.TYP_ERSATZFARBE)
    beschriftung = TYP_DEUTSCH.get(typ, typ)
    return (
        f"<span style='background:{farbe};color:{design.SCHRIFT_AUF_FARBE};"
        f"padding:2px 9px;border-radius:10px;"
        f"font-size:0.72rem;font-weight:600;margin-right:4px;white-space:nowrap;'>"
        f"{beschriftung}</span>"
    )


def typ_abzeichen_paar(typ1: str | None, typ2: str | None = None) -> str:
    """Abzeichen fuer ein Typenpaar."""
    return typ_abzeichen(typ1) + (typ_abzeichen(typ2) if typ2 and not pd.isna(typ2) else "")


def pokemon_karte(zeile: pd.Series, zusatz: str = "") -> str:
    """Kompakte Kartendarstellung eines Pokemon fuer Uebersichten."""
    return (
        "<div class='karte'>"
        f"<img src='{sprite_url(int(zeile['pokedex_id']))}' width='104' "
        "style='display:block;margin:0 auto;'>"
        f"<div style='font-weight:600;margin:4px 0 6px;font-size:0.95rem;'>"
        f"{zeile['anzeigename']}</div>"
        f"<div style='margin-bottom:6px;'>{typ_abzeichen_paar(zeile.get('typ1'), zeile.get('typ2'))}</div>"
        f"{zusatz}</div>"
    )


def kennzahl_kachel(beschriftung: str, wert: str, hinweis: str = "",
                    bedeutung: str = "neutral") -> str:
    """Kachel fuer eine einzelne Kennzahl.

    Angegeben wird keine Farbe, sondern die **Aussage** der Zahl -- eine der
    vier aus :data:`bi.ui.design.BEDEUTUNGEN`. Welcher Farbwert daraus wird,
    entscheidet allein das Designsystem.

    Zuvor reichte jede Seite hier einen Hexwert herein und griff dafuer in die
    Typenpalette: die Kacheln des Cockpits trugen Wasser-, Elektro-, Gift-,
    Pflanzen- und Feuerfarbe, ohne dass eine davon etwas ueber ihre Zahl sagte.
    """
    if bedeutung not in design.BEDEUTUNGEN:
        raise ValueError(
            f"Unbekannte Bedeutung '{bedeutung}'. Zulaessig: {', '.join(design.BEDEUTUNGEN)}."
        )
    zusatz = "" if bedeutung == "neutral" else f" kachel--{bedeutung}"
    return (
        f"<div class='kachel{zusatz}'>"
        f"<div class='kachel-beschriftung'>{beschriftung}</div>"
        f"<div class='kachel-wert'>{wert}</div>"
        f"<div class='kachel-hinweis'>{hinweis}</div></div>"
    )


# --------------------------------------------------------------------------
# Tabellen
# --------------------------------------------------------------------------
# Die Tabellen liefen zuvor ohne ``column_config``: Streamlit riet die
# Spaltenbreite aus dem Inhalt, Raenge standen linksbuendig neben Fliesstext,
# und ein Anteil war von einem Rang nur am Namen zu unterscheiden.
#
# Die Zuordnung haengt am **angezeigten** Spaltennamen. Die Seiten benennen ihre
# Spalten ohnehin vor der Ausgabe um; damit ist der Name die einzige Angabe, die
# an jeder Ausgabestelle schon vorliegt.
#
# Ein Rang bekommt bewusst *keinen* Balken. Ein Balken fuellt sich mit
# wachsendem Wert -- bei einem Rang waere er fuer Platz 1 am kuerzesten und
# laege damit genau falsch herum. Als Balken erscheint deshalb das
# Rangperzentil, das die Quelle ohnehin auf 0 bis 100 normiert und in dem 100
# fuer den ersten Platz steht.

_RANGSPALTEN = frozenset({
    "Rang", "Rang zuvor", "Bester Rang", "Schlechtester Rang", "Mittlerer Rang",
    "Aktueller Rang", "Meta-Rang", "Rang im Meta",
})

# Ganzzahlen ohne Nachkommastelle: Zaehlungen und Statuswerte.
_GANZZAHLSPALTEN = frozenset({
    "Nennungen", "Tage in der Spitze", "Wechsel in den besten 10", "Zeilen",
    "Saetze", "Gelesen", "Geladen", "Abgewiesen", "Anfaellig", "Resistent",
    "Immun", "Erfasste Sets", "Erfasste Pokemon", "Gefaehrdete Mitglieder",
    "Lauf", "Initiative", "Grundwert", "Ohne Investition", "Basiswertsumme",
    "Initiative (ohne Investition)",
})

# Nachkommastellen je Spalte, wo die Vorgabe zu grob oder zu fein waere.
_NACHKOMMA = {
    "Korrelation zum Start": "%.3f", "Korrelation zum Vortag": "%.3f",
    "Dauer (s)": "%.1f s", "Hoechster Faktor": "%.2f", "Konzentration": "%.2f",
    "Mittlere Initiative": "%.1f",
}

# Bilanzgroessen mit Nullpunkt -- das Vorzeichen ist die eigentliche Aussage.
_VORZEICHENSPALTEN = {
    "Veraenderung": "%+d", "Bewertung": "%+.2f", "Punktzahl": "%+.2f",
    "Gesamtwertung": "%+.2f", "Beitrag": "%+.2f", "Mittelwert": "%+.2f",
    "Schlechtester Fall": "%+.2f",
}

# Balken ueber einer festen Skala von 0 bis 100.
_ANTEILSSPALTEN = frozenset({"Rangperzentil", "Vorteil in %"})

# Balken ueber dem groessten beobachteten Wert: Indexgroessen ohne feste
# Obergrenze, bei denen nur der Vergleich untereinander etwas aussagt.
_INDEXSPALTEN = frozenset({
    "Begegnungshaeufigkeit", "Bedrohungswert", "Risiko", "Praesenzindex",
})

# Freitext, der sonst auf eine Zeile gequetscht wird.
_LANGTEXTSPALTEN = frozenset({
    "Meldung", "Erlaeuterung", "Parameter", "Riskanteste Gegnerauswahl",
    "Gegnerische Auswahl", "Auswahl", "Betroffen", "Passt zu",
})


def _hoechster(serie: pd.Series) -> float:
    """Groesster Wert einer Spalte, oder 0 bei leerer bzw. leerer Spalte.

    ``max()`` liefert bei einer leeren oder durchgaengig leeren Spalte ``NaN``.
    Als Obergrenze eines Balkens waere das unbrauchbar -- und faellt erst in
    der Anzeige auf, wo niemand mehr nach der Ursache sucht.
    """
    groesster = serie.max()
    return 0.0 if pd.isna(groesster) else float(groesster)


def _balken(serie: pd.Series, muster: str, hoechstwert: float | None = None):
    """Balken in der Zelle, skaliert auf ``hoechstwert`` oder das Maximum."""
    grenze = hoechstwert if hoechstwert is not None else _hoechster(serie)
    return st.column_config.ProgressColumn(
        format=muster, min_value=0, max_value=max(grenze, 1.0))


def spaltenkonfiguration(df: pd.DataFrame) -> dict:
    """Formatvorgaben fuer die Spalten eines Datenrahmens.

    Unbekannte Spalten bleiben unberuehrt und behalten Streamlits Vorgabe --
    eine Seite kann damit jederzeit eine neue Spalte ausgeben, ohne hier zuerst
    einen Eintrag anlegen zu muessen.
    """
    konfiguration: dict = {}
    for spalte in df.columns:
        if not isinstance(spalte, str):
            continue
        werte = df[spalte]
        zahl = pd.api.types.is_numeric_dtype(werte)

        if spalte in _RANGSPALTEN and zahl:
            konfiguration[spalte] = st.column_config.NumberColumn(
                format="%d", width="small")
        elif spalte in _VORZEICHENSPALTEN and zahl:
            konfiguration[spalte] = st.column_config.NumberColumn(
                format=_VORZEICHENSPALTEN[spalte], width="small")
        elif spalte in _GANZZAHLSPALTEN and zahl:
            konfiguration[spalte] = st.column_config.NumberColumn(
                format="%d", width="small")
        elif spalte in _NACHKOMMA and zahl:
            konfiguration[spalte] = st.column_config.NumberColumn(
                format=_NACHKOMMA[spalte], width="small")
        elif zahl and (spalte in _ANTEILSSPALTEN or spalte.endswith("(%)")):
            # Ueber 100 kann der feste Balken nicht hinaus; ein solcher Wert
            # bliebe stumm bei voller Laenge stehen. Dann lieber eine Zahl.
            konfiguration[spalte] = (
                _balken(werte, "%.1f %%", hoechstwert=100.0)
                if _hoechster(werte) <= 100
                else st.column_config.NumberColumn(format="%.1f %%")
            )
        elif spalte in _INDEXSPALTEN and zahl:
            konfiguration[spalte] = _balken(werte, "%.1f")
        elif spalte in _LANGTEXTSPALTEN:
            konfiguration[spalte] = st.column_config.TextColumn(width="large")

    return konfiguration


def tabelle(df: pd.DataFrame, hide_index: bool = True, **kwargs) -> None:
    """Gibt einen Datenrahmen mit den Formatvorgaben des Designsystems aus.

    Ersetzt den unmittelbaren Aufruf von ``st.dataframe`` in den Seitenmodulen,
    damit dieselbe Spalte auf jeder Seite gleich aussieht.
    """
    st.dataframe(df, column_config=spaltenkonfiguration(df), width="stretch",
                 hide_index=hide_index, **kwargs)


def seitenkopf(titel: str, aufgabe: str, stand: str = "") -> None:
    """Einheitlicher Seitenkopf mit Titel, Aufgabe und Datenstand.

    Jede Seite beantwortet genau eine Frage. Sie im Kopf zu nennen erspart es,
    die Aufgabe aus den Steuerelementen zu erschliessen -- und macht im
    Team-Preview den Unterschied, wo rund 60 Sekunden bleiben.
    """
    st.markdown(
        f"<div class='seitenkopf'><h1>{titel}</h1>"
        f"<div class='aufgabe'>{aufgabe}</div>"
        + (f"<div class='stand'>{stand}</div>" if stand else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def datenstand(conn, kampfformat: str | None = None, tag: str | None = None) -> str:
    """Einzeiler ueber die Datengrundlage, fuer den Seitenkopf."""
    basis = kpi.datenbasis(conn)
    if not basis:
        return ""
    teile = [f"Pokemon Champions · Saison {basis.get('saison', '-')}",
             f"{basis.get('tage', 0)} Tage bis {basis.get('ende', '-')}"]
    if kampfformat:
        teile.append(kampfformat)
    if tag:
        teile.append(f"Berichtstag {tag}")
    return " · ".join(teile)


def befundzeile(stufe: str, text: str) -> str:
    """Zeile des Qualitaetsberichts, mit einem Punkt in der Farbe der Stufe."""
    farbe = design.STUFEN_FARBEN.get(stufe, design.GRAU_MITTE)
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

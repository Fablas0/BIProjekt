"""Seite: Trends.

Vier Blicke auf die Zeitachse: welche Typen die Meta tragen, welche Items sich
durchsetzen, wer neu aufgestiegen ist und wer sich dauerhaft oben haelt. Alles
auf der Zeitreihe, die erst das eigene Archiv moeglich macht -- die Quelle
selbst haelt nur rund zwei Wochen vor.

Jede Auswertung nennt ihre Kennzahl und deren Rechtfertigung; die Regeln dazu
stehen in :mod:`bi.analytics.trends`.
"""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from ..analytics import trends
from ..config import META_RANGGRENZE, TYP_DEUTSCH, TYP_FARBEN, sprite_url
from . import design
from .komponenten import (
    hinweis_leere_datenbank,
    hole_verbindung,
    kopfauswahl,
    seitenkopf,
)


def zeichne() -> None:
    conn = hole_verbindung()
    seitenkopf("Trends",
               "Typen, Items, Neuzugaenge und Dauerbrenner im Zeitverlauf")

    from ..analytics import kpi
    if not kpi.verfuegbare_formate(conn):
        hinweis_leere_datenbank()
        return

    kampfformat, _ = kopfauswahl(conn, "trends", mit_tag=False)

    _typen(conn, kampfformat)
    _items(conn, kampfformat)
    spalten = st.columns(2)
    with spalten[0]:
        _neuzugaenge(conn, kampfformat)
    with spalten[1]:
        _spitzenreiter(conn, kampfformat)


def _typen(conn, kampfformat: str) -> None:
    st.markdown("### Starke Typen ueber die Zeit")
    verlauf = trends.typenstaerke_verlauf(conn, kampfformat=kampfformat)
    if verlauf.empty:
        st.caption("Keine Daten.")
        return

    bewegung = trends.typen_bewegung(conn, kampfformat=kampfformat)
    interessant = set(bewegung.loc[bewegung["veraenderung"] != 0, "typ"]) | set(
        bewegung.nlargest(6, "ende")["typ"])
    df = verlauf.loc[verlauf["typ"].isin(interessant)].copy()
    df["typ_deutsch"] = df["typ"].map(lambda t: TYP_DEUTSCH.get(t, t))

    figur = px.line(
        df, x="datum_iso", y="vertreter", color="typ",
        color_discrete_map=TYP_FARBEN, markers=True,
        labels={"datum_iso": "", "vertreter": f"Vertreter in den besten {META_RANGGRENZE}",
                "typ": "Typ"})
    figur.update_layout(height=380, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(figur, width="stretch")

    auf = bewegung.loc[bewegung["veraenderung"] > 0]
    ab = bewegung.loc[bewegung["veraenderung"] < 0]
    if not auf.empty or not ab.empty:
        teile = []
        if not auf.empty:
            teile.append("Im Aufwind: " + ", ".join(
                f"{TYP_DEUTSCH.get(z.typ, z.typ)} (+{z.veraenderung})"
                for z in auf.itertuples()))
        if not ab.empty:
            teile.append("Im Rueckgang: " + ", ".join(
                f"{TYP_DEUTSCH.get(z.typ, z.typ)} ({z.veraenderung})"
                for z in ab.itertuples()))
        st.caption(" · ".join(teile))
    st.caption(
        "Gezaehlt werden Vertreter je Typ in der Spitzengruppe -- eine "
        "Mengenoperation, die auf Rangdaten zulaessig ist. Ein 'mittlerer Rang "
        "je Typ' waere es nicht."
    )


def _items(conn, kampfformat: str) -> None:
    st.markdown("### Item-Nutzung")
    spalten = st.columns([1, 1])

    with spalten[0]:
        aktuell = trends.item_nutzung(conn, kampfformat)
        if aktuell.empty:
            st.caption("Keine Daten.")
            return
        st.markdown("**Meistgetragen am juengsten Tag**")
        st.dataframe(
            aktuell.head(12).rename(columns={
                "bezeichnung": "Item", "wirkung_klasse": "Wirkung",
                "traeger": "Traeger", "mittlerer_anteil": "Anteil im Set (%)"}),
            hide_index=True, height=380)

    with spalten[1]:
        verlauf = trends.item_nutzung_verlauf(conn, kampfformat=kampfformat)
        if not verlauf.empty:
            st.markdown("**Traegerzahl im Zeitverlauf**")
            figur = px.line(verlauf, x="datum_iso", y="traeger", color="bezeichnung",
                            markers=True,
                            color_discrete_sequence=design.DIAGRAMM_FOLGE,
                            labels={"datum_iso": "", "traeger": "Traeger",
                                    "bezeichnung": "Item"})
            figur.update_layout(height=380, margin={"l": 10, "r": 10, "t": 10, "b": 10})
            st.plotly_chart(figur, width="stretch")

    st.caption(
        "Gezaehlt wird, bei wie vielen Pokemon das Item an erster Stelle steht. "
        "Der mittlere Anteil ist zulaessig, weil die Merkmalsanteile echte "
        "Anteile sind -- anders als die Nutzungsraenge."
    )


def _neuzugaenge(conn, kampfformat: str) -> None:
    st.markdown("### Neu in der Meta")
    neu = trends.neuzugaenge(conn, kampfformat=kampfformat)
    if neu.empty:
        st.caption(f"Kein Pokemon ist im geladenen Zeitraum neu in die besten "
                   f"{META_RANGGRENZE} aufgestiegen.")
        return
    for zeile in neu.head(6).itertuples():
        spalten = st.columns([1, 4])
        with spalten[0]:
            st.image(sprite_url(int(zeile.pokedex_id)), width=64)
        with spalten[1]:
            stand = (f"aktuell Rang {int(zeile.aktueller_rang)}"
                     if zeile.noch_oben else "inzwischen wieder darunter")
            st.markdown(f"**{zeile.anzeigename}** — oben seit {zeile.erster_tag_oben}, "
                        f"bester Rang {zeile.bester_rang}, {stand}")
    st.caption("Neu heisst: der erste Tag in der Spitzengruppe liegt nach dem "
               "ersten geladenen Tag. Wer von Anfang an oben stand, ist "
               "etabliert, nicht neu.")


def _spitzenreiter(conn, kampfformat: str) -> None:
    st.markdown("### Dauerhaft stark")
    dauer = trends.spitzenreiter(conn, kampfformat=kampfformat)
    if dauer.empty:
        st.caption("Keine Daten.")
        return
    st.dataframe(
        dauer.head(10)[["anzeigename", "tage_in_top", "anteil_tage",
                        "bester_rang", "aktueller_rang", "bestaendigkeit"]]
        .rename(columns={
            "anzeigename": "Pokemon", "tage_in_top": "Tage oben",
            "anteil_tage": "Anteil (%)", "bester_rang": "Bester Rang",
            "aktueller_rang": "Aktuell", "bestaendigkeit": "Einordnung"}),
        hide_index=True, height=390)
    st.caption("Verweildauer in den besten 10 -- eine Zaehlung, kein Rechnen "
               "mit Raengen. Ob die Spitze insgesamt stabil ist, prueft H1.")

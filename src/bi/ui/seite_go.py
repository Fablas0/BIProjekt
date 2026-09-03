"""Seite: GO-Meta.

Die PvP-Ranglisten von Pokemon GO je Liga -- vollstaendig, durchsuchbar, und
mit dem Abgleich gegen die eigene Box: Welche meiner Pokemon stehen gerade
in einer Liga weit oben?

Die Kennzahl ist der pvpoke-Score (0-100), kardinal. Anders als bei den
Champions-Raengen sind hier Differenzen zulaessig; die Seite zeigt deshalb
auch, wie weit ein eigenes Pokemon von der Spitze entfernt ist.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .. import nutzerdaten
from ..analytics import einsatz
from ..config import TYP_FARBEN
from . import anmeldung
from .komponenten import (
    hole_verbindung,
    kennzahl_kachel,
    seitenkopf,
    tabelle,
)


def zeichne() -> None:
    conn = hole_verbindung()
    nutzerdaten.anhaengen(conn)
    seitenkopf("GO-Meta",
               "Die PvP-Ranglisten je Liga -- und welche eigenen Pokemon darin stehen")

    if not conn.execute("SELECT EXISTS(SELECT 1 FROM Fact_GO_Meta)").fetchone()[0]:
        st.info(
            "**Die GO-Rangliste ist noch nicht geladen.** Der taegliche ETL-Lauf "
            "holt sie von pvpoke ohne weitere Einrichtung; die Cloud baut sie aus "
            "dem Archiv beim Start auf. Kopfstart: `python -m scripts.etl_lauf`."
        )
        return

    df = pd.read_sql("""
        SELECT liga, liga_name, wp_grenze, quell_id, slug,
               COALESCE(anzeigename, quell_id) AS name, name_de,
               score, rang, ist_schatten, typ1, typ2, datum_iso
        FROM V_GO_Meta
        WHERE zeit_sk = (SELECT MAX(zeit_sk) FROM Fact_GO_Meta)
        ORDER BY liga, rang
    """, conn)
    stand = df["datum_iso"].iloc[0] if not df.empty else "-"
    st.caption(f"Stand der Rangliste: {stand} · Quelle: pvpoke · Score 0-100, kardinal")

    ligen = df.drop_duplicates("liga")[["liga", "liga_name", "wp_grenze"]]
    kacheln = st.columns(len(ligen))
    for spalte, (_, liga) in zip(kacheln, ligen.iterrows(), strict=False):
        with spalte:
            n = int((df["liga"] == liga["liga"]).sum())
            spitze = df.loc[df["liga"] == liga["liga"]].iloc[0]
            st.markdown(kennzahl_kachel(
                liga["liga_name"], str(n),
                f"Pokemon gewertet · Spitze: {spitze['name']} ({spitze['score']:.1f})"),
                unsafe_allow_html=True)

    nutzer = anmeldung.angemeldeter_nutzer(conn)
    box_slugs = (
        sorted({e["slug"] for e in nutzerdaten.box_lesen(conn, nutzer.nutzer_id)})
        if nutzer else [])

    rangliste, eigene, typen = st.tabs(["Rangliste", "Eigene Box in GO", "Typen je Liga"])
    with rangliste:
        _rangliste(df, ligen, box_slugs)
    with eigene:
        _eigene(conn, df, box_slugs)
    with typen:
        _typen(df, ligen)


def _rangliste(df: pd.DataFrame, ligen: pd.DataFrame, box_slugs: list[str]) -> None:
    liganamen = dict(zip(ligen["liga"], ligen["liga_name"], strict=True))
    spalten = st.columns([1, 2, 1])
    with spalten[0]:
        liga = st.selectbox("Liga", list(liganamen), key="go_liga",
                            format_func=lambda schluessel: liganamen[schluessel])
    with spalten[1]:
        suche = st.text_input("Suche (englisch oder deutsch)", key="go_suche")
    with spalten[2]:
        ohne_schatten = st.checkbox("Ohne Schattenformen", value=False, key="go_ohne_schatten")

    auswahl = df.loc[df["liga"] == liga].copy()
    if ohne_schatten:
        auswahl = auswahl.loc[auswahl["ist_schatten"] == 0]
    if suche:
        muster = suche.strip().lower()
        auswahl = auswahl.loc[
            auswahl["name"].str.lower().str.contains(muster, regex=False)
            | auswahl["name_de"].fillna("").str.lower().str.contains(muster, regex=False)]

    auswahl["In der Box"] = auswahl["slug"].isin(box_slugs).map({True: "ja", False: ""})
    auswahl["Form"] = auswahl["ist_schatten"].map({0: "", 1: "Schatten"})
    ausgabe = auswahl[["rang", "name", "name_de", "typ1", "typ2", "score", "Form", "In der Box"]]
    ausgabe = ausgabe.rename(columns={
        "rang": "Rang", "name": "Pokemon", "name_de": "Deutsch", "typ1": "Typ 1",
        "typ2": "Typ 2", "score": "Score"})
    tabelle(ausgabe, height=560)
    st.caption(
        f"{len(auswahl)} Eintraege. Der Score stammt aus Kampfsimulationen von pvpoke; "
        "der Rang ist daraus abgeleitet. Schattenformen sind eine GO-eigene Mechanik "
        "und auf das Grund-Pokemon der konformen Dimension abgebildet."
    )


def _eigene(conn, df: pd.DataFrame, box_slugs: list[str]) -> None:
    if not box_slugs:
        st.info("Die Box ist leer -- oder niemand ist angemeldet. Im *PC-System* lassen "
                "sich eigene Pokemon ablegen; hier erscheint dann ihr Stand je Liga.")
        return

    treffer = df.loc[df["slug"].isin(box_slugs) & (df["ist_schatten"] == 0)].copy()
    urteile = einsatz.pruefen(conn, box_slugs)
    spielbar = sum(1 for u in urteile.values()
                   if (b := u.befund("Pokemon GO")) and b.urteil in ("meta", "spielbar"))

    kacheln = st.columns(3)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Eigene Pokemon", str(len(box_slugs)), "in der Box"),
                    unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel(
            "In einer Liga gewertet", str(spielbar),
            "davon in mindestens einer Rangliste",
            bedeutung="guenstig" if spielbar else "neutral"), unsafe_allow_html=True)
    with kacheln[2]:
        stark = sum(1 for u in urteile.values()
                    if (b := u.befund("Pokemon GO")) and b.urteil == "meta")
        st.markdown(kennzahl_kachel(
            f"Score ab {einsatz.GO_EINSATZ_SCORE:.0f}", str(stark),
            "in ihrer besten Liga -- das spielt die Szene",
            bedeutung="guenstig" if stark else "neutral"), unsafe_allow_html=True)

    if treffer.empty:
        st.caption("Keines der eigenen Pokemon steht derzeit in einer GO-Rangliste.")
        return

    spitze = df.loc[df["ist_schatten"] == 0].groupby("liga")["score"].max()
    treffer["Abstand zur Spitze"] = (treffer["liga"].map(spitze) - treffer["score"]).round(1)
    ausgabe = treffer[["name", "liga_name", "rang", "score", "Abstand zur Spitze"]].rename(
        columns={"name": "Pokemon", "liga_name": "Liga", "rang": "Rang", "score": "Score"})
    tabelle(ausgabe.sort_values(["Pokemon", "Score"], ascending=[True, False]))
    st.caption(
        "Der Abstand zur Spitze ist eine Differenz von Scores -- zulaessig, weil der "
        "Score kardinal ist. Bei den Champions-Raengen gaebe es diese Spalte nicht."
    )


def _typen(df: pd.DataFrame, ligen: pd.DataFrame) -> None:
    st.markdown("**Typen in den besten 50 je Liga**")
    spitze = df.loc[(df["rang"] <= 50) & (df["ist_schatten"] == 0)]
    zaehlung = spitze.groupby(["liga_name", "typ1"]).size().rename("Pokemon").reset_index()
    if zaehlung.empty:
        st.caption("Zu wenige aufgeloeste Pokemon fuer die Typenzaehlung.")
        return
    figur = px.bar(zaehlung, x="liga_name", y="Pokemon", color="typ1",
                   color_discrete_map=TYP_FARBEN,
                   labels={"liga_name": "", "typ1": "Typ"})
    figur.update_layout(height=420, legend={"orientation": "h", "y": -0.15})
    st.plotly_chart(figur, width="stretch")
    st.caption(
        "Gezaehlt werden Vertreter je Erst-Typ in der Spitzengruppe -- dieselbe "
        "Methode wie im Champions-Trend, damit die Spielformen vergleichbar bleiben."
    )

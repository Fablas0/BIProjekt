"""Seite: Sammelkartenspiel.

Zwei Blicke auf dieselben Karten: die **Turnier-Meta** (welche Decks werden
gespielt, und wo?) und die **eigene Sammlung**. Die Bruecke zwischen beiden
ist das Leit-Pokemon eines Decks: eine Karte, die einem Pokemon der
konformen Dimension zugeordnet ist, laesst sich gegen die Decks halten, die
dieses Pokemon anfuehren.

Die Sammlung ist Freitext, weil es keine angebundene Kartenstammdatenquelle
gibt (siehe :mod:`bi.sammlung`). Die Turnier-Meta braucht die
Limitless-Strecke und damit einen API-Schluessel; ohne ihn erklaert sich die
Luecke an Ort und Stelle, und die Sammlung funktioniert trotzdem.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .. import nutzerdaten, sammlung
from . import anmeldung, design
from .komponenten import (
    hole_verbindung,
    kennzahl_kachel,
    name_mit_deutsch,
    seitenkopf,
    tabelle,
)


def zeichne() -> None:
    conn = hole_verbindung()
    nutzerdaten.anhaengen(conn)
    seitenkopf("Sammelkartenspiel",
               "Turnierdecks und Laendervergleich -- und die eigene Sammlung mit "
               "Bruecke zur Meta")

    tcg_geladen = conn.execute("SELECT EXISTS(SELECT 1 FROM Fact_TCG_Meta)").fetchone()[0]

    meta, eigene = st.tabs(["Turnier-Meta", "Meine Sammlung"])
    with meta:
        if tcg_geladen:
            _meta(conn)
        else:
            st.info(
                "**Die Turnierdaten sind noch nicht geladen.** Die Limitless-Strecke "
                "verlangt einen kostenlosen API-Schluessel (`VGC_BI_TCG_SCHLUESSEL`, "
                "Registrierung bei play.limitlesstcg.com). Ohne ihn ueberspringt der "
                "Lauf genau diese Strecke und weist das im Qualitaetsbericht aus. Die "
                "Sammlung nebenan funktioniert davon unabhaengig."
            )
    with eigene:
        _sammlung(conn, tcg_geladen)


# --------------------------------------------------------------------------
# Turnier-Meta
# --------------------------------------------------------------------------

def _meta(conn) -> None:
    df = pd.read_sql("""
        SELECT deck_name, leit_slug, region, markt, iso2, datum_iso,
               SUM(spieler) AS spieler, SUM(top8) AS top8
        FROM V_TCG_Meta GROUP BY deck_name, leit_slug, region, markt, iso2, datum_iso
    """, conn)
    if df.empty:
        return

    kacheln = st.columns(4)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Decks", str(df["deck_name"].nunique()),
                                    "Archetypen in den Standings"), unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("Spieler", f"{int(df['spieler'].sum()):,}",
                                    "gezaehlte Turnierteilnahmen"), unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("Laender", str(df["iso2"].nunique()),
                                    f"in {df['region'].nunique()} Regionen"),
                    unsafe_allow_html=True)
    with kacheln[3]:
        st.markdown(kennzahl_kachel("Turniertage", str(df["datum_iso"].nunique()),
                                    f"bis {df['datum_iso'].max()}"), unsafe_allow_html=True)

    je_deck = (df.groupby("deck_name")[["spieler", "top8"]].sum()
               .sort_values("spieler", ascending=False))
    je_deck["Top-8-Quote (%)"] = (100 * je_deck["top8"] / je_deck["spieler"]).round(1)

    spalten = st.columns([1, 1])
    with spalten[0]:
        st.markdown("**Meistgespielte Archetypen**")
        figur = px.bar(je_deck["spieler"].head(12).iloc[::-1], orientation="h",
                       labels={"value": "Spieler", "deck_name": ""})
        figur.update_layout(showlegend=False, height=420)
        figur.update_traces(marker_color=design.BLAU_HELL)
        st.plotly_chart(figur, width="stretch")
    with spalten[1]:
        st.markdown("**Deckwahl nach Region**")
        regional = df.loc[df["deck_name"].isin(je_deck.index[:6])]
        regional = regional.groupby(["region", "deck_name"])["spieler"].sum().reset_index()
        figur = px.bar(regional, x="region", y="spieler", color="deck_name",
                       labels={"spieler": "Spieler", "region": "", "deck_name": "Deck"},
                       color_discrete_sequence=design.DIAGRAMM_FOLGE)
        figur.update_layout(height=420)
        st.plotly_chart(figur, width="stretch")

    st.markdown("**Alle Decks**")
    tabelle(je_deck.reset_index().rename(columns={
        "deck_name": "Deck", "spieler": "Spieler", "top8": "Top 8"}))
    st.caption(
        "Spieler und Top-8-Platzierungen sind Zaehlungen -- Summen und Anteile sind "
        "zulaessig. Ob die Unterschiede zwischen den Regionen mehr sind als Zufall, "
        "prueft H11 im Hypothesenkatalog."
    )


# --------------------------------------------------------------------------
# Eigene Sammlung
# --------------------------------------------------------------------------

def _sammlung(conn, tcg_geladen: bool) -> None:
    nutzer = anmeldung.verlangen(conn)
    if nutzer is None:
        return

    karten = sammlung.karten_lesen(conn, nutzer.nutzer_id)
    zahlen = sammlung.bilanz(karten)

    kacheln = st.columns(4)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Karten", str(zahlen["karten"]), "verschiedene"),
                    unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("Exemplare", str(zahlen["exemplare"]), "insgesamt"),
                    unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("Saetze", str(zahlen["saetze"]), "Erweiterungen"),
                    unsafe_allow_html=True)
    with kacheln[3]:
        st.markdown(kennzahl_kachel(
            "Fuehren ein Meta-Deck an", str(zahlen["im_meta"]),
            "Karten, deren Pokemon ein Turnierdeck leitet" if tcg_geladen
            else "erst mit geladenen Turnierdaten",
            bedeutung="guenstig" if zahlen["im_meta"] else "neutral"),
            unsafe_allow_html=True)

    with st.expander("Karte hinzufuegen", expanded=not karten):
        _karte_erfassen(conn, nutzer)

    if not karten:
        st.caption("Die Sammlung ist leer.")
        return

    uebersicht = pd.DataFrame([{
        "Satz": k["satz"], "Nr.": k.get("nummer") or "", "Karte": k["name"],
        "Pokemon": k.get("anzeigename") or "", "Anzahl": int(k["anzahl"]),
        "Seltenheit": k.get("seltenheit") or "", "Zustand": k.get("zustand") or "",
        "Meta-Deck": k.get("meta_decks") or "",
    } for k in karten])
    tabelle(uebersicht)

    with st.expander("Karte entfernen"):
        auswahl = st.selectbox(
            "Karte", karten, key="karte_entfernen",
            format_func=lambda k: f"{k['satz']} {k.get('nummer') or ''} · {k['name']}")
        if auswahl and st.button("Entfernen", key="karte_entfernen_knopf"):
            sammlung.karte_loeschen(conn, nutzer.nutzer_id, auswahl["karte_id"])
            st.rerun()


def _karte_erfassen(conn, nutzer) -> None:
    pokemon = pd.read_sql(
        "SELECT slug, anzeigename FROM Dim_Pokemon WHERE ist_aktuell = 1 ORDER BY anzeigename",
        conn)
    namen = dict(zip(pokemon["anzeigename"], pokemon["slug"], strict=True))

    zugeordnet = st.selectbox(
        "Pokemon auf der Karte (optional, fuer die Bruecke zur Meta)", list(namen),
        index=None, key="karte_pokemon", format_func=name_mit_deutsch,
        placeholder="Kein Pokemon oder Trainerkarte")
    with st.form("karte_anlegen"):
        spalten = st.columns([2, 1, 2])
        with spalten[0]:
            satz = st.text_input("Satz (Erweiterung)", placeholder="z. B. Obsidianflammen")
        with spalten[1]:
            nummer = st.text_input("Nummer", placeholder="125/197")
        with spalten[2]:
            name = st.text_input("Kartenname", placeholder="Glurak-ex")
        spalten = st.columns(3)
        with spalten[0]:
            anzahl = st.number_input("Anzahl", min_value=1, value=1)
        with spalten[1]:
            seltenheit = st.selectbox("Seltenheit", list(sammlung.SELTENHEITEN), index=None,
                                      placeholder="Nicht angegeben")
        with spalten[2]:
            zustand = st.selectbox("Zustand", list(sammlung.ZUSTAENDE), index=None,
                                   placeholder="Nicht angegeben")
        notiz = st.text_input("Notiz (optional)")
        if st.form_submit_button("In die Sammlung", type="primary"):
            try:
                sammlung.karte_speichern(conn, nutzer.nutzer_id, {
                    "satz": satz, "nummer": nummer or None, "name": name,
                    "slug": namen.get(zugeordnet), "anzahl": int(anzahl),
                    "seltenheit": seltenheit, "zustand": zustand, "notiz": notiz or None,
                })
                st.rerun()
            except ValueError as fehler:
                st.error(str(fehler))

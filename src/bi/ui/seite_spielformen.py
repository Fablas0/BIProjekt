"""Seite: Spielformen.

Stellt die drei Spielformen nebeneinander: das Wettkampf-Metagame von Pokemon
Champions, die PvP-Meta von Pokemon GO und die Turnier-Meta des
Sammelkartenspiels -- einschliesslich des Laendervergleichs, den nur die
TCG-Quelle tragen kann, weil nur sie den Ort des Spielers mitliefert.

Die Seite ist zugleich die Sichtbarmachung einer Modellentscheidung: alle drei
Quellen zeigen ueber die **konforme Pokemon-Dimension** auf dieselben Pokemon.
Erst dadurch ist die Frage beantwortbar, ob ein starkes VGC-Pokemon auch in GO
stark ist -- statistisch geprueft als H13 im Hypothesenkatalog.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..config import TYP_FARBEN
from . import design
from .komponenten import hole_verbindung, kennzahl_kachel, seitenkopf


def zeichne() -> None:
    conn = hole_verbindung()
    seitenkopf("Spielformen",
               "Dieselben Pokemon, drei Regelwerke: VGC, Pokemon GO und das "
               "Sammelkartenspiel im Vergleich")

    go_geladen = conn.execute("SELECT COUNT(*) FROM Fact_GO_Meta").fetchone()[0]
    tcg_geladen = conn.execute("SELECT COUNT(*) FROM Fact_TCG_Meta").fetchone()[0]

    kacheln = st.columns(3)
    with kacheln[0]:
        vgc = conn.execute("SELECT COUNT(DISTINCT pokemon_sk) FROM Fact_Champions_Usage"
                           ).fetchone()[0]
        st.markdown(kennzahl_kachel("VGC (Champions)", str(vgc),
                                    "Pokemon im Ranked, ordinal"),
                    unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("Pokemon GO", str(go_geladen),
                                    "Bewertungssaetze, kardinal (Score 0-100)"),
                    unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("Sammelkartenspiel", str(tcg_geladen),
                                    "Zaehlsaetze Deck x Land, kardinal"),
                    unsafe_allow_html=True)

    st.caption(
        "Drei Quellen, drei Messniveaus: Champions liefert einen **Rang** "
        "(ordinal), pvpoke einen **Score** (kardinal), Limitless eine "
        "**Personenzaehlung** (kardinal). Welche Kennzahl zulaessig ist, "
        "entscheidet das Messniveau -- es steht als Merkmal an der Quelle "
        "(Dim_Quelle) und nicht im Code."
    )

    if not go_geladen and not tcg_geladen:
        st.info(
            "**Die Spielform-Quellen sind noch nicht geladen.**\n\n"
            "Beide werden vom taeglichen ETL-Lauf mitgeholt und wie die "
            "Champions-Daten im versionierten Archiv gesichert; die Cloud "
            "baut sie daraus beim Start auf. Pokemon GO braucht keine "
            "Einrichtung, das Sammelkartenspiel einen API-Schluessel "
            "(`VGC_BI_TCG_SCHLUESSEL`, kostenlos bei play.limitlesstcg.com). "
            "Kopfstart: `python -m scripts.etl_lauf`."
        )
        return

    # Fehlt nur eine der beiden Quellen, erklaert sich die Luecke an Ort und
    # Stelle -- eine kommentarlos fehlende Spielform liest sich sonst als
    # kaputte Seite, nicht als fehlender Schluessel.
    if go_geladen:
        _go_bereich(conn)
    else:
        st.info(
            "**Pokemon GO ist noch nicht geladen.** Die pvpoke-Rangliste wird "
            "vom naechsten ETL-Lauf ohne weitere Einrichtung mitgeholt und im "
            "Archiv gesichert."
        )
    if tcg_geladen:
        _tcg_bereich(conn)
    else:
        st.info(
            "**Das Sammelkartenspiel ist noch nicht geladen.** Die "
            "Limitless-Turnierdaten verlangen einen kostenlosen API-Schluessel "
            "(`VGC_BI_TCG_SCHLUESSEL`, Registrierung bei play.limitlesstcg.com). "
            "Ohne ihn ueberspringt der Lauf genau diese Strecke und weist das "
            "im Qualitaetsbericht aus -- die uebrigen Spielformen bleiben "
            "davon unberuehrt. Damit entfaellt hier auch der Laendervergleich "
            "(H11), denn nur diese Quelle liefert den Ort des Spielers."
        )
    if go_geladen:
        _bruecke(conn)


# --------------------------------------------------------------------------
# Pokemon GO
# --------------------------------------------------------------------------

def _go_bereich(conn) -> None:
    st.markdown("### Pokemon GO: PvP-Meta je Liga")

    df = pd.read_sql("""
        SELECT liga_name, quell_id, COALESCE(anzeigename, quell_id) AS name,
               score, rang, ist_schatten, typ1
        FROM V_GO_Meta
        WHERE zeit_sk = (SELECT MAX(zeit_sk) FROM Fact_GO_Meta)
        ORDER BY liga_name, rang
    """, conn)
    if df.empty:
        return

    ligen = df["liga_name"].unique().tolist()
    spalten = st.columns(len(ligen))
    for spalte, liga in zip(spalten, ligen, strict=True):
        with spalte:
            st.markdown(f"**{liga}**")
            beste = df.loc[df["liga_name"] == liga].head(10)
            beste = beste.assign(
                Schatten=beste["ist_schatten"].map({0: "", 1: "Schatten"}))
            st.dataframe(
                beste[["rang", "name", "score", "Schatten"]]
                .rename(columns={"rang": "Rang", "name": "Pokemon", "score": "Score"}),
                hide_index=True, height=390)

    st.caption(
        "Der Score (0-100) stammt aus Kampfsimulationen von pvpoke; der Rang ist "
        "daraus abgeleitet. Schattenformen sind eine GO-eigene Mechanik und auf "
        "das Grund-Pokemon der konformen Dimension abgebildet."
    )


# --------------------------------------------------------------------------
# Sammelkartenspiel
# --------------------------------------------------------------------------

def _tcg_bereich(conn) -> None:
    st.markdown("### Sammelkartenspiel: Decks und Laender")

    df = pd.read_sql("""
        SELECT deck_name, region, SUM(spieler) AS spieler, SUM(top8) AS top8
        FROM V_TCG_Meta GROUP BY deck_name, region
    """, conn)
    if df.empty:
        return

    gesamt = df.groupby("deck_name")["spieler"].sum().nlargest(12)
    spalten = st.columns([1, 1])

    with spalten[0]:
        st.markdown("**Meistgespielte Archetypen**")
        figur = px.bar(gesamt.iloc[::-1], orientation="h",
                       labels={"value": "Spieler", "deck_name": ""})
        figur.update_layout(showlegend=False, height=420,
                            margin={"l": 10, "r": 10, "t": 10, "b": 10})
        figur.update_traces(marker_color=design.BLAU_HELL)
        st.plotly_chart(figur, width="stretch")

    with spalten[1]:
        st.markdown("**Deckwahl nach Region**")
        regional = df.loc[df["deck_name"].isin(gesamt.index[:6])]
        figur = px.bar(regional, x="region", y="spieler", color="deck_name",
                       labels={"spieler": "Spieler", "region": "", "deck_name": "Deck"},
                       color_discrete_sequence=design.DIAGRAMM_FOLGE)
        figur.update_layout(height=420, margin={"l": 10, "r": 10, "t": 10, "b": 10})
        st.plotly_chart(figur, width="stretch")

    st.caption(
        "Ob die Unterschiede zwischen den Regionen mehr sind als Zufall, prueft "
        "H11 im Hypothesenkatalog -- als Chi-Quadrat-Test auf der Kreuztabelle, "
        "nicht mit blossem Auge."
    )


# --------------------------------------------------------------------------
# Spieluebergreifende Bruecke
# --------------------------------------------------------------------------

def _bruecke(conn) -> None:
    st.markdown("### Die Bruecke: dieselben Pokemon in VGC und GO")

    df = pd.read_sql("""
        SELECT u.anzeigename, u.rang AS vgc_rang, g.score AS go_score, u.typ1
        FROM V_Usage_Aktuell u
        JOIN V_GO_Meta g ON g.slug = u.slug
        WHERE u.kampfformat = 'Doubles' AND g.liga = 'master' AND g.ist_schatten = 0
          AND g.zeit_sk = (SELECT MAX(zeit_sk) FROM Fact_GO_Meta)
    """, conn)
    if df.empty:
        st.caption("Noch keine gemeinsame Schnittmenge zwischen VGC und GO geladen.")
        return

    figur = px.scatter(
        df, x="vgc_rang", y="go_score", color="typ1", hover_name="anzeigename",
        color_discrete_map=TYP_FARBEN,
        labels={"vgc_rang": "VGC-Rang (klein = stark)",
                "go_score": "GO-Score (gross = stark)", "typ1": "Typ"})
    figur.update_layout(height=460, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(figur, width="stretch")

    st.caption(
        f"{len(df)} Pokemon stehen in beiden Spielen zur Wertung. Ob sich Staerke "
        "uebertraegt, prueft H13 im Hypothesenkatalog: ein negativer "
        "Rangkorrelationskoeffizient hiesse ja -- kleiner Rang und hoher Score "
        "gingen zusammen."
    )

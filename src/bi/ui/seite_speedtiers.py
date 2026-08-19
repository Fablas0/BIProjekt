"""Seite: Speed-Tiers.

Wertet die tatsaechlich gespielten Initiativwerte aus. Grundlage ist nicht der
Basiswert, sondern der aus Wesen und Fleisspunkten berechnete Wert des konkret
gespielten Exemplars -- die einzige Groesse, die im Kampf zaehlt.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ..analytics import kpi, speed
from ..config import sprite_url
from ..stats import SZENARIEN
from . import design
from .komponenten import (
    hinweis_leere_datenbank,
    hole_verbindung,
    kennzahl_kachel,
    kopfauswahl,
    name_mit_deutsch,
    seitenkopf,
    tabelle,
)


def zeichne() -> None:
    conn = hole_verbindung()

    seitenkopf("Speed-Tiers", "Wer handelt zuerst?")
    if not kpi.verfuegbare_formate(conn):
        hinweis_leere_datenbank()
        return

    spread_zeilen = conn.execute(
        "SELECT COUNT(*) FROM Fact_Champions_Merkmal WHERE kategorie = 'spread'"
    ).fetchone()[0]
    if spread_zeilen == 0:
        st.warning(
            "Es liegen noch keine Punkteverteilungen vor. Bitte unter "
            "*ETL & Datenqualitaet* die Champions-Daten laden."
        )
        return

    st.markdown(
        "Die Zugreihenfolge entscheidet einen erheblichen Teil der Partien. "
        "Massgeblich ist dabei **nicht der angezeigte Grundwert**, sondern der Wert "
        "des tatsaechlich gespielten Exemplars: Grundwert plus Statuspunkte, "
        "verrechnet mit dem Wesen."
    )

    kampfformat, monat = kopfauswahl(conn, "speed")
    if not monat:
        st.warning("Fuer dieses Format liegen keine Daten vor.")
        return

    tiers = speed.speed_tier_liste(conn, monat, kampfformat)
    if tiers.empty:
        st.info("Fuer diesen Tag liegen keine auswertbaren Verteilungen vor.")
        return

    verfuegbar = kpi.meta_uebersicht(conn, monat, kampfformat)
    team = st.multiselect(
        "Eigenes Team zum Vergleich (optional)",
        options=verfuegbar["anzeigename"].tolist(), max_selections=6,
        key="speed_team", format_func=name_mit_deutsch,
    )

    _zeige_eckwerte(tiers, verfuegbar)

    reiter = st.tabs([
        "Tier-Liste", "Team im Vergleich", "Szenarien", "Benchmark-Rechner",
        "Vorhersagbarkeit der Sets",
    ])

    with reiter[0]:
        _zeige_tierliste(tiers, team)
    with reiter[1]:
        _zeige_teamvergleich(conn, tiers, team, monat, kampfformat)
    with reiter[2]:
        _zeige_szenarien(conn, team, monat, kampfformat)
    with reiter[3]:
        _zeige_benchmark(conn, verfuegbar, monat, kampfformat)
    with reiter[4]:
        _zeige_vorhersagbarkeit(conn, monat, kampfformat)


# --------------------------------------------------------------------------

def _zeige_eckwerte(tiers: pd.DataFrame, meta: pd.DataFrame) -> None:
    """Kennzahlenzeile zur Initiative im Metagame."""
    schnellstes = tiers.iloc[0]
    median = int(tiers["speed_real"].median())

    # Wie stark weichen reale Werte von den Basiswerten ab? Das ist das
    # eigentliche Argument fuer diese Auswertung.
    mittlere_abweichung = float(
        (tiers["speed_real"] - tiers["speed_ohne_investition"]).mean())

    bizarroraum_anteil = 100 * tiers.loc[tiers["ist_bizarroraum_set"], "gewicht"].sum() / max(
        tiers["gewicht"].sum(), 1e-9)

    # Vier Beschreibungen des Metagames, keine Bewertung des eigenen Teams --
    # entsprechend traegt keine der Kacheln eine Aussage.
    spalten = st.columns(4)
    spalten[0].markdown(kennzahl_kachel(
        "Schnellstes Set", str(int(schnellstes["speed_real"])),
        f"{schnellstes['anzeigename']} ({schnellstes['wesen']})"),
        unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel(
        "Median des Metagames", str(median),
        "Haelfte der Sets liegt darunter"), unsafe_allow_html=True)
    spalten[2].markdown(kennzahl_kachel(
        "Gewinn durch Training", f"+{mittlere_abweichung:.0f}",
        "gegenueber dem Grundwert"), unsafe_allow_html=True)
    spalten[3].markdown(kennzahl_kachel(
        "Bizarroraum-Sets", f"{bizarroraum_anteil:.1f} %",
        "bewusst langsam gespielt"), unsafe_allow_html=True)


def _zeige_tierliste(tiers: pd.DataFrame, team: list[str]) -> None:
    """Die Initiativwerte des Metagames als gewichtete Verteilung."""
    verteilung = speed.tier_verteilung(tiers)

    abbildung = px.bar(
        verteilung, x="gewicht", y="band", orientation="h",
        labels={"gewicht": "Begegnungshaeufigkeit", "band": "Initiative"},
        title="Wo sich das Metagame ballt",
        color="gewicht", color_continuous_scale=design.VERLAUF_NEUTRAL,
        text_auto=".0f", height=max(420, 22 * len(verteilung)),
    )
    # Die Baender sind Texte; ohne ausdrueckliche Reihenfolge wuerden sie
    # alphabetisch sortiert und '20-29' erschiene hinter '180-189'.
    abbildung.update_layout(
        coloraxis_showscale=False,
        yaxis={
            "categoryorder": "array",
            "categoryarray": verteilung.sort_values("untergrenze")["band"].tolist(),
        },
    )
    st.plotly_chart(abbildung, width="stretch")

    st.caption(
        "Die Begegnungshaeufigkeit verrechnet die Nutzung des Pokemon mit dem Anteil "
        "des jeweiligen Sets. Ein Band mit hohem Wert bedeutet: genau dort steht viel "
        "Konkurrenz -- ein Punkt mehr Initiative kann hier den Unterschied machen."
    )

    st.markdown("#### Einzelne Sets")
    anzeige = tiers.copy()
    anzeige["Eigenes Team"] = anzeige["anzeigename"].isin(team)
    anzeige = anzeige.rename(columns={
        "anzeigename": "Pokemon", "speed_ohne_investition": "Grundwert",
        "kurzform": "Set", "speed_real": "Initiative",
        "set_anteil": "Anteil des Sets (%)", "usage_rang": "Meta-Rang",
        "gewicht": "Begegnungshaeufigkeit",
    })
    tabelle(
        anzeige[["Pokemon", "Grundwert", "Initiative", "Set",
                 "Anteil des Sets (%)", "Meta-Rang", "Begegnungshaeufigkeit",
                 "Eigenes Team"]],
        height=460,
    )


def _zeige_teamvergleich(conn, tiers: pd.DataFrame, team: list[str], monat: str,
                         kampfformat: str) -> None:
    """Einordnung der eigenen Pokemon in die Verteilung des Metagames."""
    if not team:
        st.info("Waehle oben ein Team aus, um es in die Verteilung einzuordnen.")
        return

    szenario = st.selectbox(
        "Szenario", list(SZENARIEN.keys()),
        format_func=lambda s: SZENARIEN[s].bezeichnung, key="speed_vergleich_szenario",
    )
    st.caption(SZENARIEN[szenario].erlaeuterung)

    einordnung = speed.team_einordnung(conn, team, monat, szenario, kampfformat)
    if einordnung.empty:
        st.warning("Fuer die Auswahl liegen keine Verteilungen vor.")
        return

    # Das Metagame ist hier Hintergrund, die eigenen Pokemon sind die Aussage.
    # Die Bezugslinien tragen deshalb die Farbe der Bedienelemente -- sie zeigen
    # die eigene Auswahl. Rot waere hier eine Bedrohung, die sie nicht sind.
    abbildung = go.Figure()
    abbildung.add_trace(go.Histogram(
        x=tiers["speed_real"], nbinsx=30, name="Metagame",
        marker_color=design.GRAU_FLAECHE, opacity=0.75,
    ))
    for _, zeile in einordnung.iterrows():
        abbildung.add_vline(
            x=zeile["Initiative"], line_dash="dash", line_color=design.BLAU_HELL,
            annotation_text=f"{zeile['Pokemon']} ({zeile['Initiative']})",
            annotation_position="top",
        )
    abbildung.update_layout(
        title=f"Team im Vergleich zur Initiative-Verteilung — {SZENARIEN[szenario].bezeichnung}",
        xaxis_title="Initiative (Stufe 50)", yaxis_title="Anzahl Sets",
        height=460, showlegend=False,
    )
    st.plotly_chart(abbildung, width="stretch")

    tabelle(einordnung)

    langsam = einordnung[einordnung["Ueberholt (%)"] < 30]
    if not langsam.empty and szenario == "normal":
        st.warning(
            "**Auf Unterstuetzung angewiesen:** " + ", ".join(langsam["Pokemon"]) +
            ". Diese Pokemon handeln in der Mehrzahl der Begegnungen zuletzt. Das ist "
            "unproblematisch, wenn es gewollt ist (Bizarroraum, defensive Rolle) -- "
            "sonst fehlt dem Team Initiative-Kontrolle."
        )


def _zeige_szenarien(conn, team: list[str], monat: str, kampfformat: str) -> None:
    """Vergleich aller Szenarien nebeneinander."""
    if not team:
        st.info("Waehle oben ein Team aus, um die Szenarien zu vergleichen.")
        return

    uebersicht = speed.szenario_uebersicht(conn, team, monat, kampfformat)
    if uebersicht.empty:
        st.warning("Fuer die Auswahl liegen keine Verteilungen vor.")
        return

    abbildung = px.bar(
        uebersicht.sort_values("Ueberholt im Mittel (%)"),
        x="Ueberholt im Mittel (%)", y="Szenario", orientation="h",
        labels={"Ueberholt im Mittel (%)": "Anteil des Metagames, der ueberholt wird (%)",
                "Szenario": ""},
        title="Wirkung der Szenarien auf die Initiative des Teams",
        color="Ueberholt im Mittel (%)", color_continuous_scale=design.VERLAUF_BILANZ,
        # Die Haelfte des Metagames zu ueberholen ist der Gleichstand; erst der
        # Abstand dazu ist ein Vor- oder Nachteil.
        color_continuous_midpoint=50,
        text_auto=".1f", height=420,
    )
    abbildung.update_layout(coloraxis_showscale=False)
    st.plotly_chart(abbildung, width="stretch")

    tabelle(uebersicht[["Szenario", "Mittlere Initiative", "Ueberholt im Mittel (%)",
                        "Schnellstes Mitglied", "Erlaeuterung"]])

    ohne = uebersicht[uebersicht["schluessel"] == "normal"]
    mit = uebersicht[uebersicht["schluessel"] == "rueckenwind"]
    if not ohne.empty and not mit.empty:
        gewinn = (mit.iloc[0]["Ueberholt im Mittel (%)"]
                  - ohne.iloc[0]["Ueberholt im Mittel (%)"])
        st.info(
            f"**Rueckenwind bringt diesem Team {gewinn:.1f} Prozentpunkte.** "
            "Je groesser dieser Wert, desto mehr haengt das Team davon ab, die "
            "Initiative-Kontrolle zu etablieren -- und desto teurer wird es, wenn der "
            "Gegner sie unterbindet."
        )


def _zeige_benchmark(conn, meta: pd.DataFrame, monat: str, kampfformat: str) -> None:
    """Rechner fuer die noetige Investition in Initiative."""
    st.markdown(
        "Die klassische Frage der Teamvorbereitung lautet nicht *wie schnell kann ich "
        "werden*, sondern *wie schnell muss ich werden*. Jeder Fleisspunkt, der nicht "
        "in Initiative fliesst, steht fuer Widerstandsfaehigkeit oder Durchschlagskraft "
        "zur Verfuegung."
    )

    namen = meta["anzeigename"].tolist()
    links, mitte, rechts = st.columns(3)
    with links:
        angreifer = st.selectbox("Eigenes Pokemon", namen, key="bench_angreifer",
                                 format_func=name_mit_deutsch)
    with mitte:
        standard_ziel = 1 if len(namen) > 1 else 0
        ziel = st.selectbox("Zu ueberholendes Ziel", namen, index=standard_ziel,
                            key="bench_ziel", format_func=name_mit_deutsch)
    with rechts:
        wesen = st.selectbox(
            "Angenommenes Wesen", ["Timid", "Jolly", "Hasty", "Naive", "Hardy"],
            key="bench_wesen",
            help="Die ersten vier erhoehen die Initiative um zehn Prozent, "
                 "'Hardy' steht fuer ein neutrales Wesen.",
        )

    if angreifer == ziel:
        st.info("Bitte zwei unterschiedliche Pokemon waehlen.")
        return

    ergebnis = speed.benchmark(conn, angreifer, ziel, monat, wesen, kampfformat)
    if ergebnis is None:
        st.warning("Fuer mindestens eines der beiden Pokemon liegt keine Verteilung vor.")
        return

    # Die ersten beiden Kacheln nennen die Ausgangslage, die dritte enthaelt die
    # Antwort auf die Frage der Seite -- nur sie traegt eine Aussage.
    spalten = st.columns(3)
    spalten[0].markdown(kennzahl_kachel(
        f"{ergebnis['ziel']}", str(ergebnis["ziel_initiative"]),
        f"gaengigstes Set: {ergebnis['ziel_set']}"), unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel(
        f"{ergebnis['angreifer']} aktuell", str(ergebnis["aktuelle_initiative"]),
        f"Basiswert {ergebnis['angreifer_basiswert']}"), unsafe_allow_html=True)

    if ergebnis["erreichbar"]:
        rest = 66 - ergebnis["benoetigte_punkte"]
        spalten[2].markdown(kennzahl_kachel(
            "Benoetigte Statuspunkte", str(ergebnis["benoetigte_punkte"]),
            f"{rest} von 66 bleiben frei", "guenstig"), unsafe_allow_html=True)
        st.success(
            f"Mit **{ergebnis['benoetigte_punkte']} Statuspunkten** in Initiative und dem "
            f"Wesen **{wesen}** handelt {ergebnis['angreifer']} vor "
            f"{ergebnis['ziel']} ({ergebnis['ziel_initiative']}). "
            f"Die verbleibenden {rest} Punkte koennen in Widerstandsfaehigkeit oder "
            "Durchschlagskraft investiert werden."
        )
    else:
        spalten[2].markdown(kennzahl_kachel(
            "Benoetigte Statuspunkte", "nicht erreichbar",
            "auch mit maximaler Investition", "gefahr"), unsafe_allow_html=True)
        st.error(
            f"{ergebnis['angreifer']} kann {ergebnis['ziel']} auch mit maximaler "
            f"Investition und dem Wesen {wesen} nicht ueberholen. Hier helfen nur ein "
            "Wahlschal, Rueckenwind oder ein Wechsel auf Bizarroraum."
        )


def _zeige_vorhersagbarkeit(conn, monat: str, kampfformat: str) -> None:
    """Wie einheitlich die haeufigsten Pokemon gespielt werden."""
    df = kpi.vorhersagbarkeit(conn, monat, kampfformat)
    if df.empty:
        st.info("Keine Daten vorhanden.")
        return

    st.markdown(
        "Ein hoher Anteil des haeufigsten Sets bedeutet, dass sich eine "
        "Standardkonfiguration durchgesetzt hat -- das Verhalten des Gegners ist dann "
        "gut vorhersagbar. Eine breite Streuung heisst: hier muss mit Varianten "
        "gerechnet werden, und eine Annahme ueber die Initiative ist riskant."
    )

    abbildung = px.bar(
        df.sort_values("top_anteil"), x="top_anteil", y="anzeigename", orientation="h",
        color="einstufung",
        color_discrete_map=design.abstufung_farben(
            ["Sehr hoch", "Hoch", "Mittel", "Gering"]),
        hover_data=["konzentration"],
        labels={"top_anteil": "Anteil des haeufigsten Sets (%)", "anzeigename": "",
                "einstufung": "Vorhersagbarkeit"},
        title="Wie einheitlich werden die Meta-Pokemon gespielt?",
        text_auto=".0f", height=560,
    )
    st.plotly_chart(abbildung, width="stretch")

    unsicher = df[df["einstufung"] == "Gering"]
    if not unsicher.empty:
        st.warning(
            "**Kaum vorhersagbar:** " + ", ".join(unsicher["anzeigename"]) +
            ". Bei diesen Pokemon deckt das haeufigste Set weniger als 20 Prozent ab -- "
            "die Initiative sollte hier nicht als bekannt vorausgesetzt werden."
        )

    st.markdown("#### Standardkonfigurationen")
    spalten = st.columns(5)
    for spalte, (_, zeile) in zip(spalten, df.head(5).iterrows(), strict=False):
        with spalte:
            meta_zeile = pd.Series({
                "pokedex_id": zeile["pokedex_id"], "anzeigename": zeile["anzeigename"],
                "typ1": None, "typ2": None,
            })
            st.markdown(
                "<div class='karte'>"
                f"<img src='{sprite_url(int(meta_zeile['pokedex_id']))}' width='92'>"
                f"<div style='font-weight:700;font-size:0.9rem;'>{zeile['anzeigename']}</div>"
                f"<div style='font-size:0.74rem;opacity:0.8;margin-top:3px;'>"
                f"{zeile['top_set']}</div>"
                f"<div style='font-size:0.78rem;margin-top:3px;'>Initiative "
                f"<b>{zeile['initiative']}</b> · {zeile['top_anteil']:.0f} % der Sets</div>"
                f"</div>", unsafe_allow_html=True,
            )

    tabelle(
        df.rename(columns={
            "anzeigename": "Pokemon", "usage_rang": "Meta-Rang",
            "top_anteil": "Anteil des Top-Sets (%)", "top_set": "Haeufigstes Set",
            "initiative": "Initiative", "konzentration": "Konzentration",
            "erfasste_sets": "Erfasste Sets", "einstufung": "Vorhersagbarkeit",
        })[["Pokemon", "Meta-Rang", "Haeufigstes Set", "Initiative",
            "Anteil des Top-Sets (%)", "Konzentration", "Erfasste Sets",
            "Vorhersagbarkeit"]],
    )

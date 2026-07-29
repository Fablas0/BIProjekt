"""Seite: Meta-Cockpit.

Verdichtete Managementsicht auf das Metagame von Pokemon Champions. Beantwortet
die Leitfragen: Wie sieht das Format aktuell aus, wie stabil ist es, wer bewegt
sich, und wer haelt sich dauerhaft oben?
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ..analytics import kpi
from ..config import TYP_FARBEN
from .komponenten import (
    hinweis_leere_datenbank,
    hinweis_messniveau,
    hole_verbindung,
    kennzahl_kachel,
    kopfauswahl,
    pokemon_karte,
)


def zeichne() -> None:
    conn = hole_verbindung()

    st.title("Meta-Cockpit")
    if not kpi.verfuegbare_formate(conn):
        hinweis_leere_datenbank()
        return

    basis = kpi.datenbasis(conn)
    st.caption(
        f"Quelle: {basis.get('quelle', '-')} · Saison {basis.get('saison', '-')} · "
        f"{basis.get('tage', 0)} Tage von {basis.get('beginn', '-')} "
        f"bis {basis.get('ende', '-')}"
    )

    kampfformat, tag = kopfauswahl(conn, "cockpit")
    if not tag:
        st.warning("Fuer dieses Format liegen keine Daten vor.")
        return

    werte = kpi.eckwerte(conn, tag, kampfformat)
    if not werte:
        st.warning("Fuer diesen Tag liegen keine Daten vor.")
        return

    # ------------------------------------------------------------------
    st.markdown("### Kennzahlen des Berichtstags")
    spalten = st.columns(5)
    stabilitaet = werte.get("stabilitaet")
    kacheln = [
        ("Erfasste Pokemon", str(werte["erfasste_pokemon"]),
         "mit vergebenem Nutzungsrang", "#6390F0"),
        ("Spitzenreiter", str(werte["spitzenreiter"]), "Rang 1 des Tages", "#F7D02C"),
        ("Meta-Stabilitaet", f"{stabilitaet:.3f}" if stabilitaet is not None else "-",
         "Rangkorrelation zum ersten Tag", "#A33EA1"),
        ("Beobachtete Tage", str(werte["beobachtete_tage"]),
         "in der laufenden Saison", "#7AC74C"),
        ("Typen in der Spitze", str(werte["typen_vielfalt"]),
         "vertretene Typen", "#EE8130"),
    ]
    for spalte, (titel, wert, hinweis, farbe) in zip(spalten, kacheln, strict=True):
        spalte.markdown(kennzahl_kachel(titel, wert, hinweis, farbe), unsafe_allow_html=True)

    hinweis_messniveau()

    reiter = st.tabs([
        "Rangliste", "Stabilitaet im Zeitverlauf", "Auf- und Absteiger",
        "Bestaendigkeit", "Typen- und Rollenstruktur",
    ])

    with reiter[0]:
        _zeige_rangliste(conn, tag, kampfformat)
    with reiter[1]:
        _zeige_stabilitaet(conn, kampfformat)
    with reiter[2]:
        _zeige_bewegung(conn, tag, kampfformat)
    with reiter[3]:
        _zeige_bestaendigkeit(conn, kampfformat)
    with reiter[4]:
        _zeige_struktur(conn, tag, kampfformat)


# --------------------------------------------------------------------------

def _zeige_rangliste(conn, tag: str, kampfformat: str) -> None:
    """Die fuehrenden Pokemon des Berichtstags."""
    top = kpi.rangliste(conn, tag, kampfformat, grenze=25)

    abbildung = px.bar(
        top.sort_values("rang", ascending=False), x="rang_perzentil", y="anzeigename",
        orientation="h", color="typ1", color_discrete_map=TYP_FARBEN,
        labels={"rang_perzentil": "Rangperzentil", "anzeigename": "", "typ1": "Primaertyp"},
        title=f"Die 25 meistgespielten Pokemon -- {tag} ({kampfformat})",
        text="rang", height=680,
    )
    abbildung.update_traces(texttemplate="Rang %{text}")
    abbildung.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(abbildung, use_container_width=True)

    st.caption(
        "Das Rangperzentil normiert den Rang auf 0 bis 100 und macht Tage mit "
        "unterschiedlich vielen erfassten Pokemon vergleichbar. Es ist eine "
        "abgeleitete Groesse, keine Nutzungsquote."
    )

    st.markdown("#### Die fuenf ersten Plaetze")
    karten = st.columns(5)
    for spalte, (_, zeile) in zip(karten, top.head(5).iterrows(), strict=False):
        with spalte:
            st.markdown(
                pokemon_karte(
                    zeile,
                    f"<div style='font-size:0.85rem;'><b>Rang {int(zeile['rang'])}</b>"
                    f"<br><span style='opacity:0.7;'>{zeile['rolle']}</span></div>",
                ), unsafe_allow_html=True,
            )

    st.dataframe(
        top.rename(columns={
            "rang": "Rang", "anzeigename": "Pokemon", "typ_kombination": "Typen",
            "rolle": "Rolle", "rang_perzentil": "Rangperzentil",
            "stufe50_speed": "Initiative (ohne Investition)",
            "basiswert_summe": "Basiswertsumme",
        })[["Rang", "Pokemon", "Typen", "Rolle", "Rangperzentil",
            "Initiative (ohne Investition)", "Basiswertsumme"]],
        use_container_width=True, hide_index=True, height=420,
    )


def _zeige_stabilitaet(conn, kampfformat: str) -> None:
    """Entwicklung der Rangkorrelation ueber die geladenen Tage."""
    verlauf = kpi.stabilitaet_verlauf(conn, kampfformat)
    if verlauf.empty:
        st.info("Fuer eine Verlaufsaussage werden mindestens zwei geladene Tage benoetigt.")
        return

    st.markdown(
        "Die **Rangkorrelation nach Spearman** ist das ordinale Gegenstueck zu einem "
        "Konzentrationsmass: sie gibt an, wie stark die Reihenfolge des Metagames "
        "erhalten geblieben ist. Ein Wert von 1 bedeutet eine unveraenderte "
        "Rangfolge, ein fallender Wert eine zunehmende Umsortierung."
    )

    abbildung = go.Figure()
    abbildung.add_trace(go.Scatter(
        x=verlauf["datum_iso"], y=verlauf["stabilitaet_zum_start"],
        name="Korrelation zum ersten Tag", mode="lines+markers",
        line={"width": 3, "color": "#EF553B"},
    ))
    abbildung.add_trace(go.Scatter(
        x=verlauf["datum_iso"], y=verlauf["stabilitaet_zum_vortag"],
        name="Korrelation zum Vortag", mode="lines+markers",
        line={"width": 2, "color": "#6390F0", "dash": "dot"},
    ))
    abbildung.update_layout(
        title="Meta-Stabilitaet im Zeitverlauf",
        yaxis={"title": "Rangkorrelation", "range": [0.9, 1.005]},
        height=420, legend={"orientation": "h", "y": -0.2},
    )
    st.plotly_chart(abbildung, use_container_width=True)

    letzte = verlauf.iloc[-1]
    wert = letzte["stabilitaet_zum_start"]
    if wert is not None and wert >= 0.99:
        st.info(
            f"**Das Format ist sehr stabil** (Korrelation {wert:.3f} zum ersten "
            "geladenen Tag). Die Rangfolge hat sich im Betrachtungszeitraum kaum "
            "veraendert -- Vorbereitung auf den aktuellen Stand ist verlaesslich."
        )
    elif wert is not None and wert < 0.9:
        st.warning(
            f"**Das Format ist in Bewegung** (Korrelation nur {wert:.3f}). Die "
            "Rangfolge hat sich deutlich umsortiert; eine Vorbereitung auf aeltere "
            "Staende ist riskant."
        )

    st.dataframe(
        verlauf.rename(columns={
            "datum_iso": "Tag", "stabilitaet_zum_start": "Korrelation zum Start",
            "stabilitaet_zum_vortag": "Korrelation zum Vortag",
            "top10_fluktuation": "Wechsel in den besten 10",
        }), use_container_width=True, hide_index=True,
    )


def _zeige_bewegung(conn, tag: str, kampfformat: str) -> None:
    """Rangveraenderungen gegenueber dem ersten geladenen Tag."""
    tage = kpi.verfuegbare_tage(conn, kampfformat)
    if len(tage) < 2:
        st.info("Fuer eine Trendaussage werden mindestens zwei geladene Tage benoetigt.")
        return

    vergleich = st.selectbox(
        "Vergleichstag", [t for t in tage if t < tag] or [tage[0]],
        index=0, key="cockpit_vergleich",
    )
    bewegung = kpi.rangbewegung(conn, tag, vergleich, kampfformat)
    if bewegung.empty:
        st.info("Keine Bewegungsdaten fuer diesen Vergleich.")
        return

    st.markdown(
        "Bei Rangdaten ist die **Differenz zweier Raenge** die zulaessige "
        "Vergleichsgroesse. Ein positiver Wert bedeutet einen Aufstieg, also einen "
        "kleineren Rang als zuvor."
    )

    verwertbar = bewegung.dropna(subset=["veraenderung"])
    links, rechts = st.columns(2)
    with links:
        st.markdown("#### Aufsteiger")
        auf = verwertbar.nlargest(8, "veraenderung")
        abbildung = px.bar(
            auf.sort_values("veraenderung"), x="veraenderung", y="anzeigename",
            orientation="h", color_discrete_sequence=["#2ecc71"],
            labels={"veraenderung": "Rangplaetze gutgemacht", "anzeigename": ""},
            text_auto="+d", height=340,
        )
        st.plotly_chart(abbildung, use_container_width=True)

    with rechts:
        st.markdown("#### Absteiger")
        ab = verwertbar.nsmallest(8, "veraenderung")
        abbildung = px.bar(
            ab.sort_values("veraenderung", ascending=False),
            x="veraenderung", y="anzeigename", orientation="h",
            color_discrete_sequence=["#e74c3c"],
            labels={"veraenderung": "Rangplaetze verloren", "anzeigename": ""},
            text_auto="+d", height=340,
        )
        st.plotly_chart(abbildung, use_container_width=True)

    neu = bewegung[bewegung["richtung"] == "Neu erfasst"]
    if not neu.empty:
        st.success(
            "**Neu in der Rangliste:** " + ", ".join(
                f"{z['anzeigename']} (Rang {int(z['rang'])})"
                for _, z in neu.head(6).iterrows()))

    st.dataframe(
        bewegung.rename(columns={
            "anzeigename": "Pokemon", "rang": "Rang", "vorher_rang": "Rang zuvor",
            "veraenderung": "Veraenderung", "richtung": "Tendenz",
            "typ_kombination": "Typen", "rolle": "Rolle",
        })[["Pokemon", "Rang", "Rang zuvor", "Veraenderung", "Tendenz", "Rolle"]],
        use_container_width=True, hide_index=True, height=380,
    )


def _zeige_bestaendigkeit(conn, kampfformat: str) -> None:
    """Wer sich dauerhaft in der Spitzengruppe haelt."""
    n = st.slider("Spitzengruppe", 5, 30, 15, 5, key="cockpit_topn")
    df = kpi.verweildauer(conn, n, kampfformat)
    if df.empty:
        st.info("Keine Daten vorhanden.")
        return

    st.markdown(
        f"Wie viele der geladenen Tage sich ein Pokemon in den besten {n} gehalten "
        "hat. Unterscheidet dauerhaft etablierte Pokemon von kurzzeitigen "
        "Ausreissern -- fuer die Turniervorbereitung ein wichtiger Unterschied."
    )

    abbildung = px.bar(
        df.head(20).sort_values("anteil_tage"), x="anteil_tage", y="anzeigename",
        orientation="h", color="bestaendigkeit",
        color_discrete_map={"Dauerhaft": "#2ecc71", "Etabliert": "#7AC74C",
                            "Schwankend": "#f1c40f", "Kurzzeitig": "#e74c3c"},
        labels={"anteil_tage": "Anteil der Tage in der Spitzengruppe (%)",
                "anzeigename": "", "bestaendigkeit": "Einstufung"},
        text_auto=".0f", height=560,
    )
    st.plotly_chart(abbildung, use_container_width=True)

    st.dataframe(
        df.rename(columns={
            "anzeigename": "Pokemon", "tage_in_top": "Tage in der Spitze",
            "anteil_tage": "Anteil (%)", "bester_rang": "Bester Rang",
            "schlechtester_rang": "Schlechtester Rang", "aktueller_rang": "Aktuell",
            "bestaendigkeit": "Einstufung",
        })[["Pokemon", "Tage in der Spitze", "Anteil (%)", "Bester Rang",
            "Schlechtester Rang", "Aktuell", "Einstufung"]],
        use_container_width=True, hide_index=True, height=400,
    )


def _zeige_struktur(conn, tag: str, kampfformat: str) -> None:
    """Verteilung der Spitzengruppe nach Typ und Rolle."""
    df = kpi.rangliste(conn, tag, kampfformat, grenze=50)

    links, rechts = st.columns(2)
    with links:
        typen = df["typ1"].value_counts().reset_index()
        typen.columns = ["typ1", "anzahl"]
        abbildung = px.pie(
            typen, names="typ1", values="anzahl", hole=0.45,
            color="typ1", color_discrete_map=TYP_FARBEN,
            title="Primaertypen der besten 50",
        )
        abbildung.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(abbildung, use_container_width=True)

    with rechts:
        rollen = df["rolle"].value_counts().reset_index()
        rollen.columns = ["rolle", "anzahl"]
        abbildung = px.bar(
            rollen, x="anzahl", y="rolle", orientation="h",
            labels={"anzahl": "Anzahl Pokemon", "rolle": ""},
            title="Abgeleitete Teamrollen der besten 50",
            color="anzahl", color_continuous_scale="Sunset", text_auto=True,
        )
        abbildung.update_layout(showlegend=False, coloraxis_showscale=False,
                                yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(abbildung, use_container_width=True)

    st.caption(
        "Die Teamrolle ist keine Angabe des Quellsystems, sondern wird im "
        "Transformationsschritt aus dem Verhaeltnis der Basiswerte abgeleitet. "
        "Sie macht die Pokemon-Dimension entlang einer fachlichen Achse auswertbar. "
        "Gezaehlt werden Pokemon, nicht Nutzungsanteile -- Raenge liessen sich nicht "
        "aufsummieren."
    )

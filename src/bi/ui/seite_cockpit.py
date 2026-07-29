"""Seite: Meta-Cockpit.

Verdichtete Managementsicht auf das Metagame -- Kennzahlen, Entwicklung und die
wichtigsten Bewegungen. Beantwortet die Leitfragen: Wie sieht das Format aktuell
aus, in welche Richtung entwickelt es sich, und wie verlaesslich sind die Daten?
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ..analytics import kpi
from ..config import TYP_FARBEN
from .komponenten import (
    hinweis_leere_datenbank,
    hole_verbindung,
    kennzahl_kachel,
    monatsauswahl,
    pokemon_karte,
)


def zeichne() -> None:
    conn = hole_verbindung()
    monate = kpi.verfuegbare_monate(conn)

    st.title("Meta-Cockpit")
    if not monate:
        hinweis_leere_datenbank()
        return

    format_info = kpi.geladenes_format(conn)
    st.caption(
        f"Datenbasis: {format_info.get('anzeige', 'unbekannt')} · "
        f"Skill-Stufe {format_info.get('bezeichnung', '?')} "
        f"(ELO ab {format_info.get('elo_cutoff', '?')}) · "
        f"{len(monate)} Monate von {monate[0]} bis {monate[-1]}"
    )

    monat = monatsauswahl(monate, "cockpit_monat")
    werte = kpi.eckwerte(conn, monat)
    if not werte:
        st.warning("Fuer diesen Monat liegen keine Daten vor.")
        return

    # ------------------------------------------------------------------
    # Kennzahlenzeile
    # ------------------------------------------------------------------
    st.markdown("### Kennzahlen des Berichtsmonats")
    spalten = st.columns(5)
    kacheln = [
        ("Erfasste Partien", f"{werte['partien']:,}".replace(",", "."),
         "Grundgesamtheit der Auswertung", "#6390F0"),
        ("Gefuehrte Pokemon", str(werte["pokemon_gefuehrt"]),
         "mit messbarem Nutzungsanteil", "#7AC74C"),
        ("Top-10-Anteil", f"{werte['top10_anteil']} %",
         "Anteil der zehn meistgenutzten", "#EE8130"),
        ("Meta-Konzentration", f"{werte['konzentration']}",
         "Herfindahl-Index (0-100)", "#A33EA1"),
        ("Bestes GXE", f"{werte['bestes_gxe']} %",
         "hoechste Erfolgsquote im Format", "#F7D02C"),
    ]
    for spalte, (titel, wert, hinweis, farbe) in zip(spalten, kacheln, strict=True):
        spalte.markdown(kennzahl_kachel(titel, wert, hinweis, farbe), unsafe_allow_html=True)

    st.markdown("")

    reiter = st.tabs([
        "Nutzungsverteilung", "Entwicklung im Zeitverlauf", "Auf- und Absteiger",
        "Typen- und Rollenstruktur",
    ])

    # ------------------------------------------------------------------
    with reiter[0]:
        top = kpi.usage_verteilung(conn, monat, 20)
        abbildung = px.bar(
            top.sort_values("usage_rate"), x="usage_rate", y="anzeigename",
            orientation="h", color="typ1", color_discrete_map=TYP_FARBEN,
            labels={"usage_rate": "Nutzungsanteil (%)", "anzeigename": "",
                    "typ1": "Primaertyp"},
            title=f"Die 20 meistgenutzten Pokemon -- {monat}",
            text_auto=".1f", height=640,
        )
        abbildung.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(abbildung, use_container_width=True)

        st.caption(
            "Der Nutzungsanteil gibt an, in wie viel Prozent der Teams das Pokemon "
            "vertreten ist. Da ein Team sechs Pokemon umfasst, summieren sich die "
            "Anteile ueber alle Pokemon auf rund 600 Prozent."
        )

        st.markdown("#### Die fuenf meistgenutzten Pokemon")
        karten = st.columns(5)
        for spalte, (_, zeile) in zip(karten, top.head(5).iterrows(), strict=False):
            with spalte:
                st.markdown(
                    pokemon_karte(
                        zeile,
                        f"<div style='font-size:0.85rem;'><b>{zeile['usage_rate']:.1f} %</b>"
                        f"<br><span style='opacity:0.7;'>Rang {int(zeile['rang'])}</span></div>",
                    ),
                    unsafe_allow_html=True,
                )

    # ------------------------------------------------------------------
    with reiter[1]:
        verlauf = kpi.konzentration_zeitverlauf(conn)

        abbildung = go.Figure()
        abbildung.add_trace(go.Scatter(
            x=verlauf["monat_iso"], y=verlauf["konzentration"], name="Meta-Konzentration",
            mode="lines+markers", line={"width": 3, "color": "#EF553B"},
        ))
        abbildung.add_trace(go.Scatter(
            x=verlauf["monat_iso"], y=verlauf["top10_anteil"], name="Top-10-Anteil (%)",
            mode="lines+markers", yaxis="y2", line={"width": 3, "color": "#6390F0"},
        ))
        abbildung.update_layout(
            title="Entwicklung der Meta-Konzentration",
            yaxis={"title": "Herfindahl-Index"},
            yaxis2={"title": "Top-10-Anteil (%)", "overlaying": "y", "side": "right"},
            height=430, legend={"orientation": "h", "y": -0.2},
        )
        st.plotly_chart(abbildung, use_container_width=True)

        erster, letzter = verlauf.iloc[0], verlauf.iloc[-1]
        veraenderung = letzter["top10_anteil"] - erster["top10_anteil"]
        if veraenderung > 3:
            st.warning(
                f"**Das Format verengt sich.** Der Anteil der zehn meistgenutzten Pokemon "
                f"ist von {erster['top10_anteil']} auf {letzter['top10_anteil']} Prozent "
                f"gestiegen (+{veraenderung:.1f} Prozentpunkte). Abseitige Team-Entwuerfe "
                "werden dadurch riskanter, weil sie auf ein immer einheitlicheres Feld treffen."
            )
        elif veraenderung < -3:
            st.success(
                f"**Das Format oeffnet sich.** Der Top-10-Anteil ist um "
                f"{abs(veraenderung):.1f} Prozentpunkte gefallen -- es setzen sich mehr "
                "unterschiedliche Team-Entwuerfe durch."
            )
        else:
            st.info("Die Konzentration des Formats ist ueber den Betrachtungszeitraum stabil.")

        st.dataframe(
            verlauf.rename(columns={
                "monat_name": "Monat", "konzentration": "Konzentration",
                "top10_anteil": "Top-10-Anteil (%)", "anzahl_pokemon": "Gefuehrte Pokemon",
                "partien": "Partien",
            })[["Monat", "Konzentration", "Top-10-Anteil (%)", "Gefuehrte Pokemon", "Partien"]],
            use_container_width=True, hide_index=True,
        )

    # ------------------------------------------------------------------
    with reiter[2]:
        bewegung = kpi.momentum(conn, monat)
        if bewegung.empty:
            st.info("Fuer eine Trendaussage werden mindestens zwei geladene Monate benoetigt.")
        else:
            st.markdown(
                "Die Veraenderung gegenueber dem Vormonat zeigt, **wohin sich das Format "
                "bewegt**. Fuer die Turniervorbereitung ist das aussagekraeftiger als der "
                "Ist-Stand allein, weil zwischen Vorbereitung und Turnier Wochen liegen."
            )

            links, rechts = st.columns(2)
            with links:
                st.markdown("#### Aufsteiger")
                aufsteiger = bewegung.head(8)
                abbildung = px.bar(
                    aufsteiger.sort_values("differenz"), x="differenz", y="anzeigename",
                    orientation="h", color_discrete_sequence=["#2ecc71"],
                    labels={"differenz": "Veraenderung (Prozentpunkte)", "anzeigename": ""},
                    text_auto="+.1f", height=340,
                )
                st.plotly_chart(abbildung, use_container_width=True)

            with rechts:
                st.markdown("#### Absteiger")
                absteiger = bewegung.tail(8)
                abbildung = px.bar(
                    absteiger.sort_values("differenz", ascending=False),
                    x="differenz", y="anzeigename", orientation="h",
                    color_discrete_sequence=["#e74c3c"],
                    labels={"differenz": "Veraenderung (Prozentpunkte)", "anzeigename": ""},
                    text_auto="+.1f", height=340,
                )
                st.plotly_chart(abbildung, use_container_width=True)

            neu = bewegung[bewegung["richtung"] == "Neu im Meta"]
            if not neu.empty:
                st.success(
                    "**Neu im Meta:** " + ", ".join(
                        f"{z['anzeigename']} ({z['usage_rate']:.1f} %)"
                        for _, z in neu.head(6).iterrows()
                    )
                )

            st.dataframe(
                bewegung.rename(columns={
                    "anzeigename": "Pokemon", "usage_rate": "Aktuell (%)",
                    "vormonat_rate": "Vormonat (%)", "differenz": "Differenz",
                    "veraenderung_prozent": "Veraenderung (%)", "richtung": "Tendenz",
                    "rang_veraenderung": "Rangaenderung",
                })[["Pokemon", "Aktuell (%)", "Vormonat (%)", "Differenz",
                    "Veraenderung (%)", "Rangaenderung", "Tendenz"]],
                use_container_width=True, hide_index=True, height=380,
            )

    # ------------------------------------------------------------------
    with reiter[3]:
        df = kpi.meta_uebersicht(conn, monat)

        links, rechts = st.columns(2)
        with links:
            typ_summe = (df.groupby("typ1")["usage_rate"].sum()
                         .sort_values(ascending=False).reset_index())
            abbildung = px.pie(
                typ_summe, names="typ1", values="usage_rate", hole=0.45,
                color="typ1", color_discrete_map=TYP_FARBEN,
                title="Verteilung des Nutzungsanteils nach Primaertyp",
            )
            abbildung.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(abbildung, use_container_width=True)

        with rechts:
            rollen = (df.groupby("rolle")["usage_rate"].sum()
                      .sort_values(ascending=False).reset_index())
            abbildung = px.bar(
                rollen, x="usage_rate", y="rolle", orientation="h",
                labels={"usage_rate": "Nutzungsanteil (%)", "rolle": ""},
                title="Verteilung nach abgeleiteter Teamrolle",
                color="usage_rate", color_continuous_scale="Sunset", text_auto=".0f",
            )
            abbildung.update_layout(showlegend=False, coloraxis_showscale=False,
                                    yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(abbildung, use_container_width=True)

        st.caption(
            "Die Teamrolle ist keine Angabe der Quellsysteme, sondern wird im "
            "Transformationsschritt aus dem Verhaeltnis der Basiswerte abgeleitet. "
            "Sie macht die Pokemon-Dimension entlang einer fachlichen Achse auswertbar."
        )

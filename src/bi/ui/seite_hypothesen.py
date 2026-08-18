"""Seite: Hypothesen.

Zeigt den Hypothesenkatalog samt Pruefergebnis. Jede Hypothese steht mit
Null- und Alternativhypothese, Verfahren, Datenbasis, Pruefgroesse,
Effektstaerke und Entscheidung auf der Seite -- einschliesslich ihrer
Einschraenkung. Ein Dashboard zeigt, was der Fall ist; diese Seite sagt, ob
das Gezeigte mehr ist als Rauschen.

Die Rechnung ist dieselbe wie im kopflosen Lauf
(``python -m scripts.hypothesen_pruefen``); die Seite rechnet nichts eigenes.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..analytics import hypothesen
from ..config import ALPHA
from . import design
from .komponenten import (
    hinweis_leere_datenbank,
    hole_verbindung,
    kennzahl_kachel,
    seitenkopf,
)

STATUS_FARBEN = {
    "H0 verworfen": design.GRUEN,
    "H0 beibehalten": design.BLAU_HELL,
    "nicht pruefbar": "#95a5a6",
}


@st.cache_data(ttl=300)
def _ergebnis() -> hypothesen.Katalogergebnis:
    return hypothesen.pruefe_alle(hole_verbindung())


def zeichne() -> None:
    seitenkopf("Hypothesen",
               "Vorab formulierte Aussagen, statistisch geprueft statt behauptet")

    ergebnis = _ergebnis()
    if ergebnis.geprueft == 0:
        hinweis_leere_datenbank()
        return

    kacheln = st.columns(4)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Hypothesen", str(len(ergebnis.ergebnisse)),
                                    "im Katalog"), unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("H0 verworfen", str(ergebnis.verworfen),
                                    "Effekt statistisch belegt",
                                    farbe=design.GRUEN), unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("H0 beibehalten",
                                    str(ergebnis.geprueft - ergebnis.verworfen),
                                    "kein belastbarer Effekt"), unsafe_allow_html=True)
    with kacheln[3]:
        st.markdown(kennzahl_kachel("Niveau", f"{int(ALPHA * 100)} %",
                                    "korrigiert nach Holm-Bonferroni"),
                    unsafe_allow_html=True)

    st.caption(
        "Ein p-Wert allein genuegt nicht: bei dieser Fallzahl wird fast jeder "
        "Unterschied signifikant. Jede Pruefung traegt deshalb eine Effektstaerke, "
        "und die Familie ist nach Holm-Bonferroni korrigiert -- zwoelf Einzeltests "
        "zum Niveau 5 Prozent lieferten sonst mit rund 46 Prozent "
        "Wahrscheinlichkeit einen reinen Zufallstreffer."
    )

    _effektdiagramm(ergebnis)

    for bereich, eintraege in ergebnis.nach_bereich().items():
        st.markdown(f"### {bereich}")
        for e in eintraege:
            _hypothese(e)


def _effektdiagramm(ergebnis: hypothesen.Katalogergebnis) -> None:
    """Effektstaerken im Ueberblick -- der Betrag traegt die Aussage."""
    pruefbar = [e for e in ergebnis.ergebnisse if e.pruefbar]
    if not pruefbar:
        return
    df = pd.DataFrame({
        "hypothese": [f"{e.hypothese.schluessel}: {e.hypothese.titel}" for e in pruefbar],
        "effekt": [abs(e.pruefgroesse.effekt) for e in pruefbar],
        "status": [e.status for e in pruefbar],
        "beschriftung": [f"{e.pruefgroesse.effekt_name} = {e.pruefgroesse.effekt}"
                          for e in pruefbar],
    }).iloc[::-1]

    figur = go.Figure(go.Bar(
        x=df["effekt"], y=df["hypothese"], orientation="h",
        marker_color=[STATUS_FARBEN[s] for s in df["status"]],
        text=df["beschriftung"], textposition="outside",
    ))
    figur.update_layout(
        height=90 + 32 * len(df), margin={"l": 10, "r": 10, "t": 30, "b": 10},
        xaxis_title="Betrag der Effektstaerke", yaxis_title=None,
        title="Effektstaerken (gruen: H0 verworfen)",
    )
    st.plotly_chart(figur, width="stretch")


def _hypothese(e: hypothesen.HypothesenErgebnis) -> None:
    h = e.hypothese
    farbe = STATUS_FARBEN.get(e.status, "#95a5a6")
    with st.expander(f"{h.schluessel} · {h.titel} — {e.status}"):
        st.markdown(
            f"<div style='border-left:3px solid {farbe};padding-left:12px;'>"
            f"<b>H0:</b> {h.nullhypothese}<br>"
            f"<b>H1:</b> {h.alternativhypothese}</div>",
            unsafe_allow_html=True)

        st.markdown(f"**Warum diese Frage:** {h.begruendung}")
        st.markdown(f"**Verfahren:** {h.verfahren}")
        st.markdown(f"**Datenbasis:** {h.datenbasis}")

        if e.pruefbar:
            p = e.pruefgroesse
            werte = st.columns(4)
            werte[0].metric(p.statistik_name, str(p.statistik))
            werte[1].metric("p-Wert", f"{p.p_wert:.6f}",
                            help=f"Holm-Schranke: {e.schranke:.6f}")
            werte[2].metric(p.effekt_name, str(p.effekt),
                            help=f"Einordnung: {p.effekt_deutung}")
            werte[3].metric("n", str(p.n))
            st.markdown(f"**Befund:** {e.befund}")
        else:
            st.warning(f"Nicht pruefbar: {e.hinweis}")

        if h.einschraenkung:
            st.caption(f"Einschraenkung: {h.einschraenkung}")

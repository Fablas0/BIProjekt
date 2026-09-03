"""Seite: Start -- die Wahl der Spielweise.

Die erste Frage an jemanden, der die Anwendung oeffnet, ist nicht "welche
Seite?", sondern "was spielst du?". Diese Seite stellt sie: sechs Kacheln,
eine je Spielweise, mit der Frage, die die Spielweise beantwortet. Ein Klick
setzt die Spielweise und springt auf deren erste Seite.

Die Kacheln sind Schaltflaechen mit einem Schluessel ``spielweise_*``; das
Designsystem spricht sie darueber an, wie die Navigationskaesten ueber
``nav_*``.
"""

from __future__ import annotations

import streamlit as st

from .. import nutzerdaten, shiny, spielstand
from . import anmeldung
from .komponenten import hole_verbindung, kennzahl_kachel, seitenkopf
from .spielweisen import SPIELWEISEN


def zeichne() -> None:
    conn = hole_verbindung()
    nutzerdaten.anhaengen(conn)
    nutzer = anmeldung.verlangen(conn)
    if nutzer is None:
        return

    seitenkopf("Was spielst du heute?",
               "Die Spielweise waehlt aus, welche Werkzeuge die Navigation zeigt -- "
               "wechseln geht jederzeit in der Seitenleiste")

    schluessel = list(SPIELWEISEN)
    for zeile in range(0, len(schluessel), 3):
        spalten = st.columns(3)
        for spalte, key in zip(spalten, schluessel[zeile:zeile + 3], strict=False):
            spielweise = SPIELWEISEN[key]
            with spalte, st.container(border=True):
                st.markdown(f"#### {spielweise.name}")
                st.markdown(f"*{spielweise.frage}*")
                st.caption(spielweise.beschreibung)
                if st.button("Loslegen", key=f"spielweise_{key}", width="stretch",
                             type="primary" if st.session_state.get("spielweise") == key
                             else "secondary"):
                    st.session_state["spielweise"] = key
                    st.session_state["seite"] = spielweise.startseite
                    st.rerun()

    _eigener_stand(conn, nutzer)


def _eigener_stand(conn, nutzer) -> None:
    """Was diese Person bereits angelegt hat -- der schnelle Wiedereinstieg."""
    box = len(nutzerdaten.box_lesen(conn, nutzer.nutzer_id))
    jagden = shiny.jagden_lesen(conn, nutzer.nutzer_id)
    laeufe = spielstand.laeufe_lesen(conn, nutzer.nutzer_id)
    laufend = sum(1 for j in jagden if j["status"] == "laeuft")
    offen = sum(1 for lauf in laeufe if lauf["status"] == "laeuft")

    if not (box or jagden or laeufe):
        return

    st.markdown("### Dein Stand")
    kacheln = st.columns(3)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Pokemon in der Box", str(box),
                                    "im PC-System, ueber alle Spielformen"),
                    unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("Laufende Shiny-Jagden", str(laufend),
                                    f"{len(jagden)} Jagden insgesamt"),
                    unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("Offene Spielstaende", str(offen),
                                    f"{len(laeufe)} Laeufe insgesamt"),
                    unsafe_allow_html=True)

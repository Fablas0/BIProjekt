"""VGC Business Intelligence -- Einstiegspunkt der Streamlit-Anwendung.

Business-Intelligence-Loesung fuer das kompetitive Pokemon-Doppelkampfformat (VGC).
Sie fuehrt Stammdaten der PokeAPI und die monatlichen Nutzungsstatistiken von
Smogon in einem historisierten Data Warehouse zusammen und stellt darauf ein
Dashboard mit Kennzahlen, OLAP-Auswertung und Team-Analysen bereit.

Start:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Das Paket liegt unter src/, damit Anwendungscode und Projektwurzel getrennt
# bleiben. Streamlit startet aus der Wurzel, deshalb wird der Pfad hier ergaenzt.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from bi.analytics import kpi  # noqa: E402
from bi.ui import (  # noqa: E402
    komponenten,
    seite_cockpit,
    seite_etl,
    seite_olap,
    seite_playbook,
    seite_scouting,
    seite_teambuilder,
)

SEITEN = {
    "Meta-Cockpit": seite_cockpit.zeichne,
    "Gegner-Scouting": seite_scouting.zeichne,
    "Team-Builder": seite_teambuilder.zeichne,
    "OLAP-Explorer": seite_olap.zeichne,
    "Meta-Playbook": seite_playbook.zeichne,
    "ETL & Datenqualitaet": seite_etl.zeichne,
}


def main() -> None:
    st.set_page_config(
        page_title="VGC Business Intelligence",
        page_icon="◆",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    with st.sidebar:
        st.markdown("## VGC Business Intelligence")
        st.caption("Data Warehouse und Analytics fuer das kompetitive Doppelkampfformat")

        seite = st.radio("Navigation", list(SEITEN.keys()), label_visibility="collapsed")
        st.markdown("---")

        _zeige_status()

    SEITEN[seite]()


def _zeige_status() -> None:
    """Kurzer Statusblock in der Seitenleiste."""
    try:
        conn = komponenten.hole_verbindung()
        monate = kpi.verfuegbare_monate(conn)
        format_info = kpi.geladenes_format(conn)
    except Exception as fehler:  # noqa: BLE001
        st.error(f"Keine Verbindung zum Data Warehouse: {fehler}")
        return

    if not monate:
        st.warning("Data Warehouse leer.\n\nBitte unter *ETL & Datenqualitaet* laden.")
        return

    st.markdown("**Datenbasis**")
    st.markdown(
        f"<div style='font-size:0.84rem;line-height:1.6;opacity:0.85;'>"
        f"{format_info.get('anzeige', '-')}<br>"
        f"Skill-Stufe: {format_info.get('bezeichnung', '-')}<br>"
        f"Zeitreihe: {monate[0]} bis {monate[-1]}<br>"
        f"Monate: {len(monate)}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.caption(
        "Quellen: PokeAPI (Stammdaten) und Smogon Usage Statistics (Bewegungsdaten). "
        "Die Anwendung steht in keiner Verbindung zu Nintendo, Game Freak oder "
        "The Pokemon Company."
    )


if __name__ == "__main__":
    main()

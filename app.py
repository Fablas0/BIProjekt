"""VGC Business Intelligence -- Einstiegspunkt der Streamlit-Anwendung.

Business-Intelligence-Loesung fuer Pokemon Champions, die seit April 2026
offizielle Wettkampfplattform. Die Anwendung laedt die taeglichen Ranked-Daten,
reichert sie mit Stammdaten der PokeAPI an, archiviert sie dauerhaft und stellt
darauf ein Dashboard mit Kennzahlen, OLAP-Auswertung, Team-Analysen und einem
Team-Preview-Advisor bereit.

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

from bi import warehouse  # noqa: E402
from bi.analytics import kpi  # noqa: E402
from bi.config import QUELLE_VORHALTUNG_TAGE  # noqa: E402
from bi.ui import (  # noqa: E402
    komponenten,
    seite_cockpit,
    seite_etl,
    seite_olap,
    seite_playbook,
    seite_preview,
    seite_scouting,
    seite_speedtiers,
    seite_teambuilder,
)

SEITEN = {
    "Meta-Cockpit": seite_cockpit.zeichne,
    "Team-Preview-Advisor": seite_preview.zeichne,
    "Gegner-Scouting": seite_scouting.zeichne,
    "Team-Builder": seite_teambuilder.zeichne,
    "Speed-Tiers": seite_speedtiers.zeichne,
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
        st.caption("Data Warehouse und Analytics fuer Pokemon Champions")

        seite = st.radio("Navigation", list(SEITEN.keys()), label_visibility="collapsed")
        st.markdown("---")

        _zeige_status()

    SEITEN[seite]()


def _zeige_status() -> None:
    """Kurzer Statusblock in der Seitenleiste."""
    try:
        conn = komponenten.hole_verbindung()
        basis = kpi.datenbasis(conn)
        formate = kpi.verfuegbare_formate(conn)
    except Exception as fehler:  # noqa: BLE001
        st.error(f"Keine Verbindung zum Data Warehouse: {fehler}")
        return

    if not basis:
        st.warning("Data Warehouse leer.\n\nBitte unter *ETL & Datenqualitaet* laden.")
        return

    archiv = warehouse.archiv_umfang(conn)

    st.markdown("**Datenbasis**")
    st.markdown(
        "<div style='font-size:0.84rem;line-height:1.6;opacity:0.9;'>"
        "<b>Pokemon Champions</b> <span style='opacity:0.7;'>(offiziell)</span><br>"
        f"Saison {basis.get('saison', '-')} · {basis.get('tage', 0)} Tage<br>"
        f"{basis.get('beginn', '-')} bis {basis.get('ende', '-')}<br>"
        f"Formate: {', '.join(formate)}</div>",
        unsafe_allow_html=True,
    )

    if archiv.get("tage"):
        ueberschuss = max(0, int(archiv["tage"]) - QUELLE_VORHALTUNG_TAGE)
        st.markdown(
            "<div style='font-size:0.8rem;line-height:1.5;opacity:0.75;margin-top:8px;'>"
            f"Archiv: {archiv['tage']} Tage gesichert"
            + (f", davon {ueberschuss} ueber die Vorhaltezeit der Quelle hinaus"
               if ueberschuss else "")
            + "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.caption(
        "Die Nutzung wird als Rang veroeffentlicht, nicht als Anteil -- die "
        "Kennzahlen sind entsprechend ordinal ausgelegt."
    )
    st.caption(
        "Quellen: Pokemon Champions Battle Data (Bewegungsdaten) und PokeAPI "
        "(Stammdaten). Die Anwendung steht in keiner Verbindung zu Nintendo, "
        "Game Freak oder The Pokemon Company."
    )


if __name__ == "__main__":
    main()

"""Pokemon Business Intelligence -- Einstiegspunkt der Streamlit-Anwendung.

Begonnen als Business-Intelligence-Loesung fuer Pokemon Champions, die seit
April 2026 offizielle Wettkampfplattform. Die Anwendung laedt die taeglichen
Ranked-Daten, reichert sie mit Stammdaten der PokeAPI an, archiviert sie
dauerhaft und stellt darauf ein Dashboard mit Kennzahlen, OLAP-Auswertung,
Team-Analysen und einem Team-Preview-Advisor bereit.

Inzwischen bedient sie sechs **Spielweisen** (:mod:`bi.ui.spielweisen`):
Champions, Pokemon GO, Sammelkartenspiel, Nuzlocke, Durchspielen sowie
Sammeln und Shiny-Jagd. Die Spielweise waehlt aus, welche Seiten die
Navigation zeigt; die Seiten selbst sind davon unabhaengig.

Start:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

import streamlit as st

# Das Paket liegt unter src/, damit Anwendungscode und Projektwurzel getrennt
# bleiben. Streamlit startet aus der Wurzel, deshalb wird der Pfad hier ergaenzt.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from bi import nutzerdaten, warehouse  # noqa: E402
from bi.analytics import kpi, saison  # noqa: E402
from bi.config import QUELLE_VORHALTUNG_TAGE  # noqa: E402
from bi.ui import (  # noqa: E402
    anmeldung,
    design,
    komponenten,
    seite_cockpit,
    seite_etl,
    seite_go,
    seite_hypothesen,
    seite_olap,
    seite_pc,
    seite_playbook,
    seite_pokedex,
    seite_preview,
    seite_schaden,
    seite_scouting,
    seite_shiny,
    seite_speedtiers,
    seite_spielformen,
    seite_spielstand,
    seite_start,
    seite_tcg,
    seite_teambuilder,
    seite_trends,
    spielweisen,
)

START = "Start"

SEITEN = {
    START: seite_start.zeichne,
    "Meta-Cockpit": seite_cockpit.zeichne,
    "Trends": seite_trends.zeichne,
    "Team-Preview-Advisor": seite_preview.zeichne,
    "Gegner-Scouting": seite_scouting.zeichne,
    "Team-Builder": seite_teambuilder.zeichne,
    "Speed-Tiers": seite_speedtiers.zeichne,
    "Schadensrechner": seite_schaden.zeichne,
    "PC-System": seite_pc.zeichne,
    "Pokedex": seite_pokedex.zeichne,
    "OLAP-Explorer": seite_olap.zeichne,
    "Meta-Playbook": seite_playbook.zeichne,
    "Spielformen": seite_spielformen.zeichne,
    "Hypothesen": seite_hypothesen.zeichne,
    "GO-Meta": seite_go.zeichne,
    "Sammelkartenspiel": seite_tcg.zeichne,
    "Nuzlocke-Lauf": partial(seite_spielstand.zeichne, "nuzlocke"),
    "Spielstand": partial(seite_spielstand.zeichne, "normal"),
    "Shiny-Jagd": seite_shiny.zeichne,
    "ETL & Datenqualitaet": seite_etl.zeichne,
}


def _navigation() -> str:
    """Seitenauswahl als anklickbare Kaesten, gegliedert nach Spielweise.

    Ein Auswahlfeld verlangt zwei Handgriffe und verbirgt die uebrigen
    Moeglichkeiten. Als Kaesten sind alle Seiten der gewaehlten Spielweise
    samt ihrer Aufgabe sichtbar, und ein Klick genuegt. Ohne gewaehlte
    Spielweise bleibt nur der Start -- die Wahl ist die erste Handlung.
    """
    st.session_state.setdefault("seite", START)
    schluessel = st.session_state.get("spielweise")
    spielweise = spielweisen.SPIELWEISEN.get(schluessel) if schluessel else None

    gruppen: list[tuple[str, tuple[tuple[str, str], ...]]] = [
        ("", ((START, "Spielweise waehlen oder wechseln"),)),
    ]
    if spielweise:
        gruppen.extend(spielweise.navigation)
    gruppen.append(("Betrieb", spielweisen.BETRIEB))

    for gruppe, eintraege in gruppen:
        if gruppe:
            st.markdown(f"<div class='nav-gruppe'>{gruppe}</div>", unsafe_allow_html=True)
        for name, aufgabe in eintraege:
            aktiv = st.session_state["seite"] == name
            if st.button(name, key=f"nav_{name}", help=aufgabe, width="stretch",
                         type="primary" if aktiv else "secondary"):
                st.session_state["seite"] = name
                st.rerun()

    # Eine Seite, die zur Spielweise nicht mehr gehoert -- etwa nach einem
    # Wechsel in der Seitenleiste -- faellt auf den Start zurueck.
    erlaubt = {START, *spielweisen.BETRIEB_SEITEN}
    if spielweise:
        erlaubt.update(spielweise.seiten)
    if st.session_state["seite"] not in erlaubt:
        st.session_state["seite"] = spielweise.startseite if spielweise else START
    return st.session_state["seite"]


def _spielweisenwahl() -> None:
    """Wechsel der Spielweise in der Seitenleiste."""
    schluessel = list(spielweisen.SPIELWEISEN)
    aktuell = st.session_state.get("spielweise")
    gewaehlt = st.selectbox(
        "Spielweise", schluessel,
        index=schluessel.index(aktuell) if aktuell in schluessel else None,
        format_func=lambda k: spielweisen.SPIELWEISEN[k].name,
        placeholder="Noch nicht gewaehlt",
        help="Die Spielweise bestimmt, welche Seiten die Navigation zeigt.",
    )
    if gewaehlt and gewaehlt != aktuell:
        st.session_state["spielweise"] = gewaehlt
        st.session_state["seite"] = spielweisen.SPIELWEISEN[gewaehlt].startseite
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Pokemon Business Intelligence",
        page_icon="◆",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    design.einbinden()
    design.plotly_grundstil()

    # Die Anmeldung steht VOR allem anderen: die Anwendung laeuft unter
    # bi.fablas.org im offenen Netz, und schon die Meta-Auswertung verraet,
    # womit sich der Betreiber auf ein Turnier vorbereitet. Ohne Anmeldung
    # wird ausschliesslich die Maske gezeichnet -- keine Navigation, keine
    # Seitenleiste, keine Daten. Fuer die lokale Entwicklung laesst sich das
    # ueber VGC_BI_ANMELDUNG=0 abschalten (siehe bi.ui.anmeldung).
    conn = komponenten.hole_verbindung()
    nutzerdaten.anhaengen(conn)
    nutzer = anmeldung.verlangen(conn)
    if nutzer is None:
        return

    with st.sidebar:
        st.markdown("## Pokemon Business Intelligence")
        st.caption("Champions, GO, Sammelkartenspiel, Hauptspiele und Shiny-Jagd")

        _spielweisenwahl()
        seite = _navigation()
        st.markdown("---")

        anmeldung.seitenleiste(conn, nutzer)
        st.markdown("---")

        _saisonauswahl()
        _zeige_status()

    SEITEN[seite]()


def _saisonauswahl() -> None:
    """Auswahl der auszuwertenden Saison.

    Ohne sie waere die archivierte Historie verloren, sobald Pokemon Champions
    eine neue Saison eroeffnet: die vorige verliert dann ihr Aktuell-Kennzeichen,
    und saemtliche Auswertungen filterten sie heraus. Die Daten blieben in
    Datenbank und Archiv liegen, waeren aber nicht mehr erreichbar -- ausgerechnet
    jene, deren Sicherung der Zweck des Archivs ist.

    Die Wahl reist an der Verbindung mit (:class:`bi.warehouse.Verbindung`) und
    wirkt damit auf jede Abfrage der Analyseschicht.
    """
    try:
        conn = komponenten.hole_verbindung()
        saisons = saison.verfuegbare(conn)
    except Exception:  # noqa: BLE001 -- der Statusblock meldet den Fehler
        return

    if not saisons:
        return

    schluessel = [s.schluessel for s in saisons]
    beschriftung = {s.schluessel: s.anzeige for s in saisons}

    if len(saisons) == 1:
        # Eine einzige Saison: ein Auswahlfeld waere blosse Zierde.
        st.markdown("**Saison**")
        st.caption(beschriftung[schluessel[0]])
        conn.saison_wahl = None
        return

    gewaehlt = st.selectbox(
        "Saison", schluessel, format_func=lambda s: beschriftung[s],
        key="saison_wahl",
        help="Aeltere Saisons stammen aus dem Archiv und sind bei der Quelle "
             "nicht mehr abrufbar.",
    )
    # None bedeutet "die laufende" -- so bleibt das Verhalten unveraendert,
    # wenn die laufende Saison ohnehin gewaehlt ist.
    conn.saison_wahl = None if saisons[0].schluessel == gewaehlt else gewaehlt
    komponenten.zwischenspeicher_leeren()


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
        "Quellen: Pokemon Champions Battle Data (Bewegungsdaten), PokeAPI "
        "(Stammdaten), pvpoke (Pokemon GO) und Limitless (Sammelkartenspiel). "
        "Die Anwendung steht in keiner Verbindung zu Nintendo, Game Freak, "
        "Niantic oder The Pokemon Company."
    )


if __name__ == "__main__":
    main()

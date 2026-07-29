"""Seite: ETL & Datenqualitaet.

Steuert die Ladelaeufe und macht den Zustand des Data Warehouse transparent:
Ladeprotokoll, Qualitaetsbericht, Schichtenuebersicht und Historisierung.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import quality, warehouse
from ..analytics import kpi
from ..config import STANDARD_ELO, STANDARD_MONATE
from ..etl import extract, pipeline
from .komponenten import ampel, hole_verbindung, kennzahl_kachel, zwischenspeicher_leeren


@st.cache_data(ttl=1800)
def _verfuegbare_formate() -> list[tuple[str, str, int]]:
    """Ermittelt die aktuell bei Smogon verfuegbaren VGC-Formate.

    Das Ergebnis wird zwischengespeichert, weil dafuer der Verzeichnisindex der
    Quelle abgerufen werden muss.
    """
    with extract.sitzung() as s:
        monate = extract.verfuegbare_monate(s, grenze=3)
        gesehen: dict[str, tuple[str, str, int]] = {}
        for monat in monate:
            for format_code, elo in extract.verfuegbare_formate(s, monat):
                ziel = extract.Datenabzugsziel(monat, format_code, elo, "")
                gesehen.setdefault(f"{format_code}-{elo}", (format_code, ziel.anzeige, elo))
    return sorted(gesehen.values(), key=lambda t: (t[0], -t[2]))


def zeichne() -> None:
    conn = hole_verbindung()

    st.title("ETL & Datenqualitaet")
    st.markdown(
        "Der Ladeprozess ist in zwei Teilprozesse getrennt. Die **Stammdaten** aus der "
        "PokeAPI aendern sich nur bei einer neuen Spielgeneration und werden selten "
        "geladen. Die **Bewegungsdaten** von Smogon erscheinen monatlich und werden "
        "regelmaessig nachgeladen."
    )

    reiter = st.tabs([
        "Ladelaeufe steuern", "Qualitaetsbericht", "Ladeprotokoll",
        "Schichten & Historisierung",
    ])

    with reiter[0]:
        _zeige_steuerung(conn)
    with reiter[1]:
        _zeige_qualitaet(conn)
    with reiter[2]:
        _zeige_protokoll(conn)
    with reiter[3]:
        _zeige_schichten(conn)


# --------------------------------------------------------------------------

def _zeige_steuerung(conn) -> None:
    """Schaltflaechen und Parameter der beiden Ladeprozesse."""
    befuellt = warehouse.ist_befuellt(conn)
    if not befuellt:
        st.warning(
            "Das Data Warehouse ist noch nicht vollstaendig befuellt. Fuehre zuerst "
            "Schritt 1 und anschliessend Schritt 2 aus."
        )

    links, rechts = st.columns(2)

    # ------------------------------------------------------------------
    with links:
        st.markdown("#### Schritt 1 · Stammdaten (PokeAPI)")
        anzahl = conn.execute(
            "SELECT COUNT(*) FROM Dim_Pokemon WHERE ist_aktuell = 1").fetchone()[0]
        st.caption(
            f"Aktuell {anzahl} Pokemon in der Dimension. Der Abzug umfasst rund 1350 "
            "Ressourcen und laeuft parallelisiert in etwa zehn Sekunden. Aenderungen "
            "an Basiswerten oder Typen werden bi-temporal historisiert."
        )

        if st.button("Stammdaten laden", type="primary", use_container_width=True):
            balken = st.progress(0.0, text="Starte ...")
            ergebnis = pipeline.stammdaten_laden(
                conn, lambda a, t: balken.progress(min(a, 1.0), text=t))
            balken.empty()
            zwischenspeicher_leeren()

            if ergebnis.erfolgreich:
                h = ergebnis.historisierung
                st.success(
                    f"{ergebnis.geladen} Pokemon verarbeitet. "
                    f"Neu: {h.get('neu', 0)} · Geaendert: {h.get('geaendert', 0)} · "
                    f"Unveraendert: {h.get('unveraendert', 0)}."
                )
            else:
                st.error(f"Der Ladelauf ist fehlgeschlagen: {ergebnis.meldung}")

    # ------------------------------------------------------------------
    with rechts:
        st.markdown("#### Schritt 2 · Bewegungsdaten (Smogon)")

        try:
            formate = _verfuegbare_formate()
        except Exception as fehler:  # noqa: BLE001
            st.error(f"Die verfuegbaren Formate konnten nicht ermittelt werden: {fehler}")
            formate = []

        if not formate:
            st.info("Es konnten keine Formate ermittelt werden. Bitte spaeter erneut versuchen.")
            return

        beschriftungen = {f"{anzeige} · ELO ab {elo}": (code, elo)
                          for code, anzeige, elo in formate}
        vorauswahl = next(
            (b for b in beschriftungen if f"ELO ab {STANDARD_ELO}" in b), list(beschriftungen)[0]
        )
        gewaehlt = st.selectbox(
            "Format und Skill-Stufe", list(beschriftungen.keys()),
            index=list(beschriftungen).index(vorauswahl),
            help="Die Skill-Stufe bestimmt, ab welcher Wertung die Partien in die "
                 "Auswertung eingehen. Hoehere Stufen bilden das Turniermeta genauer ab.",
        )
        format_code, elo = beschriftungen[gewaehlt]

        monate = st.slider(
            "Anzahl Monate der Zeitreihe", 1, 12, STANDARD_MONATE,
            help="Mehrere Monate sind die Voraussetzung fuer jede Trendauswertung.",
        )

        if st.button("Bewegungsdaten laden", type="primary", use_container_width=True):
            balken = st.progress(0.0, text="Starte ...")
            ergebnis = pipeline.bewegungsdaten_laden(
                conn, format_code, elo, monate,
                lambda a, t: balken.progress(min(a, 1.0), text=t))
            balken.empty()
            zwischenspeicher_leeren()

            if ergebnis.erfolgreich:
                st.success(ergebnis.meldung)
                for zeile in ergebnis.details:
                    st.markdown(f"- {zeile}")
                if ergebnis.abgewiesen:
                    st.warning(
                        f"{ergebnis.abgewiesen} Saetze wurden nicht geladen. "
                        "Einzelheiten im Qualitaetsbericht."
                    )
            else:
                st.error(f"Der Ladelauf ist fehlgeschlagen: {ergebnis.meldung}")

    st.markdown("---")
    with st.expander("Data Warehouse zuruecksetzen"):
        st.caption(
            "Das Zuruecksetzen verwirft geladene Daten. Die Stammdaten koennen dabei "
            "erhalten bleiben, da ihr erneuter Abzug den groessten Teil der Ladezeit "
            "ausmacht."
        )
        nur_fakten = st.checkbox("Stammdaten behalten, nur Bewegungsdaten verwerfen",
                                 value=True)
        if st.button("Zuruecksetzen"):
            warehouse.zuruecksetzen(conn, nur_fakten=nur_fakten)
            zwischenspeicher_leeren()
            st.success("Das Data Warehouse wurde zurueckgesetzt.")


def _zeige_qualitaet(conn) -> None:
    """Qualitaetsbericht mit Ampelbewertung."""
    ergebnisse = quality.pruefe_alles(conn)
    index = quality.qualitaetsindex(ergebnisse)

    spalten = st.columns(4)
    bestanden = sum(1 for e in ergebnisse if e.bestanden)
    spalten[0].markdown(kennzahl_kachel(
        "Qualitaetsindex", f"{index} %", "bestandene Regeln",
        "#2ecc71" if index >= 90 else "#f1c40f" if index >= 70 else "#e74c3c"),
        unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel(
        "Gepruefte Regeln", f"{bestanden} / {len(ergebnisse)}", "bestanden", "#6390F0"),
        unsafe_allow_html=True)

    befunde = pd.read_sql(
        "SELECT COUNT(*) AS n FROM DQ_Befund WHERE schweregrad IN ('Fehler', 'Warnung')", conn
    )["n"].iloc[0]
    spalten[2].markdown(kennzahl_kachel(
        "Offene Befunde", str(int(befunde)), "aus den Ladelaeufen",
        "#e74c3c" if befunde else "#2ecc71"), unsafe_allow_html=True)

    monate = kpi.verfuegbare_monate(conn)
    spalten[3].markdown(kennzahl_kachel(
        "Zeitreihe", f"{len(monate)} Monate",
        f"{monate[0]} bis {monate[-1]}" if monate else "keine Daten", "#A33EA1"),
        unsafe_allow_html=True)

    st.markdown("")
    st.markdown("#### Ergebnisse der Qualitaetsregeln")
    st.caption(
        "Die Regeln pruefen den geladenen Bestand als Ganzes. Sie decken Maengel auf, "
        "die am Einzelsatz nicht sichtbar sind -- etwa Luecken in der Zeitreihe oder "
        "verwaiste Fremdschluessel."
    )

    for dimension in ["Vollstaendigkeit", "Konsistenz", "Eindeutigkeit", "Genauigkeit",
                      "Aktualitaet"]:
        gruppe = [e for e in ergebnisse if e.dimension == dimension]
        if not gruppe:
            continue
        st.markdown(f"**{dimension}**")
        for e in gruppe:
            st.markdown(ampel(e.ampel, f"**{e.regel}** — {e.befund}"), unsafe_allow_html=True)
        st.markdown("")

    st.markdown("#### Befunde aus den Ladelaeufen")
    protokoll = pd.read_sql("""
        SELECT b.erfasst_am AS Zeitpunkt, l.quelle AS Quelle, b.regel AS Regel,
               b.dimension AS Dimension, b.klasse AS Klasse, b.schweregrad AS Schweregrad,
               b.entitaet AS Entitaet, b.schluessel AS Schluessel, b.meldung AS Meldung
        FROM DQ_Befund b JOIN ETL_Lauf l ON l.lauf_id = b.lauf_id
        ORDER BY b.befund_id DESC LIMIT 200
    """, conn)

    if protokoll.empty:
        st.success("Im letzten Ladelauf sind keine Befunde aufgetreten.")
    else:
        st.caption(
            "**Mangel 1. Klasse** ist automatisch erkennbar *und* automatisch "
            "korrigierbar, **Mangel 2. Klasse** ist erkennbar, erfordert aber eine "
            "fachliche Entscheidung."
        )
        st.dataframe(protokoll, use_container_width=True, hide_index=True, height=340)


def _zeige_protokoll(conn) -> None:
    """Historie aller Ladelaeufe."""
    laeufe = pd.read_sql("""
        SELECT lauf_id AS Lauf, gestartet_am AS Start, quelle AS Quelle,
               parameter AS Parameter, status AS Status,
               zeilen_gelesen AS Gelesen, zeilen_geladen AS Geladen,
               zeilen_abgewiesen AS Abgewiesen, dauer_sekunden AS "Dauer (s)",
               meldung AS Meldung
        FROM ETL_Lauf ORDER BY lauf_id DESC
    """, conn)

    if laeufe.empty:
        st.info("Es wurde noch kein Ladelauf durchgefuehrt.")
        return

    st.markdown(
        "Jeder Ladelauf wird mit Kennzahlen protokolliert. Die Gegenueberstellung von "
        "gelesenen, geladenen und abgewiesenen Zeilen macht Datenverluste im Prozess "
        "unmittelbar sichtbar."
    )
    st.dataframe(laeufe, use_container_width=True, hide_index=True)

    erfolgreich = laeufe[laeufe["Status"] == "erfolgreich"]
    if not erfolgreich.empty:
        spalten = st.columns(3)
        spalten[0].metric("Ladelaeufe gesamt", len(laeufe))
        spalten[1].metric("Mittlere Laufzeit",
                          f"{erfolgreich['Dauer (s)'].mean():.1f} s")
        quote = (100 * erfolgreich["Geladen"].sum()
                 / max(1, erfolgreich["Gelesen"].sum()))
        spalten[2].metric("Ladequote", f"{quote:.1f} %",
                          help="Anteil der gelesenen Saetze, die geladen wurden.")


def _zeige_schichten(conn) -> None:
    """Schichtenuebersicht und Nachweis der Historisierung."""
    st.markdown("#### Aufbau des Data Warehouse")
    st.caption(
        "Der Bestand ist in drei Schichten gegliedert: Staging/ODS haelt die "
        "unveraenderten Rohdaten, das Core Data Warehouse das integrierte und "
        "historisierte Galaxy-Schema, die Metadatenschicht die Protokolle."
    )

    statistik = pd.DataFrame(warehouse.tabellen_statistik(conn))
    for schicht in ["Staging / ODS", "Dimension", "Fakt", "Metadaten"]:
        teil = statistik[statistik["Schicht"] == schicht]
        if teil.empty:
            continue
        with st.expander(f"{schicht} · {int(teil['Zeilen'].sum()):,} Zeilen".replace(",", "."),
                         expanded=schicht == "Fakt"):
            st.dataframe(teil[["Tabelle", "Zeilen"]], use_container_width=True,
                         hide_index=True)

    st.markdown("#### Nachweis der Historisierung")
    st.caption(
        "``Dim_Pokemon`` ist bi-temporal ausgefuehrt. Aendert sich ein fachliches "
        "Attribut, wird der bisherige Satz abgegrenzt und ein neuer eroeffnet -- der "
        "alte Zustand bleibt auswertbar."
    )

    historie = pd.read_sql("""
        SELECT ist_aktuell AS "Aktuell", COUNT(*) AS "Saetze",
               MIN(gueltig_ab) AS "Fruehester Beginn", MAX(gueltig_ab) AS "Letzter Beginn"
        FROM Dim_Pokemon GROUP BY ist_aktuell
    """, conn)
    st.dataframe(historie, use_container_width=True, hide_index=True)

    geaendert = pd.read_sql("""
        SELECT slug AS "Bezeichner", anzeigename AS "Pokemon", gueltig_ab AS "Gueltig ab",
               gueltig_bis AS "Gueltig bis", ist_aktuell AS "Aktuell",
               typ_kombination AS "Typen", basiswert_summe AS "Basiswertsumme"
        FROM Dim_Pokemon
        WHERE slug IN (SELECT slug FROM Dim_Pokemon GROUP BY slug HAVING COUNT(*) > 1)
        ORDER BY slug, gueltig_ab
    """, conn)

    if geaendert.empty:
        st.info(
            "Bislang wurde keine Aenderung an den Stammdaten erkannt -- es existiert je "
            "Pokemon genau ein Gueltigkeitszeitraum. Sobald sich ein Basiswert oder Typ "
            "aendert, erscheint hier die vollstaendige Aenderungshistorie."
        )
    else:
        st.dataframe(geaendert, use_container_width=True, hide_index=True)

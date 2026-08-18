"""Seite: ETL & Datenqualitaet.

Steuert die Ladelaeufe und macht den Zustand des Data Warehouse transparent:
Archiv, Ladeprotokoll, Qualitaetsbericht, Schichtenuebersicht und Historisierung.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import quality, warehouse
from ..analytics import kpi
from ..config import QUELLE_VORHALTUNG_TAGE
from ..etl import champions, pipeline
from .komponenten import (
    befundzeile,
    hole_verbindung,
    kennzahl_kachel,
    seitenkopf,
    tabelle,
    zwischenspeicher_leeren,
)


def zeichne() -> None:
    conn = hole_verbindung()

    seitenkopf("ETL & Datenqualitaet", "Woher kommen die Daten, und wie gut sind sie?")
    st.markdown(
        "Der Ladeprozess ist in zwei Teilprozesse getrennt. Die **Stammdaten** aus der "
        "PokeAPI liefern Typen, Basiswerte und Attackeneigenschaften und aendern sich "
        "nur bei einer neuen Spielgeneration. Die **Bewegungsdaten** aus Pokemon "
        "Champions erscheinen taeglich und muessen regelmaessig geladen werden, weil "
        f"die Quelle nur rund {QUELLE_VORHALTUNG_TAGE} Tage vorhaelt."
    )

    reiter = st.tabs([
        "Ladelaeufe steuern", "Archiv", "Qualitaetsbericht",
        "Ladeprotokoll", "Schichten & Historisierung",
    ])

    with reiter[0]:
        _zeige_steuerung(conn)
    with reiter[1]:
        _zeige_archiv(conn)
    with reiter[2]:
        _zeige_qualitaet(conn)
    with reiter[3]:
        _zeige_protokoll(conn)
    with reiter[4]:
        _zeige_schichten(conn)


# --------------------------------------------------------------------------

def _zeige_steuerung(conn) -> None:
    """Schaltflaechen und Parameter der beiden Ladeprozesse."""
    if not warehouse.ist_befuellt(conn):
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
            "an Basiswerten oder Typen -- etwa durch eine Balance-Anpassung -- werden "
            "bi-temporal historisiert."
        )

        if st.button("Stammdaten laden", type="primary", width="stretch"):
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
        st.markdown("#### Schritt 2 · Bewegungsdaten (Pokemon Champions)")
        st.caption(
            "Laedt die taeglichen Nutzungsraenge sowie Attacken, Items, Faehigkeiten, "
            "Wesen und Statuspunkte fuer Einzel- und Doppelkampf. Der Lauf ist "
            "inkrementell: bereits archivierte Tage werden uebersprungen."
        )

        aus_archiv = st.checkbox(
            "Nur aus dem Archiv neu verarbeiten", value=False,
            help="Verarbeitet gesicherte Rohdaten erneut, ohne die Quelle abzurufen. "
                 "Nuetzlich, wenn sich Ableitungsregeln geaendert haben.",
        )

        if st.button("Champions-Daten laden", type="primary", width="stretch"):
            balken = st.progress(0.0, text="Starte ...")
            ergebnis = champions.laden(
                conn, aus_archiv=aus_archiv,
                fortschritt=lambda a, t: balken.progress(min(a, 1.0), text=t))
            balken.empty()
            zwischenspeicher_leeren()

            if ergebnis.get("erfolgreich"):
                st.success(ergebnis["meldung"])
                if ergebnis.get("neu_archiviert"):
                    st.info(f"{ergebnis['neu_archiviert']} Rohdatensaetze neu archiviert.")
                if ergebnis.get("abgewiesen"):
                    st.warning(
                        f"{ergebnis['abgewiesen']} Saetze wurden nicht geladen. "
                        "Einzelheiten im Qualitaetsbericht."
                    )
            else:
                st.error(f"Der Ladelauf ist fehlgeschlagen: {ergebnis.get('meldung')}")

    st.markdown("---")
    with st.expander("Data Warehouse zuruecksetzen"):
        st.caption(
            "Das Zuruecksetzen verwirft geladene Daten. Die Stammdaten koennen dabei "
            "erhalten bleiben, da ihr erneuter Abzug den groessten Teil der Ladezeit "
            "ausmacht."
        )
        nur_fakten = st.checkbox("Stammdaten behalten, nur Bewegungsdaten verwerfen",
                                 value=True)

        st.warning(
            "Das **Archiv** bleibt in jedem Fall erhalten. Die Quelle haelt nur rund "
            f"{QUELLE_VORHALTUNG_TAGE} Tage vor -- einmal verworfene Tage sind "
            "endgueltig verloren und nicht nachladbar."
        )
        archiv_verwerfen = st.checkbox(
            "Auch das Archiv unwiderruflich loeschen", value=False)

        if st.button("Zuruecksetzen"):
            warehouse.zuruecksetzen(conn, nur_fakten=nur_fakten,
                                    archiv_verwerfen=archiv_verwerfen)
            zwischenspeicher_leeren()
            st.success(
                "Das Data Warehouse wurde zurueckgesetzt."
                + ("" if archiv_verwerfen else " Das Archiv blieb erhalten.")
            )


def _zeige_archiv(conn) -> None:
    """Uebersicht ueber das dauerhaft gesicherte Rohdatenarchiv."""
    umfang = warehouse.archiv_umfang(conn)

    if not umfang or not umfang.get("saetze"):
        st.info("Das Archiv ist noch leer. Es fuellt sich mit dem ersten Ladelauf.")
        return

    st.markdown(
        f"Die Quelle haelt nur rund {QUELLE_VORHALTUNG_TAGE} Tage vor. Dieses Archiv "
        "sichert jeden geladenen Tag dauerhaft. Mit jedem Lauf waechst damit eine "
        "Zeitreihe, die an der Quelle selbst nicht mehr abrufbar ist -- der "
        "eigentliche Zweck eines Data Warehouse."
    )

    ueberschuss = max(0, int(umfang["tage"]) - QUELLE_VORHALTUNG_TAGE)

    spalten = st.columns(4)
    spalten[0].markdown(kennzahl_kachel(
        "Archivierte Tage", str(umfang["tage"]),
        f"{umfang['erster_tag']} bis {umfang['letzter_tag']}"),
        unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel(
        "Rohdatensaetze", f"{int(umfang['saetze']):,}".replace(",", "."),
        "dauerhaft gesichert"), unsafe_allow_html=True)
    spalten[2].markdown(kennzahl_kachel(
        "Saisons", str(umfang["saisons"]), "im Archiv vertreten"),
        unsafe_allow_html=True)
    # Erst dieser Ueberschuss belegt, dass das Archiv seinen Zweck erfuellt:
    # er umfasst genau die Tage, die die Quelle bereits vergessen hat.
    spalten[3].markdown(kennzahl_kachel(
        "Ueber die Quelle hinaus", f"{ueberschuss} Tage",
        f"Quelle haelt {QUELLE_VORHALTUNG_TAGE} Tage vor",
        "guenstig" if ueberschuss else "neutral"), unsafe_allow_html=True)

    if ueberschuss:
        st.success(
            f"Das Archiv enthaelt {ueberschuss} Tage, die an der Quelle nicht mehr "
            "abrufbar sind. Diese Historie existiert nur noch hier."
        )

    st.markdown("#### Bestand je Tag und Format")
    bestand = pd.read_sql("""
        SELECT datum_iso AS Datum, saison AS Saison, kampfformat AS Format,
               COUNT(*) AS "Erfasste Pokemon", MIN(archiviert_am) AS "Archiviert am"
        FROM Archiv_Champions
        GROUP BY datum_iso, saison, kampfformat
        ORDER BY datum_iso DESC, kampfformat
    """, conn)
    tabelle(bestand, height=340)

    st.markdown("#### Saisons")
    st.caption(
        "Jeder Faktensatz traegt seine Saison. Auswertungen begrenzen sich auf die "
        "laufende Saison, damit Pokemon aus abgelaufenen Regulationen und veraltete "
        "Werte das Ergebnis nicht verfaelschen."
    )
    saisons = pd.read_sql("""
        SELECT s.schluessel AS Saison, s.bezeichnung AS Bezeichnung,
               s.beginn AS Beginn, s.ende AS Ende,
               CASE s.ist_aktuell WHEN 1 THEN 'ja' ELSE 'nein' END AS Aktuell,
               q.name AS Quelle
        FROM Dim_Saison s JOIN Dim_Quelle q ON q.quelle_sk = s.quelle_sk
        ORDER BY s.ist_aktuell DESC, s.beginn DESC
    """, conn)
    tabelle(saisons)


def _zeige_qualitaet(conn) -> None:
    """Qualitaetsbericht mit Ampelbewertung."""
    ergebnisse = quality.pruefe_alles(conn)
    index = quality.qualitaetsindex(ergebnisse)

    spalten = st.columns(4)
    bestanden = sum(1 for e in ergebnisse if e.bestanden)
    # Gefaerbt wird an derselben Grenze, an der das Qualitaetstor der Workflows
    # entscheidet. Eine gruene Kachel bedeutet damit: der naechtliche Lauf ginge
    # mit diesem Bestand durch.
    spalten[0].markdown(kennzahl_kachel(
        "Qualitaetsindex", f"{index} %",
        f"bestandene Regeln · Tor bei {quality.MINDESTINDEX:.0f} %",
        "guenstig" if index >= quality.MINDESTINDEX else "gefahr"),
        unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel(
        "Gepruefte Regeln", f"{bestanden} / {len(ergebnisse)}", "bestanden"),
        unsafe_allow_html=True)

    befunde = pd.read_sql(
        "SELECT COUNT(*) AS n FROM DQ_Befund WHERE schweregrad IN ('Fehler', 'Warnung')", conn
    )["n"].iloc[0]
    spalten[2].markdown(kennzahl_kachel(
        "Offene Befunde", str(int(befunde)), "aus den Ladelaeufen",
        "gefahr" if befunde else "guenstig"), unsafe_allow_html=True)

    tage = kpi.verfuegbare_tage(conn)
    spalten[3].markdown(kennzahl_kachel(
        "Zeitreihe", f"{len(tage)} Tage",
        f"{tage[0]} bis {tage[-1]}" if tage else "keine Daten"),
        unsafe_allow_html=True)

    st.markdown("")
    st.markdown("#### Ergebnisse der Qualitaetsregeln")
    st.caption(
        "Die Regeln pruefen den geladenen Bestand als Ganzes. Sie decken Maengel auf, "
        "die am Einzelsatz nicht sichtbar sind -- etwa Luecken im Archiv, verwaiste "
        "Fremdschluessel oder Verletzungen der Spielregeln."
    )

    for dimension in ["Vollstaendigkeit", "Konsistenz", "Eindeutigkeit", "Wertebereich",
                      "Aktualitaet"]:
        gruppe = [e for e in ergebnisse if e.dimension == dimension]
        if not gruppe:
            continue
        st.markdown(f"**{dimension}**")
        for e in gruppe:
            st.markdown(befundzeile(e.stufe, f"**{e.regel}** — {e.befund}"),
                        unsafe_allow_html=True)
        st.markdown("")

    # Beobachtungen betreffen fremde Umstaende und gehen nicht in den Index ein.
    # Sie stehen deshalb neben den Regeln, nicht zwischen ihnen.
    beobachtungen = quality.beobachte_alles(conn)
    if beobachtungen:
        st.markdown("**Beobachtungen (ausserhalb der Bewertung)**")
        for b in beobachtungen:
            st.markdown(befundzeile("warnung", f"**{b.regel}** — {b.befund}"),
                        unsafe_allow_html=True)
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
        tabelle(protokoll, height=340)


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
    tabelle(laeufe)

    erfolgreich = laeufe[laeufe["Status"] == "erfolgreich"]
    if not erfolgreich.empty:
        spalten = st.columns(3)
        spalten[0].metric("Ladelaeufe gesamt", len(laeufe))
        spalten[1].metric("Mittlere Laufzeit", f"{erfolgreich['Dauer (s)'].mean():.1f} s")
        quote = 100 * erfolgreich["Geladen"].sum() / max(1, erfolgreich["Gelesen"].sum())
        spalten[2].metric("Ladequote", f"{quote:.1f} %",
                          help="Anteil der gelesenen Saetze, die geladen wurden.")


def _zeige_schichten(conn) -> None:
    """Schichtenuebersicht und Nachweis der Historisierung."""
    st.markdown("#### Aufbau des Data Warehouse")
    st.caption(
        "Der Bestand ist in drei Schichten gegliedert: Staging und Archiv halten die "
        "unveraenderten Rohdaten, das Core Data Warehouse das integrierte und "
        "historisierte Star-Schema, die Metadatenschicht die Protokolle."
    )

    statistik = pd.DataFrame(warehouse.tabellen_statistik(conn))
    for schicht in ["Staging / Archiv", "Dimension", "Fakt", "Metadaten"]:
        teil = statistik[statistik["Schicht"] == schicht]
        if teil.empty:
            continue
        with st.expander(f"{schicht} · {int(teil['Zeilen'].sum()):,} Zeilen".replace(",", "."),
                         expanded=schicht == "Fakt"):
            tabelle(teil[["Tabelle", "Zeilen"]])

    st.markdown("#### Nachweis der Historisierung")
    st.caption(
        "``Dim_Pokemon`` ist bi-temporal ausgefuehrt. Aendert sich ein fachliches "
        "Attribut -- etwa durch eine Balance-Anpassung zwischen zwei Saisons --, wird "
        "der bisherige Satz abgegrenzt und ein neuer eroeffnet. Der alte Zustand "
        "bleibt auswertbar."
    )

    historie = pd.read_sql("""
        SELECT ist_aktuell AS "Aktuell", COUNT(*) AS "Saetze",
               MIN(gueltig_ab) AS "Fruehester Beginn", MAX(gueltig_ab) AS "Letzter Beginn"
        FROM Dim_Pokemon GROUP BY ist_aktuell
    """, conn)
    tabelle(historie)

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
        tabelle(geaendert)

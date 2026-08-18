"""Anmeldung und Sitzungsverwaltung der Oberflaeche.

Die Anwendung laeuft unter ``bi.fablas.org`` im offenen Netz. Ohne Anmeldung
stuende das PC-System jedem Besucher offen -- und eigene Teams sind genau die
Information, die ein Turniergegner gerne haette.

Gestaltung: die Maske folgt dem Designsystem der Anwendung
(:mod:`bi.ui.design`) und damit derselben Farb- und Formsprache wie die
uebrige Seite unter ``fablas.org`` -- dunkle Flaeche, Markenblau als Akzent,
Gelb ausschliesslich fuer die eine gesuchte Handlung.

Ablauf:

* Beim allerersten Start existiert kein Konto. Die Maske bietet dann die
  **Einrichtung** an; das erste Konto erhaelt die Verwaltungsrolle.
* Danach ist die Selbstregistrierung nur mit Zugangscode moeglich
  (``VGC_BI_REGISTRIERUNGSCODE``), damit nicht jeder Besucher der oeffentlichen
  Adresse Konten anlegen kann.
* Nach ``ANMELDUNG_MAX_FEHLVERSUCHE`` Fehlversuchen in
  ``ANMELDUNG_SPERRE_MINUTEN`` Minuten wird das Konto voruebergehend gesperrt --
  gezaehlt wird ueber das Anmeldeprotokoll, die Sperre uebersteht damit auch
  einen Neustart des Dienstes.
* Die Anmeldung selbst lebt im ``st.session_state`` des Browsers und endet mit
  dem Schliessen des Tabs. Fuer den Einsatzzweck ist das die richtige Balance:
  kein eigenes Token-System, aber auch keine dauerhafte Anmeldung auf fremden
  Geraeten.

Fuer die lokale Entwicklung laesst sich die Anmeldung ueber
``VGC_BI_ANMELDUNG=0`` abschalten; es wird dann ein Gastkonto verwendet.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from .. import nutzerdaten
from ..config import (
    ANMELDUNG_ERFORDERLICH,
    ANMELDUNG_MAX_FEHLVERSUCHE,
    ANMELDUNG_SPERRE_MINUTEN,
    REGISTRIERUNGSCODE,
)
from . import design


def _gast() -> nutzerdaten.Nutzer:
    return nutzerdaten.Nutzer(0, "gast", "Gast (Anmeldung abgeschaltet)", "verwaltung")


def angemeldeter_nutzer(conn) -> nutzerdaten.Nutzer | None:
    """Der angemeldete Nutzer dieser Sitzung, oder ``None``."""
    if not ANMELDUNG_ERFORDERLICH:
        return _gast()
    return st.session_state.get("nutzer")


def abmelden() -> None:
    st.session_state.pop("nutzer", None)


def _gesperrt(conn, benutzername: str) -> bool:
    seit = (datetime.now() - timedelta(minutes=ANMELDUNG_SPERRE_MINUTEN)).isoformat(
        timespec="seconds")
    return nutzerdaten.fehlversuche_seit(conn, benutzername, seit) >= ANMELDUNG_MAX_FEHLVERSUCHE


def _kopf() -> None:
    """Markenkopf der Maske -- die Wiedererkennung zur Hauptseite fablas.org."""
    st.markdown(
        f"""<div style='text-align:center;padding:28px 0 8px;'>
        <div style='font-size:2.2rem;font-weight:800;letter-spacing:0.02em;'>
          <span style='color:{design.POKEMON_BLAU};'>VGC</span>
          <span style='color:{design.POKEMON_GELB};
                text-shadow:-1px 1px 0 {design.POKEMON_GOLD};'>Business Intelligence</span>
        </div>
        <div style='opacity:0.7;margin-top:4px;'>bi.fablas.org · Data Warehouse und
        Analytics fuer Pokemon Champions</div></div>""",
        unsafe_allow_html=True,
    )


def verlangen(conn) -> nutzerdaten.Nutzer | None:
    """Zeichnet die Anmeldemaske, solange niemand angemeldet ist.

    Rueckgabe: der angemeldete Nutzer -- oder ``None``, dann hat die Maske
    uebernommen und die aufrufende Seite zeichnet nichts weiter.
    """
    nutzer = angemeldeter_nutzer(conn)
    if nutzer:
        return nutzer

    _kopf()
    erster_start = nutzerdaten.anzahl_nutzer(conn) == 0

    breite = st.columns([1, 1.2, 1])
    with breite[1]:
        if erster_start:
            _einrichtung(conn)
        else:
            _maske(conn)
    return None


def _einrichtung(conn) -> None:
    """Anlage des ersten Kontos -- einmalig, mit Verwaltungsrolle."""
    st.info("**Einrichtung:** Es existiert noch kein Konto. Das erste Konto "
            "erhaelt die Verwaltungsrolle.")
    with st.form("einrichtung"):
        benutzername = st.text_input("Benutzername")
        anzeigename = st.text_input("Anzeigename (optional)")
        passwort = st.text_input("Passwort", type="password",
                                 help="Mindestens 10 Zeichen. Laenge schlaegt Sonderzeichen.")
        wiederholung = st.text_input("Passwort wiederholen", type="password")
        if st.form_submit_button("Konto anlegen", type="primary", width="stretch"):
            if passwort != wiederholung:
                st.error("Die Passwoerter stimmen nicht ueberein.")
                return
            try:
                nutzer = nutzerdaten.anlegen(conn, benutzername, passwort,
                                             anzeigename or None)
            except ValueError as fehler:
                st.error(str(fehler))
                return
            st.session_state["nutzer"] = nutzer
            st.rerun()


def _maske(conn) -> None:
    anmeldung, registrierung = st.tabs(["Anmelden", "Konto anlegen"])

    with anmeldung, st.form("anmeldung"):
        benutzername = st.text_input("Benutzername")
        passwort = st.text_input("Passwort", type="password")
        if st.form_submit_button("Anmelden", type="primary", width="stretch"):
            if _gesperrt(conn, benutzername):
                st.error(f"Zu viele Fehlversuche. Bitte in {ANMELDUNG_SPERRE_MINUTEN} "
                         f"Minuten erneut versuchen.")
                return
            nutzer = nutzerdaten.anmelden(conn, benutzername, passwort)
            if nutzer is None:
                # Bewusst dieselbe Meldung fuer unbekannten Namen und falsches
                # Passwort: die Maske darf nicht verraten, welche Konten es gibt.
                st.error("Anmeldung fehlgeschlagen.")
                return
            st.session_state["nutzer"] = nutzer
            st.rerun()

    with registrierung, st.form("registrierung"):
        if REGISTRIERUNGSCODE:
            st.caption("Fuer die Registrierung ist ein Zugangscode erforderlich.")
        benutzername = st.text_input("Benutzername", key="reg_name")
        passwort = st.text_input("Passwort", type="password", key="reg_pw",
                                 help="Mindestens 10 Zeichen.")
        wiederholung = st.text_input("Passwort wiederholen", type="password", key="reg_pw2")
        code = st.text_input("Zugangscode", type="password") if REGISTRIERUNGSCODE else ""
        if st.form_submit_button("Konto anlegen", width="stretch"):
            if REGISTRIERUNGSCODE and code != REGISTRIERUNGSCODE:
                st.error("Der Zugangscode stimmt nicht.")
                return
            if passwort != wiederholung:
                st.error("Die Passwoerter stimmen nicht ueberein.")
                return
            try:
                nutzer = nutzerdaten.anlegen(conn, benutzername, passwort)
            except ValueError as fehler:
                st.error(str(fehler))
                return
            st.session_state["nutzer"] = nutzer
            st.rerun()


def seitenleiste(conn, nutzer: nutzerdaten.Nutzer) -> None:
    """Kontoblock fuer die Seitenleiste."""
    if not ANMELDUNG_ERFORDERLICH:
        st.caption("Anmeldung abgeschaltet (VGC_BI_ANMELDUNG=0) -- Gastbetrieb.")
        return
    spalten = st.columns([2, 1])
    with spalten[0]:
        st.markdown(f"**{nutzer.anzeigename}**")
        st.caption("Verwaltung" if nutzer.ist_verwaltung else "Spieler")
    with spalten[1]:
        if st.button("Abmelden", width="stretch"):
            abmelden()
            st.rerun()

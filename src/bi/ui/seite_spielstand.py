"""Seite: Spielstand -- Durchspielen und Nuzlocke.

Eine Seite fuer zwei Spielweisen. Der Unterschied ist die **Art** des Laufs,
und die liegt an den Daten (:mod:`bi.spielstand`): ein Nuzlocke-Lauf traegt
seine Regeln, und die Datenschicht setzt sie durch -- die Seite muss sie
nicht kennen. Was sie kennt, ist die Ueberschrift und welche Art sie beim
Anlegen vorschlaegt.

Die Auswertung ist bewusst die eines Arenaleiter-Kampfes, nicht eines
Turniers: Welche Angriffstypen treffen mein Team gemeinsam, und wer im Team
faengt sie ab? Dafuer genuegt die Typen-Regelbasis; Ranked-Daten braucht es
nicht.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import nutzerdaten, spielstand
from ..config import TYP_DEUTSCH, sprite_url
from . import anmeldung
from .komponenten import (
    hole_verbindung,
    kennzahl_kachel,
    name_mit_deutsch,
    seitenkopf,
    tabelle,
    typ_abzeichen,
    typ_abzeichen_paar,
)

_KOPF = {
    "nuzlocke": ("Nuzlocke-Lauf",
                 "Erste Begegnung je Ort, gefallen ist gefallen -- und die Frage, "
                 "ob das Team den naechsten Arenaleiter uebersteht"),
    "normal": ("Spielstand",
               "Team, Orden und Begegnungen des laufenden Durchgangs -- mit den "
               "Typen-Luecken des Teams"),
}


def zeichne(art: str = "normal") -> None:
    conn = hole_verbindung()
    nutzerdaten.anhaengen(conn)
    nutzer = anmeldung.verlangen(conn)
    if nutzer is None:
        return

    titel, aufgabe = _KOPF[art]
    seitenkopf(titel, aufgabe)

    laeufe = spielstand.laeufe_lesen(conn, nutzer.nutzer_id, art)
    lauf = _laufauswahl(conn, nutzer, laeufe, art)
    if lauf is None:
        return

    begegnungen = spielstand.begegnungen_lesen(conn, nutzer.nutzer_id, lauf["lauf_id"])
    _kopfzeile(conn, nutzer, lauf, begegnungen)

    team, eintragen, alle = st.tabs(["Team und Luecken", "Begegnung eintragen", "Alle Begegnungen"])
    with team:
        _team(conn, nutzer, lauf, begegnungen)
    with eintragen:
        _eintragen(conn, nutzer, lauf)
    with alle:
        _alle(conn, nutzer, lauf, begegnungen)


# --------------------------------------------------------------------------
# Lauf waehlen oder anlegen
# --------------------------------------------------------------------------

def _laufauswahl(conn, nutzer, laeufe: list[dict], art: str) -> dict | None:
    spalten = st.columns([2, 1])
    with spalten[0]:
        lauf = st.selectbox(
            "Lauf", laeufe, index=0 if laeufe else None, key=f"lauf_wahl_{art}",
            format_func=lambda lauf: (
                f"{lauf['name']} · {lauf['spiel']} · {lauf['orden']} Orden · {lauf['status']}"),
            placeholder="Noch kein Lauf -- rechts anlegen")
    with spalten[1], st.popover("Neuen Lauf anlegen", width="stretch"):
        _lauf_anlegen(conn, nutzer, art)
    return lauf


def _lauf_anlegen(conn, nutzer, art: str) -> None:
    with st.form(f"lauf_anlegen_{art}"):
        name = st.text_input("Name des Laufs", placeholder="z. B. Platin, zweiter Versuch")
        generation = st.selectbox("Generation", list(spielstand.EDITIONEN),
                                  format_func=lambda g: f"Generation {g}")
        spiel = st.selectbox("Edition", spielstand.EDITIONEN[generation])
        regeln = []
        if art == "nuzlocke":
            st.markdown("**Regeln**")
            for schluessel, text in spielstand.NUZLOCKE_REGELN.items():
                if st.checkbox(text, value=True, key=f"regel_{schluessel}"):
                    regeln.append(schluessel)
        if st.form_submit_button("Anlegen", type="primary"):
            try:
                spielstand.lauf_anlegen(conn, nutzer.nutzer_id, name, spiel, art,
                                        regeln if art == "nuzlocke" else [])
                st.rerun()
            except ValueError as fehler:
                st.error(str(fehler))


# --------------------------------------------------------------------------
# Kopfzeile: Kennzahlen, Orden, Status
# --------------------------------------------------------------------------

def _kopfzeile(conn, nutzer, lauf: dict, begegnungen: list[dict]) -> None:
    zahlen = spielstand.bilanz(begegnungen)
    ist_nuzlocke = lauf["art"] == "nuzlocke"

    kacheln = st.columns(5)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Orden", f"{lauf['orden']} / 8",
                                    lauf["spiel"]), unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("Im Team", str(zahlen["team"]),
                                    f"{zahlen['box']} in der Box"), unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("Begegnungen", str(zahlen["begegnungen"]),
                                    f"an {zahlen['orte']} Orten"), unsafe_allow_html=True)
    with kacheln[3]:
        st.markdown(kennzahl_kachel(
            "Gefallen", str(zahlen["gefallen"]),
            "Friedhof" if ist_nuzlocke else "besiegt im Kampf",
            bedeutung="gefahr" if ist_nuzlocke and zahlen["gefallen"] else "neutral"),
            unsafe_allow_html=True)
    with kacheln[4]:
        st.markdown(kennzahl_kachel("Verpasst", str(zahlen["verpasst"]),
                                    "entkommen oder besiegt statt gefangen"),
                    unsafe_allow_html=True)

    if lauf["regeln"]:
        st.caption("Regeln: " + " · ".join(
            spielstand.NUZLOCKE_REGELN.get(r, r) for r in lauf["regeln"]))

    with st.expander("Lauf fortschreiben: Orden, Status, Loeschen"):
        spalten = st.columns([1, 1, 1])
        with spalten[0]:
            orden = st.number_input("Orden", min_value=0, max_value=16,
                                    value=int(lauf["orden"]), key=f"orden_{lauf['lauf_id']}")
        with spalten[1]:
            status = st.selectbox("Status", list(spielstand.LAUF_STATUS),
                                  index=list(spielstand.LAUF_STATUS).index(lauf["status"]),
                                  key=f"status_{lauf['lauf_id']}")
        with spalten[2]:
            st.markdown("&nbsp;")
            if st.button("Uebernehmen", key=f"lauf_speichern_{lauf['lauf_id']}",
                         width="stretch"):
                spielstand.lauf_aktualisieren(conn, nutzer.nutzer_id, lauf["lauf_id"],
                                              orden=int(orden), status=status)
                st.rerun()
        if st.button("Lauf loeschen", key=f"lauf_loeschen_{lauf['lauf_id']}"):
            spielstand.lauf_loeschen(conn, nutzer.nutzer_id, lauf["lauf_id"])
            st.rerun()


# --------------------------------------------------------------------------
# Team und Typen-Luecken
# --------------------------------------------------------------------------

def _team(conn, nutzer, lauf: dict, begegnungen: list[dict]) -> None:
    team = [b for b in begegnungen if b["status"] == "team"]
    if not team:
        st.info("Noch kein Pokemon im Team. Unter *Begegnung eintragen* das erste fangen.")
        return

    spalten = st.columns(max(len(team), 1))
    for spalte, mitglied in zip(spalten, team, strict=False):
        with spalte:
            if mitglied.get("pokedex_id"):
                st.image(sprite_url(int(mitglied["pokedex_id"])), width=88)
            name = mitglied.get("anzeigename") or mitglied["slug"]
            st.markdown(f"**{mitglied['spitzname'] or name}**")
            st.caption(name + (f" · Lv. {mitglied['stufe']}" if mitglied.get("stufe") else ""))
            st.markdown(typ_abzeichen_paar(mitglied.get("typ1"), mitglied.get("typ2")),
                        unsafe_allow_html=True)
            ziel = st.selectbox(
                "Status", ["team", "box", "tot"], key=f"team_status_{mitglied['begegnung_id']}",
                format_func=lambda s: spielstand.STATUS_NAME[s], label_visibility="collapsed")
            if ziel != "team" and st.button(
                    "Wechseln", key=f"team_wechsel_{mitglied['begegnung_id']}", width="stretch"):
                try:
                    spielstand.begegnung_status_setzen(
                        conn, nutzer.nutzer_id, mitglied["begegnung_id"], ziel)
                    st.rerun()
                except ValueError as fehler:
                    st.error(str(fehler))

    st.markdown("#### Typen-Luecken des Teams")
    st.caption(
        "Fuer jeden Angriffstyp: wie viele Teammitglieder ihn doppelt nehmen und "
        "wie viele ihn widerstehen. Ein Typ, der mehr trifft als abgefangen wird, "
        "ist die Luecke, die der naechste Arenaleiter findet."
    )
    schwaechen = spielstand.team_schwaechen(team)
    luecken = [s for s in schwaechen if s["schwach"] > s["widerstand"]]
    if luecken:
        st.markdown("Offene Luecken: " + "".join(
            typ_abzeichen(s["typ"]) + f"<span class='kachel-hinweis'>{s['schwach']}x schwach, "
            f"{s['widerstand']}x widerstanden&nbsp;&nbsp;</span>" for s in luecken),
            unsafe_allow_html=True)
    else:
        st.markdown(kennzahl_kachel("Keine offene Luecke", "0",
                                    "jeder Angriffstyp wird von mindestens so vielen "
                                    "abgefangen wie getroffen", bedeutung="guenstig"),
                    unsafe_allow_html=True)

    uebersicht = pd.DataFrame([{
        "Typ": TYP_DEUTSCH.get(s["typ"], s["typ"]), "Schwach": s["schwach"],
        "Widerstand": s["widerstand"], "Bilanz": s["bilanz"],
    } for s in schwaechen])
    tabelle(uebersicht, height=300)

    box = [b for b in begegnungen if b["status"] == "box"]
    if box:
        st.markdown("#### In der Box")
        for eintrag in box:
            name = eintrag.get("anzeigename") or eintrag["slug"]
            zeile = st.columns([3, 1])
            with zeile[0]:
                st.markdown(f"**{eintrag['spitzname'] or name}** · {name} · {eintrag['ort']}")
            with zeile[1]:
                if st.button("Ins Team", key=f"box_ins_team_{eintrag['begegnung_id']}",
                             width="stretch"):
                    try:
                        spielstand.begegnung_status_setzen(
                            conn, nutzer.nutzer_id, eintrag["begegnung_id"], "team")
                        st.rerun()
                    except ValueError as fehler:
                        st.error(str(fehler))

    gefallen = [b for b in begegnungen if b["status"] == "tot"]
    if gefallen:
        st.markdown("#### Friedhof" if lauf["art"] == "nuzlocke" else "#### Gefallen")
        st.markdown(" · ".join(
            f"{b['spitzname'] or b.get('anzeigename') or b['slug']} ({b['ort']})"
            for b in gefallen))


# --------------------------------------------------------------------------
# Begegnung eintragen
# --------------------------------------------------------------------------

def _eintragen(conn, nutzer, lauf: dict) -> None:
    pokemon = pd.read_sql(
        "SELECT slug, anzeigename FROM Dim_Pokemon WHERE ist_aktuell = 1 ORDER BY anzeigename",
        conn)
    if pokemon.empty:
        st.info("Die Pokemon-Stammdaten sind noch nicht geladen.")
        return
    namen = dict(zip(pokemon["anzeigename"], pokemon["slug"], strict=True))

    gewaehlt = st.selectbox("Pokemon", list(namen), index=None,
                            key=f"begegnung_pokemon_{lauf['lauf_id']}",
                            format_func=name_mit_deutsch, placeholder="Pokemon waehlen ...")
    with st.form(f"begegnung_{lauf['lauf_id']}"):
        spalten = st.columns([2, 1, 1])
        with spalten[0]:
            ort = st.text_input("Ort", placeholder="Route 203, Ewigwald, ...")
        with spalten[1]:
            stufe = st.number_input("Stufe", min_value=1, max_value=100, value=5)
        with spalten[2]:
            status = st.selectbox("Was wurde daraus?", list(spielstand.STATUS),
                                  format_func=lambda s: spielstand.STATUS_NAME[s])
        spitzname = st.text_input("Spitzname" + (" (Pflicht bei Fang)"
                                                  if "spitzname" in lauf["regeln"] else ""))
        notiz = st.text_input("Notiz (optional)")
        if st.form_submit_button("Eintragen", type="primary"):
            if not gewaehlt:
                st.error("Bitte ein Pokemon waehlen.")
                return
            try:
                spielstand.begegnung_speichern(
                    conn, nutzer.nutzer_id, lauf["lauf_id"], ort, namen[gewaehlt], status,
                    spitzname or None, int(stufe), notiz or None)
                st.rerun()
            except ValueError as fehler:
                st.error(str(fehler))


# --------------------------------------------------------------------------
# Alle Begegnungen
# --------------------------------------------------------------------------

def _alle(conn, nutzer, lauf: dict, begegnungen: list[dict]) -> None:
    if not begegnungen:
        st.caption("Noch keine Begegnung eingetragen.")
        return
    uebersicht = pd.DataFrame([{
        "Nr.": b["reihenfolge"], "Ort": b["ort"],
        "Pokemon": b.get("anzeigename") or b["slug"], "Spitzname": b.get("spitzname") or "",
        "Stufe": b.get("stufe"), "Status": spielstand.STATUS_NAME[b["status"]],
        "Notiz": b.get("notiz") or "",
    } for b in begegnungen])
    tabelle(uebersicht)

    with st.expander("Begegnung entfernen"):
        auswahl = st.selectbox(
            "Begegnung", begegnungen, key=f"begegnung_entfernen_{lauf['lauf_id']}",
            format_func=lambda b: f"{b['reihenfolge']}. {b['ort']} · "
                                  f"{b.get('anzeigename') or b['slug']}")
        if auswahl and st.button("Entfernen", key=f"begegnung_entfernen_knopf_{lauf['lauf_id']}"):
            spielstand.begegnung_loeschen(conn, nutzer.nutzer_id, auswahl["begegnung_id"])
            st.rerun()

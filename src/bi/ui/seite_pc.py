"""Seite: PC-System.

Das PC-System ist die eigene Datenhaltung des Projekts: welche Pokemon jemand
besitzt, wie sie trainiert sind (Item, Faehigkeit, Wesen, Statuspunkte,
Attacken) und zu welchen Teams sie gehoeren. Der Name folgt dem PC aus den
Spielen, in dem gefangene Pokemon abgelegt werden.

Anders als alle uebrigen Seiten liest diese nicht nur, sie **schreibt** -- und
zwar in die Nutzerdatenbank, nicht in das Warehouse. Das Warehouse wird bei
jedem Kaltstart aus dem Archiv neu erzeugt; eigene Eintraege dort waeren beim
naechsten Start fort (siehe :mod:`bi.nutzerdaten`).

Die Stammdaten der Auswahlfelder kommen aus dem Warehouse: angeboten wird, was
``Dim_Pokemon``, ``Dim_Item`` und ``Dim_Attacke`` fuehren. Damit erfasst das
PC-System keine Freitexte, sondern verknuepfbare Schluessel -- die Grundlage
dafuer, dass Schadensrechner und Team-Analysen eigene Pokemon genauso
verarbeiten koennen wie die der Meta.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import nutzerdaten
from ..analytics import einsatz
from ..config import KAMPFFORMATE, MITNAHME, sprite_url
from ..spielstand import ALLE_EDITIONEN
from ..stats import (
    MAX_SP_JE_WERT,
    SP_BUDGET,
    STATUSWERTE,
    WESEN,
    alle_statuswerte,
    pruefe_statuspunkte,
)
from . import anmeldung
from .komponenten import (
    attacke_mit_deutsch,
    faehigkeit_mit_deutsch,
    hole_verbindung,
    item_mit_deutsch,
    kennzahl_kachel,
    name_mit_deutsch,
    seitenkopf,
    tabelle,
    typ_abzeichen_paar,
)

PUNKTE_BESCHRIFTUNG = {
    "hp": "KP", "attack": "Angriff", "defense": "Verteidigung",
    "sp_attack": "Sp. Angriff", "sp_defense": "Sp. Verteidigung", "speed": "Initiative",
}

# Woher ein Pokemon stammen kann: die Editionen der Hauptspiele und die
# uebrigen Spielformen. Eine Auswahlliste, kein Freitext -- siehe
# ``bi.spielstand.EDITIONEN``.
HERKUENFTE = ("Pokemon Champions", "Pokemon GO", "Pokemon HOME", "Tausch", *ALLE_EDITIONEN)


def _stammdaten(conn) -> dict[str, pd.DataFrame]:
    """Auswahllisten aus den Dimensionen des Warehouse."""
    return {
        "pokemon": pd.read_sql(
            "SELECT slug, anzeigename, typ1, typ2, pokedex_id, hp, attack, defense, "
            "sp_attack, sp_defense, speed FROM Dim_Pokemon WHERE ist_aktuell = 1 "
            "ORDER BY anzeigename", conn),
        "items": pd.read_sql(
            "SELECT slug, anzeigename, wirkung_klasse FROM Dim_Item "
            "WHERE ist_kampfrelevant = 1 ORDER BY anzeigename", conn),
        "faehigkeiten": pd.read_sql(
            "SELECT slug, anzeigename FROM Dim_Faehigkeit ORDER BY anzeigename", conn),
        "attacken": pd.read_sql(
            "SELECT slug, anzeigename, typ, kategorie FROM Dim_Attacke "
            "ORDER BY anzeigename", conn),
    }


def zeichne() -> None:
    conn = hole_verbindung()
    nutzerdaten.anhaengen(conn)

    nutzer = anmeldung.verlangen(conn)
    if nutzer is None:
        return

    seitenkopf("PC-System",
               "Eigene Pokemon erfassen, trainieren, zu Teams zusammenstellen -- "
               "und wissen, wo sie gerade kompetitiv einsetzbar sind")

    stamm = _stammdaten(conn)
    if stamm["pokemon"].empty:
        st.info("Die Pokemon-Stammdaten sind noch nicht geladen. Das PC-System "
                "braucht sie fuer die Auswahlfelder -- bitte zuerst unter "
                "*ETL & Datenqualitaet* laden.")
        return

    box, check, teams, erfassen = st.tabs(["Box", "Einsatzcheck", "Teams", "Pokemon ablegen"])
    with erfassen:
        _erfassung(conn, nutzer, stamm)
    with box:
        _box(conn, nutzer)
    with check:
        _einsatzcheck(conn, nutzer)
    with teams:
        _teams(conn, nutzer)


# --------------------------------------------------------------------------
# Erfassung
# --------------------------------------------------------------------------

def _erfassung(conn, nutzer, stamm: dict[str, pd.DataFrame],
               vorhanden: dict | None = None) -> None:
    pokemon = stamm["pokemon"]
    namen = dict(zip(pokemon["anzeigename"], pokemon["slug"], strict=True))

    gewaehlt = st.selectbox("Pokemon", list(namen), index=None,
                            format_func=name_mit_deutsch,
                            placeholder="Pokemon waehlen ...")
    if not gewaehlt:
        return
    zeile = pokemon.loc[pokemon["anzeigename"] == gewaehlt].iloc[0]

    kopf = st.columns([1, 3])
    with kopf[0]:
        st.image(sprite_url(int(zeile["pokedex_id"])), width=120)
    with kopf[1]:
        st.markdown(f"### {gewaehlt}")
        st.markdown(typ_abzeichen_paar(zeile["typ1"], zeile["typ2"]),
                    unsafe_allow_html=True)

    with st.form("box_erfassung"):
        oben = st.columns([2, 2, 1])
        with oben[0]:
            spitzname = st.text_input("Spitzname (optional)")
        with oben[1]:
            herkunft = st.selectbox("Herkunft (Spiel)", list(HERKUENFTE), index=None,
                                    placeholder="Nicht angegeben")
        with oben[2]:
            st.markdown("&nbsp;")
            ist_shiny = st.checkbox("Shiny")

        auswahl = st.columns(3)
        with auswahl[0]:
            item = st.selectbox("Item", stamm["items"]["anzeigename"].tolist() or ["-"],
                                index=None, format_func=item_mit_deutsch,
                                placeholder="Kein Item")
        with auswahl[1]:
            faehigkeit = st.selectbox(
                "Faehigkeit", stamm["faehigkeiten"]["anzeigename"].tolist() or ["-"],
                index=None, format_func=faehigkeit_mit_deutsch,
                placeholder="Nicht angegeben")
        with auswahl[2]:
            wesen = st.selectbox("Wesen", list(WESEN), index=list(WESEN).index("Hardy"))

        attacken = st.multiselect("Attacken (bis zu vier)",
                                  stamm["attacken"]["anzeigename"].tolist(),
                                  format_func=attacke_mit_deutsch,
                                  max_selections=4)

        st.markdown(f"**Statuspunkte** -- hoechstens {MAX_SP_JE_WERT} je Wert, "
                    f"{SP_BUDGET} insgesamt (Champions-Regeln)")
        punkte = {}
        felder = st.columns(6)
        for feld, name in zip(felder, STATUSWERTE, strict=True):
            with feld:
                punkte[name] = st.number_input(
                    PUNKTE_BESCHRIFTUNG[name], min_value=0, max_value=MAX_SP_JE_WERT,
                    value=0, key=f"pc_punkte_{name}")

        notiz = st.text_area("Notiz (optional)", height=68)

        if st.form_submit_button("In der Box ablegen", type="primary"):
            verstoesse = pruefe_statuspunkte(punkte)
            if verstoesse:
                for text in verstoesse:
                    st.error(text)
                return
            items = dict(zip(stamm["items"]["anzeigename"], stamm["items"]["slug"],
                             strict=True))
            faehigkeiten = dict(zip(stamm["faehigkeiten"]["anzeigename"],
                                    stamm["faehigkeiten"]["slug"], strict=True))
            attackenkarte = dict(zip(stamm["attacken"]["anzeigename"],
                                     stamm["attacken"]["slug"], strict=True))
            nutzerdaten.box_speichern(conn, nutzer.nutzer_id, {
                "slug": namen[gewaehlt],
                "spitzname": spitzname or None,
                "item_slug": items.get(item),
                "faehigkeit_slug": faehigkeiten.get(faehigkeit),
                "wesen": wesen,
                **{f"punkte_{name}": punkte[name] for name in STATUSWERTE},
                "attacken": [attackenkarte[a] for a in attacken if a in attackenkarte],
                "notiz": notiz or None,
                "ist_shiny": int(ist_shiny),
                "herkunft": herkunft,
            })
            st.success(f"{gewaehlt} liegt in der Box.")
            st.rerun()

    # Live-Vorschau der Endwerte ausserhalb des Formulars ist nicht moeglich
    # (Formulare uebertragen erst beim Absenden); die Werte stehen nach dem
    # Ablegen in der Box.


# --------------------------------------------------------------------------
# Box
# --------------------------------------------------------------------------

def _box(conn, nutzer) -> None:
    eintraege = nutzerdaten.box_lesen(conn, nutzer.nutzer_id)
    if not eintraege:
        st.info("Die Box ist leer. Unter *Pokemon ablegen* den ersten Eintrag anlegen.")
        return

    st.caption(f"{len(eintraege)} Pokemon in der Box. Die Endwerte folgen den "
               "Champions-Regeln: ein Statuspunkt = +1 auf den Endwert bei Stufe 50. "
               "Der Einsatzcheck je Eintrag sagt, wo das Pokemon gerade gespielt wird.")

    urteile = einsatz.pruefen(conn, [e["slug"] for e in eintraege])

    for eintrag in eintraege:
        name = eintrag.get("anzeigename") or eintrag["slug"]
        titel = f"{eintrag['spitzname']} ({name})" if eintrag.get("spitzname") else name
        if eintrag.get("ist_shiny"):
            titel += " · Shiny"
        check = urteile.get(eintrag["slug"])
        if check:
            titel += f" · {einsatz.URTEIL_TEXT[check.bestes_urteil]}"
        with st.expander(titel):
            spalten = st.columns([1, 2, 2, 1])
            with spalten[0]:
                if eintrag.get("pokedex_id"):
                    st.image(sprite_url(int(eintrag["pokedex_id"])), width=96)
                st.markdown(typ_abzeichen_paar(eintrag.get("typ1"), eintrag.get("typ2")),
                            unsafe_allow_html=True)
            with spalten[1]:
                st.markdown(
                    f"**Item:** {eintrag.get('item_name') or eintrag.get('item_slug') or '-'}  \n"
                    f"**Faehigkeit:** {eintrag.get('faehigkeit_name') or eintrag.get('faehigkeit_slug') or '-'}  \n"
                    f"**Wesen:** {eintrag['wesen']}  \n"
                    f"**Attacken:** {', '.join(eintrag['attacken']) or '-'}  \n"
                    f"**Herkunft:** {eintrag.get('herkunft') or '-'}"
                    + ("  \n**Schillernd** -- ein Shiny" if eintrag.get("ist_shiny") else ""))
                if eintrag.get("notiz"):
                    st.caption(eintrag["notiz"])
                if check:
                    st.markdown("**Einsatzcheck**")
                    for befund in check.befunde:
                        st.markdown(kennzahl_kachel(
                            befund.spielform, einsatz.URTEIL_TEXT[befund.urteil],
                            befund.text, bedeutung=befund.bedeutung),
                            unsafe_allow_html=True)
            with spalten[2]:
                if eintrag.get("hp") is not None:
                    basis = {name: eintrag[name] for name in STATUSWERTE}
                    punkte = {name: eintrag[f"punkte_{name}"] for name in STATUSWERTE}
                    werte = alle_statuswerte(basis, punkte, eintrag["wesen"])
                    st.dataframe(pd.DataFrame({
                        "Wert": [PUNKTE_BESCHRIFTUNG[n] for n in STATUSWERTE],
                        "Punkte": [punkte[n] for n in STATUSWERTE],
                        "Endwert": [werte[n] for n in STATUSWERTE],
                    }), hide_index=True, height=248)
                else:
                    st.caption("Keine Stammdaten zu diesem Pokemon geladen -- "
                               "Endwerte nicht berechenbar.")
            with spalten[3]:
                if st.button("Loeschen", key=f"box_del_{eintrag['box_id']}"):
                    nutzerdaten.box_loeschen(conn, nutzer.nutzer_id, eintrag["box_id"])
                    st.rerun()


# --------------------------------------------------------------------------
# Einsatzcheck
# --------------------------------------------------------------------------

def _einsatzcheck(conn, nutzer) -> None:
    """Die ganze Box gegen alle drei Spielformen -- die Frage 'was kann ich
    damit gerade anfangen?' auf einen Blick."""
    eintraege = nutzerdaten.box_lesen(conn, nutzer.nutzer_id)
    if not eintraege:
        st.info("Die Box ist leer. Der Einsatzcheck braucht mindestens ein Pokemon.")
        return

    urteile = einsatz.pruefen(conn, [e["slug"] for e in eintraege])
    spielformen = list(dict.fromkeys(
        b.spielform for u in urteile.values() for b in u.befunde))

    kacheln = st.columns(len(spielformen) + 1)
    with kacheln[0]:
        meta = sum(1 for u in urteile.values() if u.bestes_urteil == "meta")
        st.markdown(kennzahl_kachel(
            "Meta-relevant", f"{meta} von {len(urteile)}",
            "eigene Pokemon, die in mindestens einer Spielform oben mitspielen",
            bedeutung="guenstig" if meta else "neutral"), unsafe_allow_html=True)
    for spalte, spielform in zip(kacheln[1:], spielformen, strict=True):
        with spalte:
            einsetzbar = sum(
                1 for u in urteile.values()
                if (b := u.befund(spielform)) and b.urteil in ("meta", "spielbar"))
            unbekannt = all(
                (b := u.befund(spielform)) and b.urteil == "unbekannt" for u in urteile.values())
            st.markdown(kennzahl_kachel(
                spielform, "-" if unbekannt else str(einsetzbar),
                "Spielform nicht geladen" if unbekannt else "davon derzeit einsetzbar",
                bedeutung="guenstig" if einsetzbar else "neutral"), unsafe_allow_html=True)

    zeilen = []
    for eintrag in eintraege:
        check = urteile[eintrag["slug"]]
        zeile = {
            "Pokemon": eintrag.get("anzeigename") or eintrag["slug"],
            "Spitzname": eintrag.get("spitzname") or "",
            "Gesamt": einsatz.URTEIL_TEXT[check.bestes_urteil],
        }
        for befund in check.befunde:
            zeile[befund.spielform] = f"{einsatz.URTEIL_TEXT[befund.urteil]} -- {befund.text}"
        zeilen.append(zeile)
    tabelle(pd.DataFrame(zeilen))
    st.caption(
        f"Champions: Meta-relevant bis Rang {einsatz.META_RANGGRENZE}, darueber "
        f"spielbar, ohne Eintrag kein Einsatz. Pokemon GO: Meta-relevant ab Score "
        f"{einsatz.GO_EINSATZ_SCORE:.0f} in der besten Liga. Sammelkartenspiel: "
        "Meta-relevant, wenn das Pokemon ein Turnierdeck anfuehrt. Der Champions-"
        "Befund folgt der in der Seitenleiste gewaehlten Saison."
    )


# --------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------

def _teams(conn, nutzer) -> None:
    eintraege = nutzerdaten.box_lesen(conn, nutzer.nutzer_id)
    if not eintraege:
        st.info("Fuer Teams braucht es zuerst Pokemon in der Box.")
        return

    beschriftung = {
        e["box_id"]: (f"{e['spitzname']} ({e.get('anzeigename') or e['slug']})"
                      if e.get("spitzname") else (e.get("anzeigename") or e["slug"]))
        for e in eintraege
    }

    with st.form("team_anlegen"):
        st.markdown("**Neues Team**")
        spalten = st.columns([2, 1])
        with spalten[0]:
            name = st.text_input("Name des Teams")
        with spalten[1]:
            kampfformat = st.selectbox("Kampfformat", list(KAMPFFORMATE))
        mitglieder = st.multiselect(
            "Mitglieder (bis zu sechs)", list(beschriftung),
            format_func=lambda box_id: beschriftung[box_id], max_selections=6)
        if st.form_submit_button("Team speichern", type="primary"):
            try:
                nutzerdaten.team_speichern(conn, nutzer.nutzer_id, name, mitglieder,
                                           kampfformat)
                st.rerun()
            except ValueError as fehler:
                st.error(str(fehler))

    teams = nutzerdaten.teams_lesen(conn, nutzer.nutzer_id)
    if not teams:
        return
    st.markdown("---")
    for team in teams:
        mitnahme = MITNAHME.get(team["kampfformat"], 4)
        with st.expander(f"{team['name']} · {team['kampfformat']} · "
                         f"{len(team['mitglieder'])} Pokemon"):
            st.caption(f"Im Team-Preview gehen {mitnahme} von sechs mit -- die Auswahl "
                       "rechnet der Team-Preview-Advisor gegen ein konkretes Gegnerteam.")
            if team["mitglieder"]:
                spalten = st.columns(max(len(team["mitglieder"]), 1))
                for spalte, mitglied in zip(spalten, team["mitglieder"], strict=False):
                    with spalte:
                        if mitglied.get("pokedex_id"):
                            st.image(sprite_url(int(mitglied["pokedex_id"])), width=72)
                        st.caption(mitglied.get("anzeigename") or mitglied["slug"])
            if st.button("Team loeschen", key=f"team_del_{team['team_id']}"):
                nutzerdaten.team_loeschen(conn, nutzer.nutzer_id, team["team_id"])
                st.rerun()

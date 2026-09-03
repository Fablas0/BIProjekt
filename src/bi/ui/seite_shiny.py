"""Seite: Shiny-Jagd.

Ein Zaehler je Jagd -- und die Einordnung des Zaehlerstands gegen die
Wahrscheinlichkeit der Methode. Die Regelbasis und die Statistik liegen in
:mod:`bi.shiny`; die Seite zeigt sie.

Drei Dinge sind bewusst so:

* Der Zaehler hat grosse Knoepfe (+1, +5, +10) und ein Feld zum Setzen. Wer
  im Spiel zaehlt, traegt nach -- nicht jeder Versuch wird einzeln geklickt.
* Die Einordnung ist ein **Anteil**, kein Urteil: "rund 63 Prozent aller
  Jaeger waren bis hier fertig". Ein Pech-Stempel ab einer festen Zahl waere
  willkuerlich; der Anteil sagt, was die Zahl bedeutet.
* Ein gefundenes Shiny laesst sich unmittelbar in der Box ablegen, mit
  Shiny-Kennzeichen und Herkunft. Das Ereignis, fuer das gezaehlt wurde,
  soll nicht in einer zweiten Maske nachgetragen werden muessen.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import nutzerdaten, shiny
from ..config import sprite_url
from . import anmeldung, design
from .komponenten import (
    hole_verbindung,
    kennzahl_kachel,
    name_mit_deutsch,
    seitenkopf,
    tabelle,
)

# Aussage der Einordnung fuer die Kachel -- die Stufen der Regelbasis auf
# die vier Bedeutungen des Designsystems abgebildet. "Pech" ist kein Mangel,
# den jemand beheben koennte, und bleibt deshalb neutral; das Glueck ist die
# gute Nachricht.
_STUFE_BEDEUTUNG = {
    "glueck": "guenstig", "frueh": "neutral", "ueblich": "neutral",
    "geduldig": "neutral", "pech": "neutral",
}


def zeichne() -> None:
    conn = hole_verbindung()
    nutzerdaten.anhaengen(conn)
    nutzer = anmeldung.verlangen(conn)
    if nutzer is None:
        return

    seitenkopf("Shiny-Jagd",
               "Versuche zaehlen -- und wissen, was die Zahl gegen die "
               "Wahrscheinlichkeit der Methode bedeutet")

    jagden = shiny.jagden_lesen(conn, nutzer.nutzer_id)
    _bilanz(jagden)

    laufend, neu, rechner, archiv = st.tabs(
        ["Laufende Jagden", "Neue Jagd", "Rechner", "Abgeschlossen"])
    with laufend:
        _laufende(conn, nutzer, [j for j in jagden if j["status"] == "laeuft"])
    with neu:
        _neue_jagd(conn, nutzer)
    with rechner:
        _rechner()
    with archiv:
        _abgeschlossene(conn, nutzer, [j for j in jagden if j["status"] != "laeuft"])


def _bilanz(jagden: list[dict]) -> None:
    zahlen = shiny.bilanz(jagden)
    kacheln = st.columns(4)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Laufende Jagden", str(zahlen["laufend"]),
                                    f"{zahlen['jagden']} insgesamt"),
                    unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("Gefunden", str(zahlen["gefunden"]),
                                    "schillernde Pokemon"),
                    unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("Versuche gesamt", f"{zahlen['versuche_gesamt']:,}",
                                    "ueber alle Jagden"),
                    unsafe_allow_html=True)
    with kacheln[3]:
        wert = zahlen["glueckswert"]
        if wert is None:
            st.markdown(kennzahl_kachel("Glueckswert", "-",
                                        "entsteht mit der ersten gefundenen Jagd"),
                        unsafe_allow_html=True)
        else:
            st.markdown(kennzahl_kachel(
                "Glueckswert", f"{wert:.2f}",
                "0,5 = Durchschnitt; kleiner = schneller fuendig als die meisten",
                bedeutung="guenstig" if wert < 0.4 else "neutral"),
                unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Laufende Jagden
# --------------------------------------------------------------------------

def _laufende(conn, nutzer, jagden: list[dict]) -> None:
    if not jagden:
        st.info("Keine laufende Jagd. Unter *Neue Jagd* beginnt die erste.")
        return

    for jagd in jagden:
        _jagdkarte(conn, nutzer, jagd)


def _jagdkarte(conn, nutzer, jagd: dict) -> None:
    name = jagd.get("anzeigename") or jagd["slug"]
    methode = shiny.METHODEN.get(jagd["methode"])
    einordnung = jagd.get("einordnung")

    with st.container(border=True):
        kopf = st.columns([1, 3, 2])
        with kopf[0]:
            if jagd.get("pokedex_id"):
                st.image(sprite_url(int(jagd["pokedex_id"])), width=110)
        with kopf[1]:
            st.markdown(f"### {name_mit_deutsch(name)}")
            st.caption(f"{jagd['spiel']} · {jagd['methode_name']}"
                       + (f" · 1 zu {methode.nenner:,.0f} je {methode.einheit[:-1]}"
                          if methode else ""))
            st.markdown(f"<div class='kachel-wert'>{int(jagd['versuche']):,} "
                        f"<span class='kachel-hinweis'>{jagd['einheit']}</span></div>",
                        unsafe_allow_html=True)
            if einordnung:
                st.markdown(kennzahl_kachel(
                    "Einordnung", f"{einordnung.anteil_bereits_fuendig:.0%}",
                    "aller Jaeger waren bis hier fuendig · "
                    f"Median {einordnung.median:,} · Erwartungswert "
                    f"{einordnung.erwartungswert:,.0f}",
                    bedeutung=_STUFE_BEDEUTUNG[einordnung.stufe]),
                    unsafe_allow_html=True)
                st.caption(einordnung.text)
        with kopf[2]:
            st.markdown("**Zaehlen**")
            knoepfe = st.columns(3)
            for spalte, schritt in zip(knoepfe, (1, 5, 10), strict=True):
                with spalte:
                    if st.button(f"+{schritt}", key=f"jagd_plus_{schritt}_{jagd['jagd_id']}",
                                 width="stretch"):
                        shiny.jagd_zaehlen(conn, nutzer.nutzer_id, jagd["jagd_id"], schritt)
                        st.rerun()
            with st.form(f"jagd_setzen_{jagd['jagd_id']}", border=False):
                stand = st.number_input("Stand setzen", min_value=0, step=1,
                                        value=int(jagd["versuche"]),
                                        key=f"jagd_stand_{jagd['jagd_id']}")
                if st.form_submit_button("Uebernehmen", width="stretch"):
                    shiny.jagd_setzen(conn, nutzer.nutzer_id, jagd["jagd_id"], int(stand))
                    st.rerun()

        if methode:
            _verteilungsdiagramm(methode, int(jagd["versuche"]))

        abschluss = st.columns([2, 1, 1])
        with abschluss[0]:
            in_box = st.checkbox("Beim Fund in der Box ablegen (als Shiny, mit Herkunft)",
                                 value=True, key=f"jagd_box_{jagd['jagd_id']}")
        with abschluss[1]:
            if st.button("Gefunden!", key=f"jagd_gefunden_{jagd['jagd_id']}",
                         type="primary", width="stretch"):
                shiny.jagd_abschliessen(conn, nutzer.nutzer_id, jagd["jagd_id"], True)
                if in_box:
                    nutzerdaten.box_speichern(conn, nutzer.nutzer_id, {
                        "slug": jagd["slug"], "ist_shiny": 1, "herkunft": jagd["spiel"],
                        "notiz": f"Shiny nach {int(jagd['versuche'])} {jagd['einheit']} "
                                 f"({jagd['methode_name']})",
                    })
                st.rerun()
        with abschluss[2]:
            if st.button("Abbrechen", key=f"jagd_abbruch_{jagd['jagd_id']}", width="stretch"):
                shiny.jagd_abschliessen(conn, nutzer.nutzer_id, jagd["jagd_id"], False)
                st.rerun()


def _verteilungsdiagramm(methode: shiny.Methode, versuche: int) -> None:
    """Die kumulierte Verteilung mit dem eigenen Stand als Markierung."""
    p = methode.wahrscheinlichkeit
    ende = max(shiny.versuche_fuer(p, 0.99), versuche + 1)
    punkte = shiny.verteilung(p, bis=ende)
    x = [n for n, _ in punkte]
    y = [100 * a for _, a in punkte]

    # Die Verteilung ist Hintergrund, vor dem der eigene Stand eingeordnet
    # wird -- deshalb grau; der eigene Stand traegt die Akzentfarbe.
    figur = go.Figure()
    figur.add_scatter(x=x, y=y, mode="lines", name="Anteil fuendiger Jaeger",
                      line={"color": design.GRAU_MITTE, "width": 2},
                      fill="tozeroy", fillcolor=design.GRAU_FLAECHE_TRANSPARENT,
                      hovertemplate="%{x:,} Versuche: %{y:.1f} % fuendig<extra></extra>")
    figur.add_vline(x=shiny.erwartungswert(p), line_dash="dot", line_color=design.GRAU_MITTE,
                    annotation_text="Erwartungswert", annotation_position="top left")
    if versuche > 0:
        figur.add_vline(x=versuche, line_color=design.BLAU_HELL, line_width=3,
                        annotation_text="Dein Stand", annotation_position="top right")
    figur.update_layout(height=220, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                        showlegend=False, yaxis_title="fuendig (%)",
                        xaxis_title=methode.einheit)
    st.plotly_chart(figur, width="stretch")


# --------------------------------------------------------------------------
# Neue Jagd
# --------------------------------------------------------------------------

def _neue_jagd(conn, nutzer) -> None:
    pokemon = pd.read_sql(
        "SELECT slug, anzeigename FROM Dim_Pokemon WHERE ist_aktuell = 1 ORDER BY anzeigename",
        conn)
    if pokemon.empty:
        st.info("Die Pokemon-Stammdaten sind noch nicht geladen -- bitte zuerst unter "
                "*ETL & Datenqualitaet* laden.")
        return
    namen = dict(zip(pokemon["anzeigename"], pokemon["slug"], strict=True))

    gewaehlt = st.selectbox("Pokemon", list(namen), index=None, key="jagd_pokemon",
                            format_func=name_mit_deutsch, placeholder="Pokemon waehlen ...")
    spiel = st.selectbox("Spielfamilie", list(shiny.SPIELE), key="jagd_spiel")
    methoden = shiny.methoden_je_spiel(spiel)
    methode = st.selectbox(
        "Methode", methoden, key="jagd_methode",
        format_func=lambda m: f"{m.bezeichnung} -- 1 zu {m.nenner:,.0f}")
    if methode and methode.erlaeuterung:
        st.caption(methode.erlaeuterung)

    with st.form("jagd_anlegen"):
        stand = st.number_input("Bisheriger Stand (falls schon gezaehlt)", min_value=0, step=1,
                                value=0)
        notiz = st.text_input("Notiz (optional)")
        if st.form_submit_button("Jagd beginnen", type="primary"):
            if not gewaehlt:
                st.error("Bitte ein Pokemon waehlen.")
                return
            shiny.jagd_anlegen(conn, nutzer.nutzer_id, namen[gewaehlt], methode.schluessel,
                               spiel, int(stand), notiz or None)
            st.success(f"Die Jagd auf {gewaehlt} laeuft.")
            st.rerun()


# --------------------------------------------------------------------------
# Rechner
# --------------------------------------------------------------------------

def _rechner() -> None:
    """Wahrscheinlichkeiten je Methode, ohne eine Jagd anzulegen."""
    st.markdown("Wie viele Versuche braucht es -- und was heisst ein Zaehlerstand?")
    spalten = st.columns([1, 1])
    with spalten[0]:
        spiel = st.selectbox("Spielfamilie", list(shiny.SPIELE), key="rechner_spiel")
        methode = st.selectbox("Methode", shiny.methoden_je_spiel(spiel), key="rechner_methode",
                               format_func=lambda m: m.bezeichnung)
    with spalten[1]:
        stand = st.number_input("Zaehlerstand", min_value=0, step=1, value=0,
                                key="rechner_stand")

    p = methode.wahrscheinlichkeit
    kacheln = st.columns(4)
    with kacheln[0]:
        st.markdown(kennzahl_kachel("Chance je Versuch", f"1 zu {methode.nenner:,.0f}",
                                    f"{100 * p:.4f} %"), unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel("Erwartungswert", f"{shiny.erwartungswert(p):,.0f}",
                                    methode.einheit), unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel("Median", f"{shiny.median_versuche(p):,}",
                                    "die Haelfte der Jaeger ist bis hier fertig"),
                    unsafe_allow_html=True)
    with kacheln[3]:
        st.markdown(kennzahl_kachel("Fuer 99 % Sicherheit", f"{shiny.versuche_fuer(p, 0.99):,}",
                                    "rund das 4,6-fache des Erwartungswerts"),
                    unsafe_allow_html=True)

    if stand:
        einordnung = shiny.einordnen(methode, int(stand))
        st.markdown(kennzahl_kachel(
            "Dein Stand", f"{einordnung.anteil_bereits_fuendig:.1%}",
            "aller Jaeger waren bis hier fuendig",
            bedeutung=_STUFE_BEDEUTUNG[einordnung.stufe]), unsafe_allow_html=True)
        st.caption(einordnung.text)
    _verteilungsdiagramm(methode, int(stand))

    st.markdown("**Alle Methoden im Vergleich**")
    uebersicht = pd.DataFrame([{
        "Spiel": m.spiel, "Methode": m.bezeichnung, "Chance": f"1 zu {m.nenner:,.0f}",
        "Erwartungswert": round(shiny.erwartungswert(m.wahrscheinlichkeit)),
        "Median": shiny.median_versuche(m.wahrscheinlichkeit),
        "Einheit": m.einheit,
    } for m in shiny.METHODEN.values()])
    tabelle(uebersicht)
    st.caption(
        "Die Chancen folgen aus den durch Datamining belegten Wurfzahlen: "
        "``1 - (1 - 1/N)^Wuerfe``. Die Angabe 'Masuda 1 zu 683' ist genau dieses "
        "Ergebnis fuer sechs Wuerfe mit 1/4096. Pokemon GO wuerfelt nicht; dort "
        "stehen die aus Community-Zaehlungen bekannten Raten."
    )


# --------------------------------------------------------------------------
# Abgeschlossene Jagden
# --------------------------------------------------------------------------

def _abgeschlossene(conn, nutzer, jagden: list[dict]) -> None:
    if not jagden:
        st.caption("Noch keine abgeschlossene Jagd.")
        return

    zeilen = []
    for jagd in jagden:
        einordnung = jagd.get("einordnung")
        zeilen.append({
            "Pokemon": jagd.get("anzeigename") or jagd["slug"],
            "Spiel": jagd["spiel"], "Methode": jagd["methode_name"],
            "Versuche": int(jagd["versuche"]), "Einheit": jagd["einheit"],
            "Ergebnis": "Gefunden" if jagd["status"] == "gefunden" else "Abgebrochen",
            "Anteil fuendiger Jaeger (%)": (
                round(100 * einordnung.anteil_bereits_fuendig, 1) if einordnung else None),
            "Begonnen": (jagd.get("begonnen_am") or "")[:10],
            "Beendet": (jagd.get("beendet_am") or "")[:10],
        })
    tabelle(pd.DataFrame(zeilen))
    st.caption(
        "Der Anteil sagt, wie viele Jaeger mit derselben Methode bis zu diesem "
        "Stand fuendig geworden waeren -- ein kleiner Wert bei 'Gefunden' ist Glueck."
    )

    with st.expander("Eintrag entfernen"):
        auswahl = st.selectbox(
            "Jagd", jagden, format_func=lambda j: (
                f"{j.get('anzeigename') or j['slug']} · {j['versuche']} {j['einheit']} · "
                f"{j['status']}"), key="jagd_entfernen")
        if auswahl and st.button("Entfernen", key="jagd_entfernen_knopf"):
            shiny.jagd_loeschen(conn, nutzer.nutzer_id, auswahl["jagd_id"])
            st.rerun()

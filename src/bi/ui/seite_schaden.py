"""Seite: Schadensrechner.

Beantwortet die Frage, an der eine Einwechselentscheidung haengt: **ueberlebt
mein Pokemon diesen Treffer -- und faellt der Gegner meinen?** Der
Team-Preview-Advisor liefert die Rangfolge; der Rechner liefert die Zahl
dahinter.

Beide Seiten des Vergleichs koennen aus zwei Bestaenden kommen:

* aus der **eigenen Box** (PC-System) -- dann rechnen die selbst vergebenen
  Statuspunkte, das getragene Item und die Faehigkeit mit;
* aus der **Meta** -- dann wird das meistgespielte Set des Berichtstags
  verwendet, also dieselbe Erwartung, mit der auch Scouting und Preview
  arbeiten.

Damit prueft man das eigene Set nicht gegen ein abstraktes Pokemon, sondern
gegen genau die Konfiguration, die einem im Turnier gegenuebersteht.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import nutzerdaten
from ..analytics import kpi
from ..analytics.schaden import Angriff, Kaempfer, berechne, treffer_bis_ko
from ..config import STANDARD_KAMPFFORMAT, TYP_DEUTSCH
from ..stats import STATUSWERTE, alle_statuswerte
from . import anmeldung
from .komponenten import (
    hinweis_leere_datenbank,
    hole_verbindung,
    kennzahl_kachel,
    seitenkopf,
)


def zeichne() -> None:
    conn = hole_verbindung()
    nutzerdaten.anhaengen(conn)

    nutzer = anmeldung.verlangen(conn)
    if nutzer is None:
        return

    seitenkopf("Schadensrechner",
               "Ueberlebt mein Pokemon diesen Treffer -- und faellt der Gegner meinen?")

    if not kpi.verfuegbare_formate(conn):
        hinweis_leere_datenbank()
        return

    tag = kpi.aktueller_tag(conn, STANDARD_KAMPFFORMAT)

    spalten = st.columns(2)
    with spalten[0]:
        st.markdown("#### Angreifer")
        angreifer = _kaempfer_waehlen(conn, nutzer, "angreifer", tag)
    with spalten[1]:
        st.markdown("#### Verteidiger")
        verteidiger = _kaempfer_waehlen(conn, nutzer, "verteidiger", tag)

    if not (angreifer and verteidiger):
        st.info("Beide Seiten waehlen -- aus der eigenen Box oder aus der Meta.")
        return

    kaempfer_a, attacken = angreifer
    kaempfer_v, _ = verteidiger

    st.markdown("---")
    angriff = _angriff_waehlen(conn, attacken)
    if angriff is None:
        return

    spanne = berechne(kaempfer_a, kaempfer_v, angriff)
    guenstig, unguenstig = treffer_bis_ko(spanne)

    kacheln = st.columns(4)
    # Ein moeglicher K.o. ist eine Gefahr fuer den Verteidiger -- die Kachel
    # traegt die Aussage, das Designsystem entscheidet ueber die Farbe.
    bedeutung = "gefahr" if spanne.moeglicher_ko else "neutral"
    with kacheln[0]:
        st.markdown(kennzahl_kachel(
            "Schaden", f"{spanne.minimum}-{spanne.maximum}",
            f"von {spanne.ziel_hp} KP"), unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel(
            "Anteil", f"{spanne.minimum_prozent}-{spanne.maximum_prozent} %",
            "Zufallsspanne 85-100 %"), unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel(
            "Effektivitaet", f"x{spanne.effektivitaet:g}",
            "Typen und Faehigkeit"), unsafe_allow_html=True)
    with kacheln[3]:
        st.markdown(kennzahl_kachel(
            "Treffer bis K.o.",
            "-" if not guenstig else (str(guenstig) if guenstig == unguenstig
                                      else f"{guenstig}-{unguenstig}"),
            "guenstig-unguenstig", bedeutung=bedeutung), unsafe_allow_html=True)

    st.markdown(f"**{spanne.urteil}**")
    if spanne.erklaerung:
        st.caption("Verrechnet: " + " · ".join(spanne.erklaerung))

    st.caption(
        "Umgesetzt ist die Schadensformel der Hauptspiele (ab Generation V) mit "
        "der Rundungsreihenfolge des Spiels. Attacken mit variabler Staerke und "
        "Feldeffekte jenseits von Wetter und Schirmen bildet der Rechner nicht ab."
    )


# --------------------------------------------------------------------------
# Auswahl der Kaempfer
# --------------------------------------------------------------------------

def _kaempfer_waehlen(conn, nutzer, schluessel: str,
                      tag: str | None) -> tuple[Kaempfer, list[str]] | None:
    """Auswahl einer Seite: eigene Box oder Meta-Set."""
    quellen = ["Meta (meistgespieltes Set)", "Eigene Box"]
    quelle = st.radio("Quelle", quellen, key=f"{schluessel}_quelle", horizontal=True)

    if quelle == "Eigene Box":
        eintraege = nutzerdaten.box_lesen(conn, nutzer.nutzer_id)
        eintraege = [e for e in eintraege if e.get("hp") is not None]
        if not eintraege:
            st.caption("Die Box ist leer oder ohne geladene Stammdaten -- "
                       "im PC-System Pokemon ablegen.")
            return None
        beschriftung = {
            e["box_id"]: (f"{e['spitzname']} ({e['anzeigename']})" if e.get("spitzname")
                          else e["anzeigename"])
            for e in eintraege
        }
        wahl = st.selectbox("Pokemon", list(beschriftung),
                            format_func=lambda i: beschriftung[i],
                            key=f"{schluessel}_box", index=None,
                            placeholder="Aus der Box waehlen ...")
        if wahl is None:
            return None
        eintrag = next(e for e in eintraege if e["box_id"] == wahl)
        basis = {name: eintrag[name] for name in STATUSWERTE}
        punkte = {name: eintrag[f"punkte_{name}"] for name in STATUSWERTE}
        werte = alle_statuswerte(basis, punkte, eintrag["wesen"])
        _steckbrief(eintrag.get("typ1"), eintrag.get("typ2"), werte,
                    eintrag.get("item_name"), eintrag.get("faehigkeit_name"))
        return Kaempfer(
            name=eintrag.get("anzeigename") or eintrag["slug"],
            typ1=eintrag.get("typ1") or "Normal", typ2=eintrag.get("typ2"),
            hp=werte["hp"], attack=werte["attack"], defense=werte["defense"],
            sp_attack=werte["sp_attack"], sp_defense=werte["sp_defense"],
            item_slug=eintrag.get("item_slug"),
            faehigkeit_slug=eintrag.get("faehigkeit_slug"),
        ), eintrag["attacken"]

    if not tag:
        st.caption("Keine Bewegungsdaten geladen.")
        return None
    uebersicht = kpi.meta_uebersicht(conn, tag, STANDARD_KAMPFFORMAT)
    if uebersicht.empty:
        st.caption("Keine Bewegungsdaten geladen.")
        return None
    wahl = st.selectbox("Pokemon", uebersicht["anzeigename"].tolist(),
                        key=f"{schluessel}_meta", index=None,
                        placeholder="Aus der Meta waehlen ...")
    if wahl is None:
        return None
    zeile = uebersicht.loc[uebersicht["anzeigename"] == wahl].iloc[0]

    werte = {name: int(zeile[f"wert_{name}"]) if pd.notna(zeile.get(f"wert_{name}"))
             else int(zeile[f"stufe50_{name}"]) for name in STATUSWERTE}
    item_slug = _meta_item(conn, wahl, tag)
    _steckbrief(zeile["typ1"], zeile.get("typ2"), werte,
                item_slug, None, rang=int(zeile["rang"]))
    attacken = _meta_attacken(conn, wahl, tag)
    return Kaempfer(
        name=wahl, typ1=zeile["typ1"], typ2=zeile.get("typ2"),
        hp=werte["hp"], attack=werte["attack"], defense=werte["defense"],
        sp_attack=werte["sp_attack"], sp_defense=werte["sp_defense"],
        item_slug=item_slug,
    ), attacken


def _steckbrief(typ1, typ2, werte: dict[str, int], item, faehigkeit,
                rang: int | None = None) -> None:
    typen = TYP_DEUTSCH.get(typ1, typ1 or "-")
    if typ2 and pd.notna(typ2):
        typen += f" / {TYP_DEUTSCH.get(typ2, typ2)}"
    teile = [typen,
             f"KP {werte['hp']} · Ang {werte['attack']} · Vert {werte['defense']} · "
             f"SpA {werte['sp_attack']} · SpV {werte['sp_defense']}"]
    if item:
        teile.append(f"Item: {item}")
    if faehigkeit:
        teile.append(f"Faehigkeit: {faehigkeit}")
    if rang:
        teile.append(f"Meta-Rang {rang}")
    st.caption(" · ".join(str(t) for t in teile))


def _meta_item(conn, anzeigename: str, tag: str) -> str | None:
    """Das meistgetragene Item des Pokemon am Berichtstag."""
    zeile = conn.execute("""
        SELECT i.slug
        FROM Fact_Champions_Merkmal f
        JOIN Dim_Pokemon p ON p.pokemon_sk = f.pokemon_sk
        JOIN Dim_Zeit    z ON z.zeit_sk    = f.zeit_sk
        JOIN Dim_Item    i ON i.item_sk    = f.item_sk
        WHERE p.anzeigename = ? AND z.datum_iso = ?
          AND f.kategorie = 'held_item' AND f.rang = 1
        LIMIT 1
    """, (anzeigename, tag)).fetchone()
    return zeile[0] if zeile else None


def _meta_attacken(conn, anzeigename: str, tag: str) -> list[str]:
    """Die meistgespielten Attacken -- als kompakte Schluessel fuer die Auswahl."""
    return [z[0] for z in conn.execute("""
        SELECT a.slug
        FROM Fact_Champions_Merkmal f
        JOIN Dim_Pokemon p ON p.pokemon_sk = f.pokemon_sk
        JOIN Dim_Zeit    z ON z.zeit_sk    = f.zeit_sk
        JOIN Dim_Attacke a ON a.attacke_sk = f.attacke_sk
        WHERE p.anzeigename = ? AND z.datum_iso = ? AND f.kategorie = 'move'
        ORDER BY f.rang LIMIT 4
    """, (anzeigename, tag))]


# --------------------------------------------------------------------------
# Angriff
# --------------------------------------------------------------------------

def _angriff_waehlen(conn, vorschlaege: list[str]) -> Angriff | None:
    attacken = pd.read_sql(
        "SELECT slug, anzeigename, typ, kategorie, basisschaden, zielbereich "
        "FROM Dim_Attacke WHERE kategorie IN ('physical', 'special') "
        "AND basisschaden > 0 ORDER BY anzeigename", conn)
    if attacken.empty:
        st.warning("Keine Attacken-Stammdaten geladen.")
        return None

    namen = attacken["anzeigename"].tolist()
    # Die Attacken des gewaehlten Sets nach vorn -- meist ist genau eine davon gemeint.
    bekannte = attacken.loc[attacken["slug"].isin(vorschlaege), "anzeigename"].tolist()
    geordnet = bekannte + [n for n in namen if n not in bekannte]

    spalten = st.columns([2, 1, 1, 1])
    with spalten[0]:
        wahl = st.selectbox("Attacke", geordnet, index=0 if bekannte else None,
                            placeholder="Attacke waehlen ...")
    if not wahl:
        return None
    zeile = attacken.loc[attacken["anzeigename"] == wahl].iloc[0]

    with spalten[1]:
        wetter = st.selectbox("Wetter", ["-", "Regen", "Sonne"])
    with spalten[2]:
        mehrfachziel = st.checkbox(
            "Mehrere Ziele",
            value=zeile["zielbereich"] in ("all-opponents", "all-other-pokemon"),
            help="Flaechenattacken verlieren im Doppelkampf ein Viertel Schaden, "
                 "wenn sie mehrere Ziele treffen.")
        kritisch = st.checkbox("Kritischer Treffer")
    with spalten[3]:
        brand = st.checkbox("Angreifer verbrannt")
        schirm = st.checkbox("Schirm aktiv",
                             help="Reflektor bzw. Lichtschild auf der Zielseite.")

    st.caption(f"{TYP_DEUTSCH.get(zeile['typ'], zeile['typ'])} · "
               f"{'physisch' if zeile['kategorie'] == 'physical' else 'speziell'} · "
               f"Staerke {int(zeile['basisschaden'])}")

    return Angriff(
        name=wahl, typ=zeile["typ"], kategorie=zeile["kategorie"],
        staerke=int(zeile["basisschaden"]),
        mehrfachziel=mehrfachziel, wetter=None if wetter == "-" else wetter,
        kritisch=kritisch, brand=brand, schirm=schirm,
    )

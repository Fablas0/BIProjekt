"""Seite: Team-Builder.

Unterstuetzt den Aufbau eines eigenen Teams: datengestuetzte Partnervorschlaege,
laufende Bewertung der defensiven Abdeckung und der offensiven Reichweite.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..analytics import kpi, speed, threat
from ..config import TYP_DEUTSCH
from . import design
from .komponenten import (
    hinweis_leere_datenbank,
    hole_verbindung,
    kennzahl_kachel,
    kopfauswahl,
    name_mit_deutsch,
    seitenkopf,
    tabelle,
)

# Ab wie vielen der 18 Verteidigungstypen die offensive Reichweite als
# ausreichend gilt.
REICHWEITE_AUSREICHEND_AB = 12


def zeichne() -> None:
    conn = hole_verbindung()

    seitenkopf("Team-Builder", "Wo ist mein Team angreifbar?")
    if not kpi.verfuegbare_formate(conn):
        hinweis_leere_datenbank()
        return

    kampfformat, monat = kopfauswahl(conn, "builder")
    if not monat:
        st.warning("Fuer dieses Format liegen keine Daten vor.")
        return

    verfuegbar = kpi.meta_uebersicht(conn, monat, kampfformat)
    if True:
        auswahl = st.multiselect(
            "Eigenes Team (bis zu sechs Pokemon)",
            options=verfuegbar["anzeigename"].tolist(), max_selections=6,
            format_func=name_mit_deutsch,
        )

    if not auswahl:
        st.info(
            "Waehle ein erstes Pokemon aus. Der Builder schlaegt daraufhin Partner vor, "
            "die im Metagame statistisch am haeufigsten gemeinsam mit der Auswahl "
            "gespielt werden, und bewertet laufend die Abdeckung des Teams."
        )
        return

    team = verfuegbar[verfuegbar["anzeigename"].isin(auswahl)].reset_index(drop=True)

    _zeige_bewertung(conn, team, auswahl, monat, kampfformat)
    st.markdown("---")

    reiter = st.tabs([
        "Partnervorschlaege", "Defensive Abdeckung", "Offensive Reichweite",
        "Initiative im Vergleich",
    ])

    with reiter[0]:
        _zeige_partner(conn, team, auswahl, monat, kampfformat)
    with reiter[1]:
        _zeige_defensive(conn, team, monat, kampfformat)
    with reiter[2]:
        _zeige_offensive(conn, auswahl, monat, kampfformat)
    with reiter[3]:
        _zeige_initiative(conn, team, monat, kampfformat)


# --------------------------------------------------------------------------

def _zeige_bewertung(conn, team: pd.DataFrame, namen: list[str], monat: str,
                     kampfformat: str) -> None:
    """Kennzahlenzeile mit der laufenden Bewertung des Teams."""
    haeufigkeit = threat.angriffstyp_haeufigkeit(conn, monat, kampfformat)
    profil = threat.team_defensivprofil(team, haeufigkeit)
    abdeckung = threat.offensive_abdeckung(conn, namen, monat, kampfformat)

    ungedeckt = int((profil["bewertung"].str.startswith("Kritisch")).sum())
    gesamtrisiko = float(profil["risiko"].sum())
    getroffen = int((abdeckung["beste_wirkung"] >= 2).sum()) if not abdeckung.empty else 0
    mittlerer_rang = float(team["rang"].mean())

    spalten = st.columns(4)
    spalten[0].markdown(kennzahl_kachel(
        "Teamgroesse", f"{len(team)} / 6",
        "gewaehlte Pokemon"), unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel(
        "Kritische Schwaechen", str(ungedeckt),
        "Angriffstypen ohne Deckung",
        "gefahr" if ungedeckt else "guenstig"), unsafe_allow_html=True)
    spalten[2].markdown(kennzahl_kachel(
        "Offensive Reichweite", f"{getroffen} / 18",
        "Typen mit sehr effektivem Zugriff",
        "guenstig" if getroffen >= REICHWEITE_AUSREICHEND_AB else "gefahr"),
        unsafe_allow_html=True)
    spalten[3].markdown(kennzahl_kachel(
        "Mittlerer Meta-Rang", f"{mittlerer_rang:.0f}",
        "kleiner ist gaengiger"), unsafe_allow_html=True)

    if gesamtrisiko > 60:
        st.error(
            f"Das Team weist ein hohes defensives Gesamtrisiko auf ({gesamtrisiko:.0f}). "
            "Die Registerkarte *Defensive Abdeckung* zeigt, welche Angriffstypen "
            "ungedeckt bleiben."
        )


def _zeige_partner(conn, team: pd.DataFrame, namen: list[str], monat: str,
                   kampfformat: str) -> None:
    """Partnervorschlaege aus dem Beziehungsfakt, gewichtet nach Teampassung."""
    if len(namen) >= 6:
        st.success("Das Team ist vollstaendig. Fuer Vorschlaege einen Platz freimachen.")
        return

    vorschlaege = kpi.teampartner(conn, namen, monat, kampfformat, grenze=8)
    if vorschlaege.empty:
        st.info("Zu dieser Auswahl liegen keine Partnerdaten vor.")
        return

    st.markdown(
        "Die Quelle fuehrt Teampartner nur als **Rangfolge ohne Gewicht**. Es wird "
        "deshalb nicht gemittelt, sondern ausgezaehlt: wie oft ein Partner in den "
        "Listen der gewaehlten Pokemon auftaucht und auf welchem Rang. Ein Partner, "
        "der bei mehreren Teammitgliedern vorne steht, ist der bessere Vorschlag."
    )

    spalten = st.columns(4)
    for spalte, (_, zeile) in zip(spalten, vorschlaege.head(4).iterrows(), strict=False):
        with spalte:
            st.markdown(
                "<div class='karte karte--guenstig'>"
                f"<div style='font-weight:700;'>{zeile['partner']}</div>"
                f"<div style='font-size:0.82rem;margin-top:4px;'>genannt bei "
                f"<b>{int(zeile['nennungen'])}</b> Teammitglied(ern)</div>"
                f"<div style='font-size:0.78rem;opacity:0.8;'>bester Rang "
                f"{int(zeile['bester_rang'])}</div>"
                f"<div style='font-size:0.74rem;opacity:0.7;'>passt zu {zeile['passt_zu']}</div>"
                "</div>", unsafe_allow_html=True,
            )

    st.markdown("")
    tabelle(
        vorschlaege.rename(columns={
            "partner": "Vorschlag", "nennungen": "Nennungen",
            "bester_rang": "Bester Rang", "mittlerer_rang": "Mittlerer Rang",
            "passt_zu": "Passt zu",
        })[["Vorschlag", "Nennungen", "Bester Rang", "Mittlerer Rang", "Passt zu"]],
    )


def _zeige_defensive(conn, team: pd.DataFrame, monat: str, kampfformat: str) -> None:
    """Vollstaendige Typenmatrix des Teams."""
    haeufigkeit = threat.angriffstyp_haeufigkeit(conn, monat, kampfformat)
    profil = threat.team_defensivprofil(team, haeufigkeit)

    from ..typechart import eingehender_multiplikator

    matrix = pd.DataFrame(
        [[eingehender_multiplikator(angriffstyp, zeile["typ1"], zeile["typ2"])
          for _, zeile in team.iterrows()]
         for angriffstyp in profil["angriffstyp"]],
        index=[TYP_DEUTSCH.get(t, t) for t in profil["angriffstyp"]],
        columns=team["anzeigename"].tolist(),
    )

    # Hier ist ein hoher Wert der schlechte: der Faktor misst den Schaden, den
    # das eigene Team einsteckt. Der Verlauf laeuft deshalb umgekehrt.
    abbildung = px.imshow(
        matrix, text_auto=True, aspect="auto",
        color_continuous_scale=design.VERLAUF_ANFAELLIGKEIT,
        color_continuous_midpoint=1.0,
        labels={"x": "", "y": "Angriffstyp", "color": "Faktor"},
        title="Schadensmultiplikatoren je Teammitglied",
        height=620,
    )
    st.plotly_chart(abbildung, width="stretch")

    st.caption(
        "Gruen = resistent oder immun, rot = anfaellig. Ein Wert von 4 entsteht, wenn "
        "beide Typen eines Pokemon gegen denselben Angriffstyp anfaellig sind."
    )

    luecken = profil[(profil["anfaellig"] > 0) & (profil["resistent"] + profil["immun"] == 0)]
    if not luecken.empty:
        st.warning(
            "**Ohne jede Deckung:** " + ", ".join(
                TYP_DEUTSCH.get(t, t) for t in luecken["angriffstyp"]
            ) + ". Ein Pokemon mit passender Resistenz oder ein entsprechender "
            "Tera-Typ schliesst diese Luecken."
        )


def _zeige_offensive(conn, namen: list[str], monat: str, kampfformat: str) -> None:
    """Gegen welche Typen das Team effektiv Schaden anrichtet."""
    abdeckung = threat.offensive_abdeckung(conn, namen, monat, kampfformat)
    if abdeckung.empty:
        st.info("Keine Attackendaten fuer die Auswahl vorhanden.")
        return

    anzeige = abdeckung.copy()
    anzeige["verteidigungstyp"] = anzeige["verteidigungstyp"].map(
        lambda t: TYP_DEUTSCH.get(t, t))

    abbildung = px.bar(
        anzeige.sort_values("beste_wirkung"), x="beste_wirkung", y="verteidigungstyp",
        orientation="h", color="beste_wirkung",
        color_continuous_scale=design.VERLAUF_BILANZ,
        # Faktor 1 ist der neutrale Schaden -- darunter wird abgewehrt, darueber
        # getroffen. Ohne diesen Mittelpunkt laege die Grenze beim Mittelwert
        # der Auswahl und verschoebe sich mit jedem Team.
        color_continuous_midpoint=1.0,
        labels={"beste_wirkung": "Bester Schadensfaktor", "verteidigungstyp": ""},
        title="Offensive Reichweite gegen die 18 Verteidigungstypen",
        text_auto=".2f", height=560,
    )
    abbildung.update_layout(coloraxis_showscale=False)
    st.plotly_chart(abbildung, width="stretch")

    luecken = anzeige[anzeige["beste_wirkung"] < 2]["verteidigungstyp"].tolist()
    if luecken:
        st.warning(
            "**Keine sehr effektive Attacke gegen:** " + ", ".join(luecken) +
            ". Gegen diese Typen muss das Team ueber reine Statuswerte gewinnen."
        )
    else:
        st.success("Das Team trifft jeden Verteidigungstyp mindestens sehr effektiv.")

    st.caption(
        "Beruecksichtigt werden nur Attacken, die in mindestens 15 Prozent der Sets "
        "gespielt werden -- theoretisch erlernbare Attacken bleiben aussen vor."
    )


def _zeige_initiative(conn, team: pd.DataFrame, monat: str, kampfformat: str) -> None:
    """Einordnung der Team-Initiative in die Verteilung des Metagames.

    Grundlage sind die realen Initiativwerte der tatsaechlich gespielten Sets,
    nicht die Basiswerte.
    """
    namen = team["anzeigename"].tolist()
    einordnung = speed.team_einordnung(conn, namen, monat, "normal", kampfformat)

    if einordnung.empty:
        st.info(
            "Fuer die Auswahl liegen keine Fleisspunkte-Verteilungen vor. Bitte die "
            "Bewegungsdaten neu laden."
        )
        return

    tiers = speed.speed_tier_liste(conn, monat, kampfformat)
    abbildung = px.histogram(
        tiers, x="speed_real", nbins=30,
        labels={"speed_real": "Initiative (Stufe 50)", "count": "Anzahl Sets"},
        title="Initiative des Teams im Vergleich zum Metagame",
        color_discrete_sequence=[design.GRAU_FLAECHE], height=460,
    )
    for _, zeile in einordnung.iterrows():
        abbildung.add_vline(
            x=zeile["Initiative"], line_dash="dash", line_color=design.BLAU_HELL,
            annotation_text=f"{zeile['Pokemon']} ({zeile['Initiative']})",
            annotation_position="top",
        )
    st.plotly_chart(abbildung, width="stretch")

    tabelle(einordnung)

    st.caption(
        "Die Initiative ist aus Basiswert, Wesen und Fleisspunkten des jeweils "
        "haeufigsten Sets berechnet (Turnierstufe 50). Detaillierte Szenarien -- "
        "Rueckenwind, Wahlschal, Bizarroraum -- finden sich auf der Seite *Speed-Tiers*."
    )

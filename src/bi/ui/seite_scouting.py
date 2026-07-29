"""Seite: Gegner-Scouting.

Analysiert ein gegnerisches Team: welche Konfiguration zu erwarten ist, welche
Strategie es verfolgt, wo es angreifbar ist und welche Pokemon des Metagames ihm
gefaehrlich werden.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..analytics import kpi, threat
from ..config import TYP_DEUTSCH, sprite_url
from .komponenten import (
    hinweis_leere_datenbank,
    hinweis_messniveau,
    hole_verbindung,
    kopfauswahl,
    typ_abzeichen_paar,
)


def zeichne() -> None:
    conn = hole_verbindung()

    st.title("Gegner-Scouting")
    if not kpi.verfuegbare_formate(conn):
        hinweis_leere_datenbank()
        return

    kampfformat, monat = kopfauswahl(conn, "scouting")
    if not monat:
        st.warning("Fuer dieses Format liegen keine Daten vor.")
        return

    verfuegbar = kpi.meta_uebersicht(conn, monat, kampfformat)
    hinweis_messniveau()
    if True:
        auswahl = st.multiselect(
            "Gegnerisches Team zusammenstellen (bis zu sechs Pokemon)",
            options=verfuegbar["anzeigename"].tolist(),
            max_selections=6,
            help="Die Auswahl umfasst alle Pokemon, die am gewaehlten Tag "
                 "einen Nutzungsrang erhalten haben.",
        )

    if not auswahl:
        st.info(
            "Waehle oben mindestens ein Pokemon aus, um die Analyse zu starten. "
            "Die Auswertung wird mit jedem weiteren Teammitglied aussagekraeftiger."
        )
        _zeige_meta_einstieg(verfuegbar)
        return

    team = verfuegbar[verfuegbar["anzeigename"].isin(auswahl)].reset_index(drop=True)

    _zeige_teamuebersicht(conn, team, monat, kampfformat)

    reiter = st.tabs([
        "Erwartete Konfiguration", "Strategie-Erkennung", "Defensive Schwaechen",
        "Gefaehrlichste Gegner", "Rohdaten",
    ])

    with reiter[0]:
        _zeige_konfiguration(conn, team, monat, kampfformat)
    with reiter[1]:
        _zeige_strategie(conn, auswahl, monat, kampfformat)
    with reiter[2]:
        _zeige_schwaechen(conn, team, monat, kampfformat)
    with reiter[3]:
        _zeige_bedrohungen(conn, team, monat, kampfformat)
    with reiter[4]:
        st.dataframe(team.drop(columns=[s for s in ("usage_sk", "pokemon_sk", "zeit_sk",
                                                    "regulation_sk", "skill_sk")
                                        if s in team.columns]),
                     use_container_width=True)


# --------------------------------------------------------------------------

def _zeige_meta_einstieg(verfuegbar: pd.DataFrame) -> None:
    """Zeigt die meistgenutzten Pokemon als Einstiegshilfe."""
    st.markdown("#### Meistgespielte Pokemon am gewaehlten Tag")
    spalten = st.columns(6)
    for spalte, (_, zeile) in zip(spalten, verfuegbar.head(6).iterrows(), strict=False):
        with spalte:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<img src='{sprite_url(int(zeile['pokedex_id']))}' width='84'>"
                f"<div style='font-size:0.82rem;font-weight:600;'>{zeile['anzeigename']}</div>"
                f"<div style='font-size:0.75rem;opacity:0.7;'>Rang {int(zeile['rang'])}</div>"
                f"</div>", unsafe_allow_html=True,
            )


def _zeige_teamuebersicht(conn, team: pd.DataFrame, monat: str, kampfformat: str) -> None:
    """Visuelle Uebersicht des gegnerischen Teams mit Standardkonfiguration."""
    st.markdown("### Teamuebersicht")
    spalten = st.columns(len(team))

    for spalte, (_, zeile) in zip(spalten, team.iterrows(), strict=True):
        set_daten = kpi.standardset(conn, zeile["anzeigename"], monat, kampfformat)
        top_item = set_daten["items"].iloc[0] if not set_daten["items"].empty else None
        top_faehigkeit = (set_daten["faehigkeiten"].iloc[0]
                          if not set_daten["faehigkeiten"].empty else None)
        top_wesen = set_daten["wesen"].iloc[0] if not set_daten["wesen"].empty else None

        with spalte:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<img src='{sprite_url(int(zeile['pokedex_id']))}' width='110'>"
                f"<div style='font-weight:700;margin-top:2px;'>{zeile['anzeigename']}</div>"
                f"<div style='margin:5px 0;'>{typ_abzeichen_paar(zeile['typ1'], zeile['typ2'])}</div>"
                f"<div style='font-size:0.78rem;opacity:0.75;'>Rang {int(zeile['rang'])} "
                f"von {int(zeile['erfasste_pokemon'])}</div></div>",
                unsafe_allow_html=True,
            )
            if top_faehigkeit is not None:
                st.markdown(f"**Faehigkeit** · {top_faehigkeit['bezeichnung']} "
                            f"({top_faehigkeit['anteil']:.0f} %)")
            if top_item is not None:
                st.markdown(f"**Item** · {top_item['bezeichnung']} "
                            f"({top_item['anteil']:.0f} %)")
            if top_wesen is not None:
                st.markdown(f"**Wesen** · {top_wesen['bezeichnung']} "
                            f"({top_wesen['anteil']:.0f} %)")

            attacken = set_daten["attacken"].head(4)
            if not attacken.empty:
                zeilen = "".join(
                    f"<div>{a['bezeichnung']} <span style='opacity:0.6;'>{a['anteil']:.0f} %</span></div>"
                    for _, a in attacken.iterrows()
                )
                st.markdown(
                    f"<div style='font-size:0.8rem;line-height:1.45;margin-top:4px;'>{zeilen}</div>",
                    unsafe_allow_html=True,
                )


def _zeige_konfiguration(conn, team: pd.DataFrame, monat: str, kampfformat: str) -> None:
    """Vollstaendige Verteilung von Attacken, Items und Tera-Typen je Pokemon."""
    st.markdown(
        "Angezeigt wird die **vollstaendige Verteilung** statt einer festen Anzahl "
        "von Attacken. Daran ist ablesbar, wie einheitlich ein Set gespielt wird: "
        "vier Attacken nahe 100 Prozent bedeuten ein festgelegtes Standard-Set, "
        "breit gestreute Anteile deuten auf mehrere gaengige Varianten hin."
    )

    for _, zeile in team.iterrows():
        set_daten = kpi.standardset(conn, zeile["anzeigename"], monat, kampfformat)
        with st.expander(f"{zeile['anzeigename']} · Rang {int(zeile['rang'])}",
                         expanded=len(team) <= 2):
            links, mitte, rechts = st.columns([2, 1, 1])

            with links:
                attacken = set_daten["attacken"]
                if attacken.empty:
                    st.write("Keine Attackendaten vorhanden.")
                else:
                    abbildung = px.bar(
                        attacken.sort_values("anteil"), x="anteil", y="bezeichnung",
                        orientation="h", color="taktik_klasse",
                        labels={"anteil": "Anteil der Sets (%)", "bezeichnung": "",
                                "taktik_klasse": "Funktion"},
                        text_auto=".0f", height=300,
                    )
                    abbildung.update_layout(margin={"t": 10}, legend={"orientation": "h",
                                                                     "y": -0.25})
                    st.plotly_chart(abbildung, use_container_width=True)

            with mitte:
                st.markdown("**Items**")
                for _, i in set_daten["items"].head(5).iterrows():
                    st.markdown(f"{i['bezeichnung']} · **{i['anteil']:.0f} %**")

            with rechts:
                st.markdown("**Wesen**")
                for _, w in set_daten["wesen"].head(4).iterrows():
                    st.markdown(f"{w['bezeichnung']} · **{w['anteil']:.0f} %**")


def _zeige_strategie(conn, namen: list[str], monat: str, kampfformat: str) -> None:
    """Strategie-Radar auf Basis der angereicherten Taktik-Klassen."""
    befunde = threat.strategie_radar(conn, namen, monat, kampfformat)

    st.markdown(
        "Die Erkennung arbeitet ueber die im ETL angereicherte **Taktik-Klasse** einer "
        "Attacke, nicht ueber eine feste Liste von Attackennamen. Neue Attacken mit "
        "gleicher Funktion werden dadurch automatisch mit erfasst."
    )

    if not befunde:
        st.info(
            "Keine der hinterlegten Spezialstrategien erkannt. Das deutet auf ein "
            "klassisches Offensivteam hin, das ueber Statuswerte und Typenabdeckung "
            "gewinnt statt ueber einen Feldeffekt."
        )
        return

    for befund in befunde:
        text = (f"**{befund['titel']}**\n\n{befund['hinweis']}\n\n"
                f"*Traeger:* {', '.join(befund['traeger'])} — "
                f"*ueber:* {', '.join(befund['attacken'][:5])}")
        if befund["stufe"] == "warnung":
            st.warning(text)
        else:
            st.info(text)


def _zeige_schwaechen(conn, team: pd.DataFrame, monat: str, kampfformat: str) -> None:
    """Defensivprofil, gewichtet mit der tatsaechlichen Meta-Haeufigkeit."""
    haeufigkeit = threat.angriffstyp_haeufigkeit(conn, monat, kampfformat)
    profil = threat.team_defensivprofil(team, haeufigkeit)

    st.markdown(
        "Eine Typenschwaeche wiegt nur so schwer, wie der Angriffstyp tatsaechlich "
        "gespielt wird. Die Spalte **Risiko** verrechnet daher die ungedeckten "
        "Anfaelligkeiten mit der aus der Faktentabelle ermittelten Praesenz des "
        "Angriffstyps im Metagame."
    )

    kritisch = profil[profil["bewertung"].str.startswith("Kritisch")]
    if not kritisch.empty:
        st.error(
            "**Ungedeckte Schwaechen:** " + ", ".join(
                f"{TYP_DEUTSCH.get(z['angriffstyp'], z['angriffstyp'])} "
                f"({z['anfaellig']} Pokemon, {z['meta_anteil']:.1f} % des Metagames)"
                for _, z in kritisch.iterrows()
            ) + ". Gegen diese Typen fehlt dem Team jede Resistenz oder Immunitaet."
        )
    else:
        st.success("Keine kritisch ungedeckte Typenschwaeche im Team.")

    anzeige = profil.copy()
    anzeige["angriffstyp"] = anzeige["angriffstyp"].map(lambda t: TYP_DEUTSCH.get(t, t))
    abbildung = px.bar(
        anzeige[anzeige["risiko"] > 0].sort_values("risiko"),
        x="risiko", y="angriffstyp", orientation="h", color="risiko",
        color_continuous_scale="Reds",
        labels={"risiko": "Risikowert", "angriffstyp": ""},
        title="Ungedeckte Schwaechen, gewichtet mit der Meta-Haeufigkeit",
        text_auto=".1f", height=420,
    )
    abbildung.update_layout(coloraxis_showscale=False)
    st.plotly_chart(abbildung, use_container_width=True)

    st.dataframe(
        anzeige.rename(columns={
            "angriffstyp": "Angriffstyp", "anfaellig": "Anfaellig",
            "resistent": "Resistent", "immun": "Immun",
            "schlimmster_faktor": "Hoechster Faktor", "meta_anteil": "Meta-Anteil (%)",
            "risiko": "Risiko", "bewertung": "Bewertung",
        }), use_container_width=True, hide_index=True, height=420,
    )


def _zeige_bedrohungen(conn, team: pd.DataFrame, monat: str, kampfformat: str) -> None:
    """Berechneter Bedrohungsindex als Ersatz fuer die leeren Quell-Counter."""
    st.markdown(
        "Die Smogon-Auswertung fuehrt zwar ein Feld *Checks and Counters*, dieses ist "
        "fuer die VGC-Formate jedoch durchgaengig unbefuellt. Die folgende Rangliste "
        "wird deshalb **selbst berechnet** -- aus der Typen-Regelbasis, den Basiswerten, "
        "den tatsaechlich gespielten Attacken und der Nutzungshaeufigkeit."
    )

    bedrohungen = threat.bedrohungsindex(conn, team, monat, kampfformat, grenze=10)
    if bedrohungen.empty:
        st.info("Keine Bedrohungen ermittelbar -- vermutlich fehlen Attackendaten.")
        return

    spalten = st.columns(5)
    for spalte, (_, zeile) in zip(spalten, bedrohungen.head(5).iterrows(), strict=False):
        with spalte:
            st.markdown(
                f"<div style='text-align:center;padding:8px;border-radius:10px;"
                f"background:rgba(231,76,60,0.10);'>"
                f"<img src='{sprite_url(int(zeile['pokedex_id']))}' width='92'>"
                f"<div style='font-weight:700;font-size:0.9rem;'>{zeile['anzeigename']}</div>"
                f"<div style='font-size:0.76rem;opacity:0.75;'>Bedrohung "
                f"{zeile['bedrohungswert']:.0f}</div>"
                f"<div style='font-size:0.74rem;opacity:0.65;'>{zeile['beste_attacke']}</div>"
                f"</div>", unsafe_allow_html=True,
            )

    st.markdown("")
    st.dataframe(
        bedrohungen.rename(columns={
            "anzeigename": "Pokemon", "typ_kombination": "Typen",
            "rang": "Rang im Meta", "bedrohungswert": "Bedrohungswert",
            "anzahl_gefaehrdet": "Gefaehrdete Mitglieder", "beste_attacke": "Gefaehrlichste Attacke",
            "gefaehrdet": "Betroffen",
        })[["Pokemon", "Typen", "Rang im Meta", "Bedrohungswert", "Gefaehrlichste Attacke",
            "Gefaehrdete Mitglieder", "Betroffen"]],
        use_container_width=True, hide_index=True,
    )

    st.caption(
        "Der Bedrohungswert kombiniert die Wirksamkeit der gespielten Attacken gegen "
        "die Typen des Teams, den Initiativevorteil des Angreifers und dessen "
        "Haeufigkeit im Metagame. Er ist eine relative Rangkennzahl, keine absolute "
        "Schadensprognose."
    )

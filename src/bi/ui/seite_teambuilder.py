"""Seite: Team-Builder.

Unterstuetzt den Aufbau eines eigenen Teams: datengestuetzte Partnervorschlaege,
laufende Bewertung der defensiven Abdeckung und der offensiven Reichweite.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..analytics import kpi, threat
from ..config import TYP_DEUTSCH, sprite_url
from .komponenten import (
    hinweis_leere_datenbank,
    hole_verbindung,
    kennzahl_kachel,
    monatsauswahl,
    typ_abzeichen_paar,
)


def zeichne() -> None:
    conn = hole_verbindung()
    monate = kpi.verfuegbare_monate(conn)

    st.title("Team-Builder")
    if not monate:
        hinweis_leere_datenbank()
        return

    kopf_links, kopf_rechts = st.columns([3, 1])
    with kopf_rechts:
        monat = monatsauswahl(monate, "builder_monat")

    verfuegbar = kpi.meta_uebersicht(conn, monat)
    with kopf_links:
        auswahl = st.multiselect(
            "Eigenes Team (bis zu sechs Pokemon)",
            options=verfuegbar["anzeigename"].tolist(), max_selections=6,
        )

    if not auswahl:
        st.info(
            "Waehle ein erstes Pokemon aus. Der Builder schlaegt daraufhin Partner vor, "
            "die im Metagame statistisch am haeufigsten gemeinsam mit der Auswahl "
            "gespielt werden, und bewertet laufend die Abdeckung des Teams."
        )
        return

    team = verfuegbar[verfuegbar["anzeigename"].isin(auswahl)].reset_index(drop=True)

    _zeige_bewertung(conn, team, auswahl, monat)
    st.markdown("---")

    reiter = st.tabs([
        "Partnervorschlaege", "Defensive Abdeckung", "Offensive Reichweite",
        "Initiative im Vergleich",
    ])

    with reiter[0]:
        _zeige_partner(conn, team, auswahl, monat)
    with reiter[1]:
        _zeige_defensive(conn, team, monat)
    with reiter[2]:
        _zeige_offensive(conn, auswahl, monat)
    with reiter[3]:
        _zeige_initiative(conn, team, monat)


# --------------------------------------------------------------------------

def _zeige_bewertung(conn, team: pd.DataFrame, namen: list[str], monat: str) -> None:
    """Kennzahlenzeile mit der laufenden Bewertung des Teams."""
    haeufigkeit = threat.angriffstyp_haeufigkeit(conn, monat)
    profil = threat.team_defensivprofil(team, haeufigkeit)
    abdeckung = threat.offensive_abdeckung(conn, namen, monat)

    ungedeckt = int((profil["bewertung"].str.startswith("Kritisch")).sum())
    gesamtrisiko = float(profil["risiko"].sum())
    getroffen = int((abdeckung["beste_wirkung"] >= 2).sum()) if not abdeckung.empty else 0
    mittlere_nutzung = float(team["usage_rate"].mean())

    spalten = st.columns(4)
    spalten[0].markdown(kennzahl_kachel(
        "Teamgroesse", f"{len(team)} / 6",
        "gewaehlte Pokemon", "#6390F0"), unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel(
        "Kritische Schwaechen", str(ungedeckt),
        "Angriffstypen ohne Deckung",
        "#e74c3c" if ungedeckt else "#2ecc71"), unsafe_allow_html=True)
    spalten[2].markdown(kennzahl_kachel(
        "Offensive Reichweite", f"{getroffen} / 18",
        "Typen mit sehr effektivem Zugriff",
        "#2ecc71" if getroffen >= 12 else "#f1c40f"), unsafe_allow_html=True)
    spalten[3].markdown(kennzahl_kachel(
        "Mittlere Meta-Nutzung", f"{mittlere_nutzung:.1f} %",
        "Standard- oder Nischenwahl", "#A33EA1"), unsafe_allow_html=True)

    if gesamtrisiko > 60:
        st.error(
            f"Das Team weist ein hohes defensives Gesamtrisiko auf ({gesamtrisiko:.0f}). "
            "Die Registerkarte *Defensive Abdeckung* zeigt, welche Angriffstypen "
            "ungedeckt bleiben."
        )


def _zeige_partner(conn, team: pd.DataFrame, namen: list[str], monat: str) -> None:
    """Partnervorschlaege aus dem Beziehungsfakt, gewichtet nach Teampassung."""
    if len(namen) >= 6:
        st.success("Das Team ist vollstaendig. Fuer Vorschlaege einen Platz freimachen.")
        return

    vorschlaege = kpi.teampartner(conn, namen, monat, grenze=8)
    if vorschlaege.empty:
        st.info("Zu dieser Auswahl liegen keine Partnerdaten vor.")
        return

    st.markdown(
        "Der Synergiewert gibt an, in wie viel Prozent der Teams mit den gewaehlten "
        "Pokemon der jeweilige Partner ebenfalls vertreten ist. Partner, die zu "
        "**mehreren** Teammitgliedern passen, werden hoeher gewichtet -- sie fuegen "
        "sich in das Gesamtkonzept ein und nicht nur an einen einzelnen Slot."
    )

    spalten = st.columns(4)
    for spalte, (_, zeile) in zip(spalten, vorschlaege.head(4).iterrows(), strict=False):
        with spalte:
            st.markdown(
                f"<div style='text-align:center;padding:10px;border-radius:12px;"
                f"background:rgba(46,204,113,0.10);'>"
                f"<img src='{sprite_url(int(zeile['partner_pokedex_id']))}' width='100'>"
                f"<div style='font-weight:700;'>{zeile['partner']}</div>"
                f"<div style='margin:4px 0;'>"
                f"{typ_abzeichen_paar(zeile['partner_typ1'], zeile['partner_typ2'])}</div>"
                f"<div style='font-size:0.82rem;'>gemeinsam in "
                f"<b>{zeile['mittlerer_anteil']:.0f} %</b> der Teams</div>"
                f"<div style='font-size:0.74rem;opacity:0.7;'>passt zu {zeile['passt_zu']}</div>"
                f"</div>", unsafe_allow_html=True,
            )

    st.markdown("")
    st.dataframe(
        vorschlaege.rename(columns={
            "partner": "Vorschlag", "mittlerer_anteil": "Mittlerer Anteil (%)",
            "treffer": "Passt zu (Anzahl)", "passt_zu": "Passt zu",
            "punktzahl": "Gewichtete Punktzahl",
        })[["Vorschlag", "Mittlerer Anteil (%)", "Passt zu (Anzahl)", "Passt zu",
            "Gewichtete Punktzahl"]],
        use_container_width=True, hide_index=True,
    )


def _zeige_defensive(conn, team: pd.DataFrame, monat: str) -> None:
    """Vollstaendige Typenmatrix des Teams."""
    haeufigkeit = threat.angriffstyp_haeufigkeit(conn, monat)
    profil = threat.team_defensivprofil(team, haeufigkeit)

    from ..typechart import eingehender_multiplikator

    matrix = pd.DataFrame(
        [[eingehender_multiplikator(angriffstyp, zeile["typ1"], zeile["typ2"])
          for _, zeile in team.iterrows()]
         for angriffstyp in profil["angriffstyp"]],
        index=[TYP_DEUTSCH.get(t, t) for t in profil["angriffstyp"]],
        columns=team["anzeigename"].tolist(),
    )

    abbildung = px.imshow(
        matrix, text_auto=True, aspect="auto",
        color_continuous_scale=["#1a5c2a", "#2ecc71", "#f5f5f5", "#e67e22", "#c0392b"],
        color_continuous_midpoint=1.0,
        labels={"x": "", "y": "Angriffstyp", "color": "Faktor"},
        title="Schadensmultiplikatoren je Teammitglied",
        height=620,
    )
    st.plotly_chart(abbildung, use_container_width=True)

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


def _zeige_offensive(conn, namen: list[str], monat: str) -> None:
    """Gegen welche Typen das Team effektiv Schaden anrichtet."""
    abdeckung = threat.offensive_abdeckung(conn, namen, monat)
    if abdeckung.empty:
        st.info("Keine Attackendaten fuer die Auswahl vorhanden.")
        return

    anzeige = abdeckung.copy()
    anzeige["verteidigungstyp"] = anzeige["verteidigungstyp"].map(
        lambda t: TYP_DEUTSCH.get(t, t))

    abbildung = px.bar(
        anzeige.sort_values("beste_wirkung"), x="beste_wirkung", y="verteidigungstyp",
        orientation="h", color="beste_wirkung",
        color_continuous_scale=["#c0392b", "#e67e22", "#f5f5f5", "#2ecc71"],
        labels={"beste_wirkung": "Bester Schadensfaktor", "verteidigungstyp": ""},
        title="Offensive Reichweite gegen die 18 Verteidigungstypen",
        text_auto=".2f", height=560,
    )
    abbildung.update_layout(coloraxis_showscale=False)
    st.plotly_chart(abbildung, use_container_width=True)

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


def _zeige_initiative(conn, team: pd.DataFrame, monat: str) -> None:
    """Einordnung der Team-Initiative in die Speed-Verteilung des Metagames."""
    meta = kpi.meta_uebersicht(conn, monat)
    relevant = meta[meta["usage_rate"] >= 3]

    abbildung = px.histogram(
        relevant, x="speed", nbins=28,
        labels={"speed": "Basis-Initiative", "count": "Anzahl Pokemon"},
        title="Initiative des Teams im Vergleich zum Metagame",
        color_discrete_sequence=["#4a5568"], height=460,
    )
    for _, zeile in team.iterrows():
        abbildung.add_vline(
            x=zeile["speed"], line_dash="dash", line_color="#EF553B",
            annotation_text=zeile["anzeigename"], annotation_position="top",
        )
    st.plotly_chart(abbildung, use_container_width=True)

    einordnung = []
    for _, zeile in team.iterrows():
        perzentil = 100 * (relevant["speed"] < zeile["speed"]).mean()
        einordnung.append({
            "Pokemon": zeile["anzeigename"],
            "Basis-Initiative": int(zeile["speed"]),
            "Schneller als (% des Metas)": round(perzentil, 1),
            "Speed-Klasse": zeile["speed_klasse"],
        })
    st.dataframe(pd.DataFrame(einordnung).sort_values("Basis-Initiative", ascending=False),
                 use_container_width=True, hide_index=True)

    st.caption(
        "Grundlage sind die Basiswerte ohne Berücksichtigung von Wesen, EV-Verteilung "
        "oder Items wie dem Wahlschal. Rueckenwind verdoppelt die Initiative, "
        "Bizarroraum kehrt die Reihenfolge um."
    )

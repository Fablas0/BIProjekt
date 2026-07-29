"""Seite: Team-Preview-Advisor.

Beantwortet die Frage, die im Turnier unter Zeitdruck faellt: welche Pokemon
sollen aus den eigenen sechs mitgenommen werden -- vier im Doppelkampf, drei im
Einzelkampf.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..analytics import preview
from ..config import sprite_url
from .komponenten import (
    hole_verbindung,
    kennzahl_kachel,
    typ_abzeichen_paar,
)


def zeichne() -> None:
    conn = hole_verbindung()

    st.title("Team-Preview-Advisor")

    vorhanden = conn.execute("SELECT COUNT(*) FROM Fact_Champions_Usage").fetchone()[0]
    if vorhanden == 0:
        st.info(
            "**Es liegen noch keine Champions-Daten vor.**\n\n"
            "Wechsle zu *ETL & Datenqualitaet* und starte dort den Champions-Ladelauf. "
            "Die Auswertung dieser Seite stuetzt sich bewusst auf Pokemon Champions, "
            "weil das seit April 2026 die offizielle Wettkampfplattform ist."
        )
        return

    st.markdown(
        "Im Team-Preview siehst du die sechs Pokemon des Gegners und waehlst daraus "
        "deine Kaempfer. Diese Auswertung rechnet **alle Kombinationen beider Seiten "
        "gegeneinander durch** und empfiehlt die Auswahl mit der besten Bilanz."
    )

    # ------------------------------------------------------------------
    kopf = st.columns([1, 1, 1])
    with kopf[0]:
        kampfformat = st.selectbox(
            "Kampfformat", ["Doubles", "Singles"], key="preview_format",
            help="Doppelkampf: vier von sechs. Einzelkampf: drei von sechs.",
        )
    mitnahme = 4 if kampfformat == "Doubles" else 3

    auswahl = pd.read_sql("""
        SELECT DISTINCT anzeigename, rang FROM V_Usage_Aktuell
        WHERE kampfformat = ? ORDER BY rang
    """, conn, params=(kampfformat,))
    namen = auswahl["anzeigename"].tolist()

    with kopf[1]:
        st.metric("Auswahlgroesse", f"{mitnahme} von 6")
    with kopf[2]:
        saison = conn.execute(
            "SELECT schluessel FROM Dim_Saison WHERE ist_aktuell = 1 LIMIT 1").fetchone()
        st.metric("Saison", saison[0] if saison else "-")

    st.markdown("---")

    links, rechts = st.columns(2)
    with links:
        st.markdown("#### Dein Team")
        mein_team = st.multiselect(
            "Deine sechs Pokemon", namen, max_selections=6, key="preview_eigene",
            label_visibility="collapsed",
        )
    with rechts:
        st.markdown("#### Gegnerisches Team")
        gegner_team = st.multiselect(
            "Die sechs des Gegners", namen, max_selections=6, key="preview_gegner",
            label_visibility="collapsed",
        )

    if len(mein_team) < mitnahme or len(gegner_team) < mitnahme:
        st.info(
            f"Waehle auf beiden Seiten mindestens {mitnahme} Pokemon. Mit jeweils "
            "sechs entspricht die Auswertung dem echten Team-Preview."
        )
        _zeige_meta_hilfe(conn, kampfformat)
        return

    from ..analytics import kpi as kpi_modul

    tag = kpi_modul.aktueller_tag(conn, kampfformat)
    eigene = preview.lade_kaempfer(conn, mein_team, tag, kampfformat)
    gegner = preview.lade_kaempfer(conn, gegner_team, tag, kampfformat)

    if len(eigene) < mitnahme or len(gegner) < mitnahme:
        st.warning(
            "Fuer einen Teil der Auswahl liegen keine aktuellen Saisondaten vor. "
            "Moeglicherweise sind diese Pokemon in der laufenden Saison nicht zugelassen."
        )
        return

    empfehlungen, paarungen = preview.bewerte_auswahlen(eigene, gegner, mitnahme)
    if not empfehlungen:
        st.warning("Die Auswertung lieferte kein Ergebnis.")
        return

    beste = empfehlungen[0]

    # ------------------------------------------------------------------
    st.markdown("### Empfehlung")
    _zeige_empfehlung(beste, eigene, mitnahme, len(paarungen) // len(empfehlungen))

    reiter = st.tabs([
        "Begruendung", "Alle Auswahlen", "Gegen welche Gegnerauswahl?",
        "Einzelduelle",
    ])

    with reiter[0]:
        _zeige_begruendung(beste, eigene, gegner)
    with reiter[1]:
        _zeige_alle(empfehlungen)
    with reiter[2]:
        _zeige_gegnerauswahlen(paarungen, empfehlungen)
    with reiter[3]:
        _zeige_einzelduelle(eigene, gegner)


# --------------------------------------------------------------------------

def _zeige_meta_hilfe(conn, kampfformat: str) -> None:
    """Zeigt die meistgespielten Pokemon als Einstiegshilfe."""
    top = pd.read_sql("""
        SELECT anzeigename, pokedex_id, typ1, typ2, rang
        FROM V_Usage_Aktuell
        WHERE kampfformat = ? ORDER BY rang LIMIT 8
    """, conn, params=(kampfformat,))
    if top.empty:
        return

    st.markdown(f"#### Meistgespielt im {kampfformat}-Format")
    spalten = st.columns(8)
    for spalte, (_, z) in zip(spalten, top.iterrows(), strict=False):
        with spalte:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<img src='{sprite_url(int(z['pokedex_id']))}' width='74'>"
                f"<div style='font-size:0.76rem;font-weight:600;'>{z['anzeigename']}</div>"
                f"<div style='font-size:0.7rem;opacity:0.7;'>Rang {int(z['rang'])}</div>"
                f"</div>", unsafe_allow_html=True,
            )


def _zeige_empfehlung(beste: preview.Empfehlung, eigene: list[preview.Kaempfer],
                      mitnahme: int, gegnerauswahlen: int) -> None:
    """Hebt die empfohlene Auswahl hervor."""
    nach_name = {k.name: k for k in eigene}

    spalten = st.columns(mitnahme)
    for spalte, name in zip(spalten, beste.auswahl, strict=True):
        k = nach_name[name]
        beitrag = beste.beitraege.get(name, 0.0)
        farbe = "#2ecc71" if beitrag > 0 else "#e74c3c"
        with spalte:
            st.markdown(
                f"<div style='text-align:center;padding:12px 6px;border-radius:12px;"
                f"background:rgba(46,204,113,0.10);border:1px solid rgba(46,204,113,0.35);'>"
                f"<img src='{sprite_url(k.pokedex_id)}' width='112'>"
                f"<div style='font-weight:700;margin-top:2px;'>{k.name}</div>"
                f"<div style='margin:5px 0;'>{typ_abzeichen_paar(k.typ1, k.typ2)}</div>"
                f"<div style='font-size:0.8rem;'>Initiative {k.speed}</div>"
                f"<div style='font-size:0.8rem;color:{farbe};font-weight:600;'>"
                f"Beitrag {beitrag:+.2f}</div>"
                f"</div>", unsafe_allow_html=True,
            )

    st.markdown("")
    kacheln = st.columns(4)
    kacheln[0].markdown(kennzahl_kachel(
        "Gesamtwertung", f"{beste.gesamtwertung:+.2f}",
        "Mittelwert und Risiko verrechnet", "#2ecc71"), unsafe_allow_html=True)
    kacheln[1].markdown(kennzahl_kachel(
        "Im Vorteil gegen", f"{beste.gewinnquote:.0f} %",
        f"der {gegnerauswahlen} gegnerischen Auswahlen",
        "#2ecc71" if beste.gewinnquote >= 60 else "#f1c40f"), unsafe_allow_html=True)
    kacheln[2].markdown(kennzahl_kachel(
        "Schlechtester Fall", f"{beste.schlechtester_fall:+.2f}",
        "gegen die unguenstigste Auswahl",
        "#e74c3c" if beste.schlechtester_fall < 0 else "#2ecc71"), unsafe_allow_html=True)
    kacheln[3].markdown(kennzahl_kachel(
        "Bester Fall", f"{beste.bester_fall:+.2f}",
        "gegen die guenstigste Auswahl", "#6390F0"), unsafe_allow_html=True)

    if beste.schlechtester_fall < 0:
        st.warning(
            "Diese Auswahl hat eine Paarung, in der sie im Nachteil ist. Die "
            "Registerkarte *Gegen welche Gegnerauswahl?* zeigt, welche das ist."
        )


def _zeige_begruendung(beste: preview.Empfehlung, eigene: list[preview.Kaempfer],
                       gegner: list[preview.Kaempfer]) -> None:
    """Erlaeutert die Empfehlung im Klartext."""
    for text in preview.begruendung(beste, eigene, gegner):
        st.markdown(f"- {text}")

    st.markdown("")
    st.markdown("#### Beitrag der einzelnen Pokemon")
    beitraege = pd.DataFrame(
        [{"Pokemon": n, "Beitrag": w} for n, w in beste.beitraege.items()]
    ).sort_values("Beitrag")

    abbildung = px.bar(
        beitraege, x="Beitrag", y="Pokemon", orientation="h",
        color="Beitrag", color_continuous_scale=["#c0392b", "#f5f5f5", "#2ecc71"],
        color_continuous_midpoint=0, text_auto="+.2f", height=300,
        title="Wer traegt die Auswahl, wer belastet sie?",
    )
    abbildung.update_layout(coloraxis_showscale=False)
    st.plotly_chart(abbildung, use_container_width=True)

    st.caption(
        "Der Beitrag ist der gemittelte Bewertungsanteil eines Pokemon ueber alle "
        "gegnerischen Auswahlen hinweg. Negative Werte bedeuten nicht, dass das "
        "Pokemon schlecht ist -- nur, dass es gegen dieses Team wenig ausrichtet."
    )


def _zeige_alle(empfehlungen: list[preview.Empfehlung]) -> None:
    """Rangliste aller moeglichen eigenen Auswahlen."""
    tabelle = preview.empfehlungen_als_tabelle(empfehlungen)

    abbildung = px.bar(
        tabelle.head(15).sort_values("Gesamtwertung"),
        x="Gesamtwertung", y="Auswahl", orientation="h",
        color="Gesamtwertung", color_continuous_scale=["#c0392b", "#f5f5f5", "#2ecc71"],
        color_continuous_midpoint=0, text_auto="+.2f",
        height=max(380, 26 * min(len(tabelle), 15)),
        title="Bewertung aller moeglichen Auswahlen",
    )
    abbildung.update_layout(coloraxis_showscale=False)
    st.plotly_chart(abbildung, use_container_width=True)

    st.dataframe(tabelle, use_container_width=True, hide_index=True, height=420)

    st.caption(
        "Die Gesamtwertung verrechnet den Mittelwert ueber alle gegnerischen Auswahlen "
        "mit dem unguenstigsten Fall. Damit gewinnt keine Auswahl, die im Mittel gut "
        "dasteht, aber gegen eine bestimmte Aufstellung einbricht."
    )


def _zeige_gegnerauswahlen(paarungen: list[preview.Paarung],
                           empfehlungen: list[preview.Empfehlung]) -> None:
    """Zeigt, wie die empfohlene Auswahl gegen jede gegnerische abschneidet."""
    beschriftungen = {" · ".join(e.auswahl): e.auswahl for e in empfehlungen}
    gewaehlt = st.selectbox("Eigene Auswahl", list(beschriftungen),
                            key="preview_auswahl_detail")

    matrix = preview.matchup_matrix(paarungen, beschriftungen[gewaehlt])
    if matrix.empty:
        st.info("Keine Paarungen vorhanden.")
        return

    abbildung = px.bar(
        matrix, x="Punktzahl", y="Gegnerische Auswahl", orientation="h",
        color="Punktzahl", color_continuous_scale=["#c0392b", "#f5f5f5", "#2ecc71"],
        color_continuous_midpoint=0, text_auto="+.2f",
        height=max(380, 26 * len(matrix)),
        title="Bewertung gegen jede moegliche gegnerische Auswahl",
    )
    abbildung.update_layout(coloraxis_showscale=False,
                            yaxis={"categoryorder": "total descending"})
    st.plotly_chart(abbildung, use_container_width=True)

    schlecht = matrix[matrix["Punktzahl"] < 0]
    if not schlecht.empty:
        st.error(
            f"Gegen {len(schlecht)} von {len(matrix)} gegnerischen Auswahlen bist du "
            "im Nachteil. Die kritischste: **"
            + schlecht.iloc[0]["Gegnerische Auswahl"] + "**."
        )
    else:
        st.success("Diese Auswahl ist gegen jede gegnerische Aufstellung im Vorteil.")

    st.dataframe(matrix, use_container_width=True, hide_index=True, height=360)


def _zeige_einzelduelle(eigene: list[preview.Kaempfer],
                        gegner: list[preview.Kaempfer]) -> None:
    """Matrix aller Einzelduelle -- macht die Gesamtbewertung nachvollziehbar."""
    duelle = preview.einzelduelle(eigene, gegner)

    matrix = duelle.pivot(index="Eigenes Pokemon", columns="Gegner", values="Bewertung")
    abbildung = px.imshow(
        matrix, text_auto=".2f", aspect="auto",
        color_continuous_scale=["#c0392b", "#f5f5f5", "#2ecc71"],
        color_continuous_midpoint=0,
        labels={"color": "Bewertung"},
        title="Einzelduelle: eigenes Pokemon gegen gegnerisches",
        height=max(360, 62 * len(matrix)),
    )
    st.plotly_chart(abbildung, use_container_width=True)

    st.caption(
        "Gruen bedeutet Vorteil fuer dein Pokemon, rot Nachteil. Die Bewertung "
        "verrechnet den ausgeuebten Druck, den erlittenen Druck und die Initiative."
    )

    st.dataframe(
        duelle.sort_values("Bewertung", ascending=False),
        use_container_width=True, hide_index=True, height=360,
    )

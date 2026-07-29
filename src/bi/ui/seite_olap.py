"""Seite: OLAP-Explorer.

Macht den Datenwuerfel interaktiv navigierbar. Alle klassischen OLAP-Operationen
sind ueber die Oberflaeche ausfuehrbar: Slice und Dice ueber die Filter,
Drill-Down und Roll-Up ueber die Schaltflaechen am Konsolidierungspfad, Pivot
ueber das Vertauschen der Achsen, Split und Merge ueber das Hinzunehmen oder
Entfernen der Spaltenachse.
"""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from ..analytics import olap
from .komponenten import hinweis_leere_datenbank, hole_verbindung, kennzahl_kachel


def _merkmal_optionen() -> dict[str, str]:
    """Auswahlliste aller Merkmale, gruppiert nach Dimension."""
    return {
        f"{merkmal.dimension}: {merkmal.bezeichnung}": merkmal.schluessel
        for merkmale in olap.HIERARCHIEN.values() for merkmal in merkmale
    }


def zeichne() -> None:
    conn = hole_verbindung()
    wuerfel = olap.lade_wuerfel(conn)

    st.title("OLAP-Explorer")
    if wuerfel.empty:
        hinweis_leere_datenbank()
        return

    st.markdown(
        "Der Wuerfel wird relational gehalten (ROLAP): die multidimensionale Sicht "
        "entsteht zur Laufzeit aus der Faktentabelle. Die Steuerelemente entsprechen "
        "den klassischen OLAP-Operationen."
    )

    optionen = _merkmal_optionen()
    umkehr = {wert: beschriftung for beschriftung, wert in optionen.items()}

    # ------------------------------------------------------------------
    # Zustand der Achsen. Drill-Down und Roll-Up veraendern ihn, deshalb
    # muss er ueber die Neuausfuehrung der Seite hinweg erhalten bleiben.
    # ------------------------------------------------------------------
    st.session_state.setdefault("olap_zeile", "anzeigename")
    st.session_state.setdefault("olap_spalte", "monat_name")

    # ------------------------------------------------------------------
    # Slice und Dice
    # ------------------------------------------------------------------
    with st.sidebar:
        st.markdown("### Filter (Slice / Dice)")
        st.caption(
            "Ein Filter auf einer Dimension entspricht einem **Slice**, mehrere "
            "gleichzeitig einem **Dice**."
        )
        bedingungen: dict[str, list] = {}
        for beschriftung, merkmal in (
            ("Zeitraum (Tag)", "tag_label"),
            ("Generation", "generation"),
            ("Primaertyp", "typ1"),
            ("Teamrolle", "rolle"),
            ("Speed-Klasse", "speed_klasse"),
        ):
            werte = sorted(wuerfel[merkmal].dropna().unique().tolist())
            gewaehlt = st.multiselect(beschriftung, werte, key=f"olap_filter_{merkmal}")
            if gewaehlt:
                bedingungen[merkmal] = gewaehlt

        ranggrenze = st.slider(
            "Nur Raenge bis", 10, 250, 250, 10,
            help="Blendet Nischen-Pokemon aus und schaerft dadurch die Verdichtung.",
        )

    teilwuerfel = olap.dice_wuerfel(wuerfel, bedingungen)
    if ranggrenze < 250:
        teilwuerfel = teilwuerfel[teilwuerfel["rang"] <= ranggrenze]

    eckwerte = olap.wuerfel_kennzahlen(teilwuerfel)
    spalten = st.columns(4)
    spalten[0].markdown(kennzahl_kachel("Faktensaetze", f"{eckwerte['zeilen']:,}".replace(",", "."),
                                        "im aktuellen Teilwuerfel", "#6390F0"),
                        unsafe_allow_html=True)
    spalten[1].markdown(kennzahl_kachel("Pokemon", str(eckwerte["pokemon"]),
                                        "unterschiedliche Auspraegungen", "#7AC74C"),
                        unsafe_allow_html=True)
    spalten[2].markdown(kennzahl_kachel("Tage", str(eckwerte["tage"]),
                                        "Zeitdimension", "#EE8130"), unsafe_allow_html=True)
    spalten[3].markdown(kennzahl_kachel("Bester Rang", str(eckwerte["bester_rang"]),
                                        "im Teilwuerfel vertreten", "#A33EA1"),
                        unsafe_allow_html=True)

    if teilwuerfel.empty:
        st.warning("Die Filterkombination liefert keine Daten. Bitte Filter lockern.")
        return

    st.markdown("---")

    # ------------------------------------------------------------------
    # Achsen und Kennzahl
    # ------------------------------------------------------------------
    achse_links, achse_mitte, achse_rechts = st.columns([2, 2, 2])

    with achse_links:
        zeile_beschriftung = st.selectbox(
            "Zeilenachse", list(optionen.keys()),
            index=list(optionen.values()).index(st.session_state["olap_zeile"]),
            key="olap_zeile_auswahl",
        )
        st.session_state["olap_zeile"] = optionen[zeile_beschriftung]

    with achse_mitte:
        spalten_optionen = ["(keine)", *optionen.keys()]
        aktuelle_spalte = st.session_state["olap_spalte"]
        index = (spalten_optionen.index(umkehr[aktuelle_spalte])
                 if aktuelle_spalte in umkehr else 0)
        spalte_beschriftung = st.selectbox(
            "Spaltenachse (Split / Merge)", spalten_optionen, index=index,
            key="olap_spalte_auswahl",
            help="Eine zweite Achse hinzunehmen entspricht **Split**, sie zu "
                 "entfernen entspricht **Merge**.",
        )
        st.session_state["olap_spalte"] = (
            optionen[spalte_beschriftung] if spalte_beschriftung != "(keine)" else None
        )

    with achse_rechts:
        kennzahl_beschriftung = st.selectbox(
            "Kennzahl", [k.bezeichnung for k in olap.KENNZAHLEN.values()], index=0,
        )
        kennzahl_schluessel = next(
            schluessel for schluessel, k in olap.KENNZAHLEN.items()
            if k.bezeichnung == kennzahl_beschriftung
        )

    zeilen_merkmal = st.session_state["olap_zeile"]
    spalten_merkmal = st.session_state["olap_spalte"]

    # ------------------------------------------------------------------
    # Navigation im Konsolidierungspfad
    # ------------------------------------------------------------------
    pfad = olap.hierarchiepfad(zeilen_merkmal)
    aktuell = olap.ALLE_MERKMALE[zeilen_merkmal]
    hinauf = olap.naechste_ebene(zeilen_merkmal, "roll_up")
    hinunter = olap.naechste_ebene(zeilen_merkmal, "drill_down")

    navigation = st.columns([1, 1, 1, 3])
    with navigation[0]:
        if st.button("Roll-Up", disabled=hinauf is None, use_container_width=True,
                     help="Zu einem staerker verdichteten Merkmal wechseln"):
            st.session_state["olap_zeile"] = hinauf
            st.rerun()
    with navigation[1]:
        if st.button("Drill-Down", disabled=hinunter is None, use_container_width=True,
                     help="Zu einem detaillierteren Merkmal wechseln"):
            st.session_state["olap_zeile"] = hinunter
            st.rerun()
    with navigation[2]:
        if st.button("Pivot", disabled=spalten_merkmal is None, use_container_width=True,
                     help="Zeilen- und Spaltenachse vertauschen (Rotation)"):
            st.session_state["olap_zeile"], st.session_state["olap_spalte"] = (
                spalten_merkmal, zeilen_merkmal
            )
            st.rerun()
    with navigation[3]:
        stufen = " → ".join(
            f"<b>{m.bezeichnung}</b>" if m.schluessel == zeilen_merkmal else m.bezeichnung
            for m in pfad
        )
        st.markdown(
            f"<div style='padding-top:6px;'>Konsolidierungspfad "
            f"<i>{aktuell.dimension}</i>: {stufen}</div>", unsafe_allow_html=True,
        )

    st.markdown("")

    # ------------------------------------------------------------------
    # Ergebnis
    # ------------------------------------------------------------------
    if spalten_merkmal:
        tabelle = olap.verdichte(teilwuerfel, zeilen_merkmal, kennzahl_schluessel,
                                 spalten_merkmal)
        if tabelle.empty:
            st.warning("Die gewaehlte Kombination liefert keine Auswertung.")
            return

        # Bei vielen Auspraegungen wird die Kreuztabelle unlesbar -- daher auf
        # die 25 groessten Zeilen beschraenken und darauf hinweisen.
        begrenzt = len(tabelle) > 25
        if begrenzt:
            tabelle = tabelle.loc[tabelle.sum(axis=1).nlargest(25).index]

        abbildung = px.imshow(
            tabelle, text_auto=".1f", aspect="auto", color_continuous_scale="Sunset",
            labels={"x": olap.ALLE_MERKMALE[spalten_merkmal].bezeichnung,
                    "y": aktuell.bezeichnung, "color": kennzahl_beschriftung},
            title=f"{kennzahl_beschriftung} nach {aktuell.bezeichnung} und "
                  f"{olap.ALLE_MERKMALE[spalten_merkmal].bezeichnung}",
            height=max(420, 26 * len(tabelle)),
        )
        st.plotly_chart(abbildung, use_container_width=True)
        if begrenzt:
            st.caption("Dargestellt sind die 25 Auspraegungen mit der hoechsten Summe.")

        st.dataframe(tabelle, use_container_width=True)

    else:
        ergebnis = olap.kennzahl_mit_anteil(teilwuerfel, zeilen_merkmal, kennzahl_schluessel)
        if ergebnis.empty:
            st.warning("Die gewaehlte Kombination liefert keine Auswertung.")
            return

        anzeige = ergebnis.head(30)
        abbildung = px.bar(
            anzeige.sort_values("wert"), x="wert", y=zeilen_merkmal, orientation="h",
            labels={"wert": kennzahl_beschriftung, zeilen_merkmal: ""},
            title=f"{kennzahl_beschriftung} nach {aktuell.bezeichnung}",
            color="wert", color_continuous_scale="Sunset", text_auto=".1f",
            height=max(400, 24 * len(anzeige)),
        )
        abbildung.update_layout(coloraxis_showscale=False)
        st.plotly_chart(abbildung, use_container_width=True)

        st.dataframe(
            ergebnis.rename(columns={
                zeilen_merkmal: aktuell.bezeichnung, "wert": kennzahl_beschriftung,
                "anteil_prozent": "Anteil (%)", "kumuliert_prozent": "Kumuliert (%)",
            }), use_container_width=True, hide_index=True, height=420,
        )

        achtzig = ergebnis[ergebnis["kumuliert_prozent"] <= 80]
        if not achtzig.empty and len(achtzig) < len(ergebnis):
            st.info(
                f"**Konzentration:** {len(achtzig)} von {len(ergebnis)} Auspraegungen "
                f"des Merkmals *{aktuell.bezeichnung}* decken bereits 80 Prozent der "
                f"Kennzahl *{kennzahl_beschriftung}* ab."
            )

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
    # Voreinstellung: Pokemon ueber die Tage. Das ist die Frage, mit der die
    # meisten hierher kommen -- wer steigt, wer faellt.
    st.session_state.setdefault("olap_zeile", "anzeigename")
    st.session_state.setdefault("olap_spalte", "tag_label")

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
        if st.button("Roll-Up", disabled=hinauf is None, width="stretch",
                     help="Zu einem staerker verdichteten Merkmal wechseln"):
            st.session_state["olap_zeile"] = hinauf
            st.rerun()
    with navigation[1]:
        if st.button("Drill-Down", disabled=hinunter is None, width="stretch",
                     help="Zu einem detaillierteren Merkmal wechseln"):
            st.session_state["olap_zeile"] = hinunter
            st.rerun()
    with navigation[2]:
        if st.button("Pivot", disabled=spalten_merkmal is None, width="stretch",
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
    kennzahl = olap.KENNZAHLEN[kennzahl_schluessel]

    if spalten_merkmal:
        tabelle = olap.verdichte(teilwuerfel, zeilen_merkmal, kennzahl_schluessel,
                                 spalten_merkmal)
        if tabelle.empty:
            st.warning("Die gewaehlte Kombination liefert keine Auswertung.")
            return

        _kreuztabelle(tabelle, kennzahl_schluessel, kennzahl_beschriftung,
                      aktuell, olap.ALLE_MERKMALE[spalten_merkmal])
        return

    ergebnis = olap.kennzahl_mit_anteil(teilwuerfel, zeilen_merkmal, kennzahl_schluessel)
    if ergebnis.empty:
        st.warning("Die gewaehlte Kombination liefert keine Auswertung.")
        return

    _rangliste(ergebnis, zeilen_merkmal, kennzahl, kennzahl_beschriftung, aktuell)


def _zeilenzahl(gesamt: int, schluessel: str) -> int | None:
    """Steuerung, wie viele Zeilen die Abbildung zeigt. ``None`` heisst: alle."""
    stufen = [n for n in (10, 20, 30, 50, 100) if n < gesamt]
    beschriftungen = [f"Top {n}" for n in stufen] + [f"Alle ({gesamt})"]
    gewaehlt = st.selectbox(
        "Umfang der Abbildung", beschriftungen,
        index=min(1, len(beschriftungen) - 1), key=f"olap_umfang_{schluessel}",
        help="Die Tabelle darunter enthaelt immer den vollstaendigen Bestand "
             "und laesst sich durch Klick auf eine Spaltenueberschrift sortieren.",
    )
    return None if gewaehlt.startswith("Alle") else stufen[beschriftungen.index(gewaehlt)]


def _kreuztabelle(tabelle, kennzahl_schluessel: str, kennzahl_beschriftung: str,
                  zeilen_merkmal: olap.Merkmal, spalten_merkmal: olap.Merkmal) -> None:
    """Zweiachsige Auswertung: Verlauf ueber die Zeit, sonst Kreuztabelle."""
    kennzahl = olap.KENNZAHLEN[kennzahl_schluessel]

    steuerung = st.columns([1, 3])
    with steuerung[0]:
        anzahl = _zeilenzahl(len(tabelle), "kreuz")

    geordnet = olap.beste_auspraegungen(tabelle, kennzahl_schluessel)
    auswahl = geordnet if anzahl is None else geordnet.head(anzahl)

    # Auf einer Zeitachse ist der Verlauf die Frage, nicht der Einzelwert.
    # Eine Linie je Auspraegung beantwortet sie unmittelbar; eine Heatmap
    # zwingt dazu, Farbnuancen zu vergleichen.
    if spalten_merkmal.dimension == "Zeit":
        lang = (auswahl.T.reset_index()
                .melt(id_vars=spalten_merkmal.schluessel,
                      var_name=zeilen_merkmal.schluessel, value_name="wert")
                .dropna(subset=["wert"]))
        abbildung = px.line(
            lang, x=spalten_merkmal.schluessel, y="wert",
            color=zeilen_merkmal.schluessel, markers=True,
            labels={spalten_merkmal.schluessel: spalten_merkmal.bezeichnung,
                    "wert": kennzahl_beschriftung,
                    zeilen_merkmal.schluessel: zeilen_merkmal.bezeichnung},
            title=f"Verlauf: {kennzahl_beschriftung} je {zeilen_merkmal.bezeichnung} "
                  f"ueber {spalten_merkmal.bezeichnung}",
            height=max(460, 20 * min(len(auswahl), 30)),
        )
        if kennzahl.kleiner_ist_besser:
            # Rang 1 gehoert nach oben, sonst liest sich der Verlauf verkehrt.
            abbildung.update_yaxes(autorange="reversed")
        abbildung.update_layout(hovermode="x unified", legend_title_text="")
        st.plotly_chart(abbildung, width="stretch")
        st.caption(
            "Eine Linie je Auspraegung. Ein unterbrochener Verlauf bedeutet, dass "
            "das Pokemon an diesem Tag nicht platziert war -- diese Luecken werden "
            "bewusst nicht mit einem Wert aufgefuellt."
            + ("  Die Rangachse ist umgekehrt: oben ist besser."
               if kennzahl.kleiner_ist_besser else "")
        )
    else:
        abbildung = px.imshow(
            auswahl, text_auto=".1f", aspect="auto", color_continuous_scale="Sunset",
            labels={"x": spalten_merkmal.bezeichnung, "y": zeilen_merkmal.bezeichnung,
                    "color": kennzahl_beschriftung},
            title=f"{kennzahl_beschriftung} nach {zeilen_merkmal.bezeichnung} und "
                  f"{spalten_merkmal.bezeichnung}",
            height=max(420, 26 * len(auswahl)),
        )
        st.plotly_chart(abbildung, width="stretch")

    if anzahl is not None:
        gute_richtung = "niedrigsten" if kennzahl.kleiner_ist_besser else "hoechsten"
        st.caption(
            f"Abgebildet sind {len(auswahl)} von {len(tabelle)} Auspraegungen -- "
            f"jene mit dem {gute_richtung} Wert der Kennzahl *{kennzahl_beschriftung}*. "
            "Die Tabelle darunter zeigt den vollstaendigen Bestand."
        )

    st.markdown(f"**Vollstaendige Auswertung** — {len(geordnet)} Auspraegungen, "
                "sortierbar durch Klick auf eine Spaltenueberschrift")
    st.dataframe(geordnet, width="stretch", height=420)


def _rangliste(ergebnis, zeilen_schluessel: str, kennzahl: olap.Kennzahl,
               kennzahl_beschriftung: str, merkmal: olap.Merkmal) -> None:
    """Einachsige Auswertung (Merge)."""
    steuerung = st.columns([1, 3])
    with steuerung[0]:
        anzahl = _zeilenzahl(len(ergebnis), "rang")

    auswahl = ergebnis if anzahl is None else ergebnis.head(anzahl)

    # ``ergebnis`` ist bereits von der besten zur schwaechsten Auspraegung
    # geordnet. Plotly zeichnet die erste Kategorie unten, deshalb wird fuer die
    # Abbildung umgedreht -- so steht das beste Ergebnis oben.
    abbildung = px.bar(
        auswahl.iloc[::-1], x="wert", y=zeilen_schluessel, orientation="h",
        labels={"wert": kennzahl_beschriftung, zeilen_schluessel: ""},
        title=f"{kennzahl_beschriftung} nach {merkmal.bezeichnung}"
              + (" (kleiner ist besser)" if kennzahl.kleiner_ist_besser else ""),
        color="wert", color_continuous_scale="Sunset", text_auto=".1f",
        height=max(400, 24 * len(auswahl)),
    )
    abbildung.update_layout(coloraxis_showscale=False)
    st.plotly_chart(abbildung, width="stretch")

    if anzahl is not None:
        st.caption(f"Abgebildet sind {len(auswahl)} von {len(ergebnis)} Auspraegungen.")

    umbenannt = {zeilen_schluessel: merkmal.bezeichnung, "wert": kennzahl_beschriftung,
                 "anteil_prozent": "Anteil (%)", "kumuliert_prozent": "Kumuliert (%)"}
    st.markdown(f"**Vollstaendige Auswertung** — {len(ergebnis)} Auspraegungen, "
                "sortierbar durch Klick auf eine Spaltenueberschrift")
    st.dataframe(ergebnis.rename(columns=umbenannt), width="stretch",
                 hide_index=True, height=420)

    if not kennzahl.anteil_zulaessig:
        st.caption(
            f"Fuer *{kennzahl_beschriftung}* wird kein Anteil ausgewiesen. Ein "
            "Prozentwert setzt voraus, dass die Summe der Werte etwas bedeutet -- "
            "die Summe aller Raenge tut das nicht."
        )
        return

    achtzig = ergebnis[ergebnis["kumuliert_prozent"] <= 80]
    if not achtzig.empty and len(achtzig) < len(ergebnis):
        st.info(
            f"**Konzentration:** {len(achtzig)} von {len(ergebnis)} Auspraegungen "
            f"des Merkmals *{merkmal.bezeichnung}* decken bereits 80 Prozent der "
            f"Kennzahl *{kennzahl_beschriftung}* ab."
        )

"""Seite: Meta-Playbook.

Erklaert die gaengigen Spielweisen des Formats und verbindet sie mit den
geladenen Daten: zu jedem Archetyp wird ausgewiesen, welchen Anteil er im
aktuellen Metagame tatsaechlich hat und wie er sich entwickelt.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..analytics import kpi
from ..etl.transform import faehigkeit_klasse
from .komponenten import hinweis_leere_datenbank, hole_verbindung, kopfauswahl, seitenkopf

# Archetypen des Formats. Die Erkennung erfolgt datengestuetzt ueber die im ETL
# angereicherte Taktik-Klasse der Attacken bzw. die Effektklasse der Faehigkeiten.
ARCHETYPEN = [
    {
        "name": "Bizarroraum",
        "erkennung": ("attacke", "Bizarroraum"),
        "konzept": (
            "Die Attacke *Bizarroraum* kehrt die Initiative fuer fuenf Runden um -- die "
            "langsamsten Pokemon handeln zuerst. Das Team besteht aus einem Setzer und "
            "sehr langsamen, aber schlagkraeftigen Angreifern, die diesen Zeitraum nutzen."
        ),
        "gegenmittel": [
            "Verhoehner blockiert den Setzer, bevor er zum Zug kommt.",
            "Den Setzer mit beiden Pokemon gleichzeitig angreifen und sofort ausschalten.",
            "Die fuenf Runden mit Schutz und Einwechseln aussitzen.",
            "Selbst Bizarroraum einsetzen -- der zweite Einsatz hebt den ersten auf.",
        ],
    },
    {
        "name": "Rueckenwind / Offensive",
        "erkennung": ("attacke", "Initiative-Kontrolle"),
        "konzept": (
            "*Rueckenwind* verdoppelt die Initiative des eigenen Teams fuer vier Runden. "
            "Schnelle Angreifer kommen dadurch zuerst zum Zug und sollen die Partie in "
            "diesem Zeitfenster entscheiden."
        ),
        "gegenmittel": [
            "Prioritaetsattacken wirken unabhaengig von der Initiative.",
            "Eigener Rueckenwind stellt das Kraefteverhaeltnis wieder her.",
            "Bizarroraum macht den Geschwindigkeitsvorteil wertlos.",
            "Tempo senkende Attacken wie Eissturm gleichen den Vorteil aus.",
        ],
    },
    {
        "name": "Wetter-Teams",
        "erkennung": ("faehigkeit", "Wetter"),
        "konzept": (
            "Faehigkeiten wie *Niesel* oder *Duerre* setzen das Wetter beim Einwechseln "
            "passiv. Das verstaerkt bestimmte Attacken und aktiviert wetterabhaengige "
            "Faehigkeiten, die etwa die Initiative verdoppeln."
        ),
        "gegenmittel": [
            "Den Wetterkrieg gewinnen: eigenes Wetter nach dem gegnerischen setzen.",
            "Den Setzer ausschalten -- das Wetter laeuft nach fuenf Runden aus.",
            "Auf Pokemon setzen, die vom gegnerischen Wetter nicht profitieren.",
        ],
    },
    {
        "name": "Terrain-Kontrolle",
        "erkennung": ("faehigkeit", "Terrain"),
        "konzept": (
            "Terrain-Faehigkeiten veraendern das gesamte Spielfeld: Psychofeld blockiert "
            "Prioritaetsattacken, Grasfeld schwaecht Boden-Attacken und heilt, Elektrofeld "
            "verhindert Schlaf."
        ),
        "gegenmittel": [
            "Das Terrain mit einem eigenen Terrain-Setzer ueberschreiben.",
            "Typen einwechseln, die von den verstaerkten Attacken nicht getroffen werden.",
            "Breitenschutz blockiert die haeufig kombinierten Flaechenattacken.",
        ],
    },
    {
        "name": "Umleitung / Support",
        "erkennung": ("attacke", "Umleitung"),
        "konzept": (
            "*Rechte Hand* und *Wutpulver* ziehen gegnerische Attacken auf sich und "
            "schuetzen so den Partner, waehrend dieser Statuswerte aufbaut oder eine "
            "starke Attacke vorbereitet."
        ),
        "gegenmittel": [
            "Flaechenattacken treffen beide Pokemon und umgehen die Umleitung.",
            "Verhoehner unterbindet die Umleitung im Voraus.",
            "Den umleitenden Partner zuerst ausschalten.",
        ],
    },
    {
        "name": "Statuswert-Aufbau",
        "erkennung": ("attacke", "Setup"),
        "konzept": (
            "Ein Pokemon steigert seine Statuswerte und wird mit jeder Runde gefaehrlicher. "
            "Der Partner deckt diesen Aufbau ab, etwa durch Umleitung oder Schutz."
        ),
        "gegenmittel": [
            "Dunkelnebel oder Klaersmog entfernen alle Statusveraenderungen.",
            "Verhoehner verhindert den Aufbau von vornherein.",
            "Sofortiger Druck, bevor der Aufbau abgeschlossen ist.",
        ],
    },
]


def zeichne() -> None:
    conn = hole_verbindung()

    seitenkopf("Meta-Playbook", "Was folgt daraus fuer die Vorbereitung?")
    if not kpi.verfuegbare_formate(conn):
        hinweis_leere_datenbank()
        return

    st.markdown(
        "Zu jedem Archetyp wird nicht nur die Spielweise erklaert, sondern auch der "
        "**tatsaechliche Anteil im geladenen Metagame** ausgewiesen. Die Zuordnung "
        "erfolgt ueber die im ETL angereicherte Taktik-Klasse der gespielten Attacken "
        "und die Effektklasse der Faehigkeiten."
    )

    kampfformat, monat = kopfauswahl(conn, "playbook")
    if not monat:
        st.warning("Fuer dieses Format liegen keine Daten vor.")
        return
    verbreitung = _archetyp_verbreitung(conn, monat, kampfformat)

    if not verbreitung.empty:
        abbildung = px.bar(
            verbreitung.sort_values("anteil"), x="anteil", y="archetyp", orientation="h",
            labels={"anteil": "Praesenzindex", "archetyp": ""},
            title=f"Verbreitung der Archetypen am {monat}",
            color="anteil", color_continuous_scale="Sunset", text_auto=".1f", height=380,
        )
        abbildung.update_layout(coloraxis_showscale=False)
        st.plotly_chart(abbildung, width="stretch")
        st.caption(
            "Der Wert summiert die Meta-Praesenz aller Pokemon, die eine "
            "entsprechende Attacke oder Faehigkeit fuehren. Da die Quelle die Nutzung "
            "nur als Rang liefert, ist das ein Praesenzindex und kein Prozentanteil -- "
            "er dient dem Vergleich der Archetypen untereinander."
        )

    st.markdown("---")

    anteile = dict(zip(verbreitung["archetyp"], verbreitung["anteil"], strict=False)) \
        if not verbreitung.empty else {}
    traeger = dict(zip(verbreitung["archetyp"], verbreitung["traeger"], strict=False)) \
        if not verbreitung.empty else {}

    for archetyp in ARCHETYPEN:
        anteil = anteile.get(archetyp["name"], 0.0)
        titel = f"{archetyp['name']} · Praesenzindex {anteil:.1f}"

        with st.expander(titel, expanded=False):
            st.markdown(f"**Konzept**\n\n{archetyp['konzept']}")

            liste = traeger.get(archetyp["name"], [])
            if liste:
                st.markdown("**Haeufigste Vertreter im gewaehlten Monat**")
                st.markdown(", ".join(n for n, _ in liste[:8]))
            else:
                st.caption("Im gewaehlten Monat nicht nachweisbar vertreten.")

            st.markdown("**Gegenmassnahmen**")
            for punkt in archetyp["gegenmittel"]:
                st.markdown(f"- {punkt}")


def _archetyp_verbreitung(conn, monat: str, kampfformat: str) -> pd.DataFrame:
    """Berechnet den Anteil jedes Archetyps am Metagame des Monats.

    Grundlage sind die Faktentabellen: ein Pokemon zaehlt zu einem Archetyp, wenn
    es eine entsprechende Attacke bzw. Faehigkeit in mindestens 15 Prozent seiner
    Sets fuehrt.
    """
    attacken = pd.read_sql("""
        SELECT m.taktik_klasse, m.anzeigename, u.rang_perzentil
        FROM V_Merkmal m
        JOIN V_Usage u ON u.pokemon_sk = m.pokemon_sk AND u.zeit_sk = m.zeit_sk
                      AND u.kampfformat_sk = m.kampfformat_sk AND u.saison_sk = m.saison_sk
        WHERE m.kategorie = 'move' AND m.datum_iso = ? AND m.kampfformat = ?
          AND m.saison_aktuell = 1 AND m.anteil >= 15 AND m.taktik_klasse IS NOT NULL
    """, conn, params=(monat, kampfformat))

    roh = pd.read_sql("""
        SELECT m.anzeigename, m.bezeichnung AS faehigkeit, u.rang_perzentil
        FROM V_Merkmal m
        JOIN V_Usage u ON u.pokemon_sk = m.pokemon_sk AND u.zeit_sk = m.zeit_sk
                      AND u.kampfformat_sk = m.kampfformat_sk AND u.saison_sk = m.saison_sk
        WHERE m.kategorie = 'ability' AND m.datum_iso = ? AND m.kampfformat = ?
          AND m.saison_aktuell = 1 AND m.anteil >= 40
    """, conn, params=(monat, kampfformat))
    # Die Effektklasse ist eine Anreicherung; die Quelle liefert nur den Namen.
    faehigkeiten = roh.assign(effekt_klasse=roh["faehigkeit"].map(faehigkeit_klasse))

    zeilen = []
    for archetyp in ARCHETYPEN:
        art, klasse = archetyp["erkennung"]
        quelle = attacken if art == "attacke" else faehigkeiten
        spalte = "taktik_klasse" if art == "attacke" else "effekt_klasse"

        treffer = quelle[quelle[spalte] == klasse]
        if treffer.empty:
            zeilen.append({"archetyp": archetyp["name"], "anteil": 0.0, "traeger": []})
            continue

        # Je Pokemon nur einmal zaehlen, auch wenn es mehrere passende Attacken hat.
        # Gezaehlt wird die Meta-Praesenz (Rangperzentil), nicht ein Anteil --
        # die Quelle liefert die Nutzung nur ordinal.
        je_pokemon = treffer.groupby("anzeigename")["rang_perzentil"].max().sort_values(
            ascending=False)
        zeilen.append({
            "archetyp": archetyp["name"],
            "anteil": round(float(je_pokemon.sum()) / 100, 1),
            "traeger": list(je_pokemon.items()),
        })

    return pd.DataFrame(zeilen)

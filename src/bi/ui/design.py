"""Zentrales Designsystem der Oberflaeche.

Alle Farben, Abstaende und Rundungen stehen hier an einer Stelle. Zuvor lagen
sie als HTML-Schnipsel in den Seitenmodulen verstreut -- allein
``seite_scouting`` enthielt dreizehn eigene ``style``-Angaben, die von denen der
anderen Seiten abwichen. Eine Aenderung an der Darstellung war damit eine
Aenderung an acht Dateien.

Farbwelt
--------
Die Grundfarben sind die der Marke Pokemon: Blau, Gelb und Rot. Sie sind hier
aber **semantisch** belegt und nicht dekorativ verteilt -- jede Farbe traegt
genau eine Bedeutung:

===============  ===========  =======================================
Merkmal          Farbe        Bedeutung
===============  ===========  =======================================
``--empfehlung`` Gelb         Das Ergebnis, nach dem gesucht wurde
``--gefahr``     Rot          Bedrohung, Verwundbarkeit, Warnung
``--guenstig``   Gruen        Vorteil, bestandene Pruefung
``--akzent``     Blau         Navigation und Bedienelemente
===============  ===========  =======================================

Das ist keine Kosmetik, sondern folgt aus dem Anwendungsfall: im Team-Preview
bleiben rund **60 Sekunden**, um vier von sechs Pokemon zu waehlen. Wer in
dieser Zeit erst entziffern muss, welche Farbe was bedeutet, hat verloren. Gelb
erscheint deshalb ausschliesslich dort, wo die Anwendung eine Empfehlung
ausspricht -- und nirgends sonst.

Die 18 Typenfarben bleiben davon unberuehrt: sie kennzeichnen Pokemon-Typen und
sind dem Spieler vertraut.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------
# Farbmarken
# --------------------------------------------------------------------------
# Die Markenfarben von Pokemon. Blau und Gelb stammen aus dem Schriftzug, Rot
# aus der Wortmarke der Hauptreihe.
POKEMON_BLAU = "#3B4CCA"
POKEMON_GELB = "#FFCB05"
POKEMON_ROT = "#EE1515"
POKEMON_GOLD = "#B3A125"

# Fuer dunkle Flaechen aufgehellte Varianten -- die Markenfarben sind auf Weiss
# abgestimmt und verlieren auf dunklem Grund an Kontrast.
BLAU_HELL = "#6C7AE0"
GRUEN = "#2ECC71"

# Reihenfolge der Diagrammfarben. Beginnt bewusst nicht mit Gelb: diese Farbe
# ist der Empfehlung vorbehalten und darf in einem beliebigen Diagramm nicht
# auftauchen, sonst verliert sie ihre Signalwirkung.
DIAGRAMM_FOLGE = [
    BLAU_HELL, "#6390F0", "#7AC74C", "#F95587", "#EE8130",
    "#A98FF3", "#96D9D6", "#C22E28", "#B7B7CE", "#A33EA1",
]

# Verlauf fuer Kennzahlen, bei denen ein kleiner Wert der bessere ist -- etwa
# ein Rang. Von kraeftigem Blau (gut) nach blass (schwach).
VERLAUF_RANG = [[0.0, POKEMON_BLAU], [0.5, "#6390F0"], [1.0, "#C9D4F5"]]
VERLAUF_NEUTRAL = [[0.0, "#1F2A6E"], [0.5, BLAU_HELL], [1.0, "#FFE27A"]]


def _stilblatt() -> str:
    """Das vollstaendige Stilblatt der Anwendung."""
    return f"""
    <style>
    :root {{
        --akzent:      {POKEMON_BLAU};
        --akzent-hell: {BLAU_HELL};
        --empfehlung:  {POKEMON_GELB};
        --gefahr:      {POKEMON_ROT};
        --guenstig:    {GRUEN};

        --flaeche:       rgba(128, 128, 128, 0.09);
        --flaeche-stark: rgba(128, 128, 128, 0.16);
        --linie:         rgba(128, 128, 128, 0.26);

        --radius:   12px;
        --radius-s:  8px;
        --abstand-s:  6px;
        --abstand-m: 14px;
        --abstand-l: 22px;
    }}

    /* ---------------------------------------------------------------
       Navigation. Ein Kasten je Seite; der aktive traegt die Akzentfarbe
       als linke Kante, damit die aktuelle Position ohne Lesen erkennbar ist.

       Angesprochen werden die Kaesten ueber ``st-key-nav_*``. Diese Klasse
       entsteht aus dem Schluessel des Bedienelements und ist damit der
       einzige Haken, der nicht von Streamlits erzeugten Klassennamen
       abhaengt -- die aendern sich mit jeder Fassung.
       --------------------------------------------------------------- */
    [data-testid="stSidebar"] [class*="st-key-nav_"] button {{
        justify-content: flex-start !important;
        width: 100% !important;
        padding: 0.5rem 0.75rem !important;
        margin-bottom: 3px;
        border-radius: var(--radius-s) !important;
        border: 1px solid transparent !important;
        border-left: 3px solid transparent !important;
        background: var(--flaeche) !important;
        color: inherit !important;
        transition: background 120ms ease, border-color 120ms ease;
    }}
    [data-testid="stSidebar"] [class*="st-key-nav_"] button p {{
        text-align: left;
        font-weight: 500;
        margin: 0;
    }}
    [data-testid="stSidebar"] [class*="st-key-nav_"] button:hover {{
        background: var(--flaeche-stark) !important;
        border-left-color: var(--akzent-hell) !important;
    }}
    /* Die aktive Seite: getoente Flaeche, kraeftige Kante, fetter Text. */
    [data-testid="stSidebar"] [class*="st-key-nav_"] button[kind="primary"] {{
        background: rgba(108, 122, 224, 0.20) !important;
        border-left-color: var(--akzent-hell) !important;
    }}
    [data-testid="stSidebar"] [class*="st-key-nav_"] button[kind="primary"] p {{
        font-weight: 700;
    }}

    .nav-gruppe {{
        font-size: 0.68rem;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        opacity: 0.55;
        margin: var(--abstand-m) 0 var(--abstand-s);
        font-weight: 600;
    }}

    /* ---------------------------------------------------------------
       Kennzahlkacheln
       --------------------------------------------------------------- */
    .kachel {{
        padding: var(--abstand-m) 16px;
        border-radius: var(--radius);
        background: var(--flaeche);
        border-left: 4px solid var(--akzent-hell);
        height: 100%;
    }}
    .kachel-beschriftung {{
        font-size: 0.72rem;
        opacity: 0.7;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    .kachel-wert {{
        font-size: 1.75rem;
        font-weight: 700;
        line-height: 1.2;
        font-variant-numeric: tabular-nums;
    }}
    .kachel-hinweis {{ font-size: 0.78rem; opacity: 0.65; }}

    /* ---------------------------------------------------------------
       Seitenkopf: Titel, Aufgabe der Seite und Datenstand in einem Block
       --------------------------------------------------------------- */
    .seitenkopf {{
        border-bottom: 1px solid var(--linie);
        padding-bottom: var(--abstand-m);
        margin-bottom: var(--abstand-l);
    }}
    .seitenkopf h1 {{ margin: 0 0 2px; font-size: 1.9rem; }}
    .seitenkopf .aufgabe {{ font-size: 0.94rem; opacity: 0.8; }}
    .seitenkopf .stand {{
        font-size: 0.78rem; opacity: 0.6; margin-top: var(--abstand-s);
        font-variant-numeric: tabular-nums;
    }}

    /* ---------------------------------------------------------------
       Empfehlungskarten. Gelb erscheint ausschliesslich hier: im
       Team-Preview bleiben rund 60 Sekunden, die Auswahl muss ohne
       Lesen erkennbar sein.
       --------------------------------------------------------------- */
    .empfehlung-karte {{
        border-radius: var(--radius);
        padding: var(--abstand-m) 10px;
        text-align: center;
        background: linear-gradient(180deg,
            rgba(255, 203, 5, 0.16), rgba(255, 203, 5, 0.05));
        border: 2px solid var(--empfehlung);
        height: 100%;
    }}
    .verworfen-karte {{
        border-radius: var(--radius);
        padding: var(--abstand-m) 10px;
        text-align: center;
        background: var(--flaeche);
        border: 1px solid var(--linie);
        opacity: 0.5;
        height: 100%;
    }}
    .karten-name {{ font-weight: 700; font-size: 1rem; margin: 6px 0 4px; }}
    .karten-wert {{
        font-size: 1.4rem; font-weight: 700; color: var(--empfehlung);
        font-variant-numeric: tabular-nums;
    }}

    /* Fliesstext in Tabellen und Zahlen gleich breit setzen, damit
       Rangspalten untereinander stehen. */
    [data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}
    </style>
    """


def einbinden() -> None:
    """Bindet das Stilblatt ein. Genau einmal je Seitenaufbau aufzurufen."""
    st.markdown(_stilblatt(), unsafe_allow_html=True)


def plotly_grundstil() -> None:
    """Setzt einen gemeinsamen Grundstil fuer alle Diagramme.

    Zuvor legte jedes Diagramm seine Schrift, Hoehe und Farbskala selbst fest.
    Dadurch unterschied sich dasselbe Merkmal je nach Seite in der Farbe, was
    der Farbe ihre Aussagekraft nahm.
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    vorlage = go.layout.Template()
    vorlage.layout = go.Layout(
        colorway=DIAGRAMM_FOLGE,
        font={"family": "system-ui, -apple-system, 'Segoe UI', sans-serif", "size": 13},
        title={"font": {"size": 16}, "x": 0, "xanchor": "left"},
        margin={"l": 10, "r": 10, "t": 52, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"gridcolor": "rgba(128,128,128,0.18)", "zeroline": False},
        yaxis={"gridcolor": "rgba(128,128,128,0.18)", "zeroline": False},
        legend={"bgcolor": "rgba(0,0,0,0)", "borderwidth": 0},
        hoverlabel={"font_size": 13},
    )
    pio.templates["vgc"] = vorlage
    pio.templates.default = "plotly_dark+vgc"

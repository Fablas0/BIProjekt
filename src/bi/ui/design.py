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
sind dem Spieler vertraut. Umgekehrt gilt aber auch: eine Typenfarbe darf nur
einen Typ bedeuten. Die Kennzahlkacheln trugen zuvor der Reihe nach Wasser-,
Elektro-, Pflanzen-, Feuer- und Gift-Blau bis -Violett, ohne dass die Zahl
darunter etwas mit dem Typ zu tun hatte. Damit war beides entwertet: die Kachel
sagte nichts, und die Typenfarbe sagte nicht mehr nur eines.

Kein Farbwert im Seitenmodul
----------------------------
Ein Seitenmodul waehlt keine Farbe, sondern eine **Aussage** -- ``guenstig``,
``gefahr``, ``empfehlung`` oder nichts davon. Welcher Farbwert daraus wird,
entscheidet allein diese Datei. ``tests/test_design.py`` haelt das nach: kein
Modul unter ``bi.ui`` darf ein eigenes Farbliteral enthalten.
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

# Neutraler Grauton fuer alles, was im Diagramm nur Hintergrund ist -- etwa die
# Verteilung des Metagames, vor der eine eigene Auswahl eingeordnet wird.
GRAU_FLAECHE = "#4A5568"
GRAU_MITTE = "#8A8F98"
# Dieselbe Hintergrundflaeche, durchscheinend -- fuer gefuellte Kurven, unter
# denen das Gitter sichtbar bleiben soll.
GRAU_FLAECHE_TRANSPARENT = "rgba(138, 143, 152, 0.18)"

# Schrift auf einer eingefaerbten Flaeche. Die 18 Typenfarben sind durchweg
# kraeftig genug, dass Weiss darauf lesbar bleibt.
SCHRIFT_AUF_FARBE = "#FFFFFF"

# Ersatz, wenn zu einem Typ keine Farbe hinterlegt ist -- etwa nach einer neuen
# Spielgeneration, bevor die Palette nachgezogen wurde.
TYP_ERSATZFARBE = "#777777"

# Reihenfolge der Diagrammfarben. Beginnt bewusst nicht mit Gelb: diese Farbe
# ist der Empfehlung vorbehalten und darf in einem beliebigen Diagramm nicht
# auftauchen, sonst verliert sie ihre Signalwirkung.
DIAGRAMM_FOLGE = [
    BLAU_HELL, "#6390F0", "#7AC74C", "#F95587", "#EE8130",
    "#A98FF3", "#96D9D6", "#C22E28", "#B7B7CE", "#A33EA1",
]

# --------------------------------------------------------------------------
# Farbverlaeufe
# --------------------------------------------------------------------------
# Ein Verlauf traegt eine Richtung, und die Richtung muss zur Kennzahl passen.
# ``bi.analytics.olap.Kennzahl`` fuehrt dafuer bereits ``kleiner_ist_besser``;
# die Oberflaeche waehlt den Verlauf danach aus, statt ihn zu raten.

# Kennzahlen, bei denen ein kleiner Wert der bessere ist -- etwa ein Rang.
# Von kraeftigem Blau (gut) nach blass (schwach).
VERLAUF_RANG = [[0.0, POKEMON_BLAU], [0.5, "#6390F0"], [1.0, "#C9D4F5"]]

# Kennzahlen ohne eigene Wertung, bei denen mehr schlicht mehr ist -- Anzahl,
# Praesenzindex, Begegnungshaeufigkeit. Endet in Tuerkis statt wie zuvor in
# einem blassen Gelb: ein Verlauf, der ins Gelbe laeuft, nimmt der Empfehlung
# ihre Signalwirkung.
VERLAUF_NEUTRAL = [[0.0, "#1F2A6E"], [0.5, BLAU_HELL], [1.0, "#9FE8DC"]]

# Abgeschwaechtes Rot fuer einen Befund, der auffallen soll, ohne als harter
# Verstoss zu erscheinen.
ROT_SCHWACH = "#E4645F"

# Risiko und Bedrohung: je hoeher der Wert, desto kraeftiger das Rot.
VERLAUF_GEFAHR = [[0.0, "#F6D9D9"], [0.5, ROT_SCHWACH], [1.0, POKEMON_ROT]]

# Bilanzgroessen mit einem Nullpunkt: negativ ist Nachteil, positiv Vorteil.
# Immer zusammen mit ``color_continuous_midpoint`` verwenden, sonst liegt die
# neutrale Mitte nicht auf dem fachlichen Nullpunkt.
VERLAUF_BILANZ = [POKEMON_ROT, GRAU_MITTE, GRUEN]

# Dieselbe Skala umgekehrt, fuer Groessen, bei denen ein hoher Wert schlecht
# ist -- etwa ein Schadensmultiplikator gegen das eigene Team.
VERLAUF_ANFAELLIGKEIT = [GRUEN, GRAU_MITTE, POKEMON_ROT]

# Vierstufige Guete-Abstufung fuer geordnete Einstufungen (Bestaendigkeit,
# Vorhersagbarkeit). Fuehrt von Gruen ueber Neutral nach Rot -- ohne Gelb, das
# in einer solchen Reihe als mittlere Stufe naheliegen wuerde.
ABSTUFUNG_GUETE = [GRUEN, "#7FBF9B", GRAU_MITTE, POKEMON_ROT]


# Stufen des Qualitaetsberichts. Eine Verkehrsampel haette hier ein gelbes
# Mittelfeld -- doch "Warnung" und "Fehler" sind beide ein *nicht bestanden*
# und unterscheiden sich nur in der Schwere. Zwei Staerken derselben Farbe
# geben das richtig wieder, und Gelb bleibt der Empfehlung vorbehalten.
STUFEN_FARBEN = {"bestanden": GRUEN, "warnung": ROT_SCHWACH, "fehler": POKEMON_ROT}


def abstufung_farben(stufen: list[str]) -> dict[str, str]:
    """Ordnet einer geordneten Einstufung ihre Farben zu.

    ``stufen`` ist von der besten zur schwaechsten Auspraegung anzugeben. Damit
    liegt die Reihenfolge dort, wo sie hingehoert -- an der fachlichen Skala des
    Seitenmoduls --, die Farbwahl aber hier.
    """
    return {stufe: ABSTUFUNG_GUETE[min(i, len(ABSTUFUNG_GUETE) - 1)]
            for i, stufe in enumerate(stufen)}


# --------------------------------------------------------------------------
# Bedeutungen einer Kennzahlkachel
# --------------------------------------------------------------------------
# Mehr als diese vier gibt es nicht. Eine fuenfte Stufe -- etwa ein "geht so"
# zwischen guenstig und gefahr -- waere genau die Abstufung, die in 60 Sekunden
# niemand mehr liest; und sie landete zwangslaeufig bei Gelb.
#
# Eine Kachel verlaesst ``neutral`` nur, wenn die Zahl ein Urteil traegt:
# ``guenstig``   eine Anforderung ist erfuellt, es liegt kein Mangel vor
# ``gefahr``     ein Mangel liegt vor oder eine Anforderung ist verfehlt
# ``empfehlung`` diese Zahl *ist* die Empfehlung der Anwendung
# ``neutral``    eine blosse Angabe ohne Wertung
#
# Gemeint ist eine echte Anforderung -- das Qualitaetstor, eine Typendeckung,
# die Erreichbarkeit eines Benchmarks. Ein Wert, der lediglich hoeher sein
# koennte, bleibt neutral; sonst leuchtet die halbe Seite rot und die Farbe
# sagt wieder nichts.
BEDEUTUNGEN = ("neutral", "guenstig", "gefahr", "empfehlung")


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
       Kennzahlkacheln. Die linke Kante traegt die Aussage: ohne Zusatz
       eine blosse Angabe, sonst guenstig, gefahr oder empfehlung.

       Die Kachel der Empfehlung faerbt zusaetzlich ihre Flaeche ein. Sie
       ist der einzige Ort neben den Empfehlungskarten, an dem Gelb
       auftaucht -- eine gelbe Kante allein ginge im Ueberfliegen unter.
       --------------------------------------------------------------- */
    .kachel {{
        padding: var(--abstand-m) 16px;
        border-radius: var(--radius);
        background: var(--flaeche);
        border-left: 4px solid var(--akzent-hell);
        height: 100%;
    }}
    .kachel--guenstig {{ border-left-color: var(--guenstig); }}
    .kachel--gefahr   {{ border-left-color: var(--gefahr); }}
    .kachel--empfehlung {{
        border-left-color: var(--empfehlung);
        background: linear-gradient(90deg,
            rgba(255, 203, 5, 0.15), var(--flaeche) 65%);
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
       Kompakte Karten in Uebersichten. Ohne Zusatz eine blosse
       Auflistung; der Zusatz traegt dieselben Aussagen wie bei den
       Kacheln und faerbt die Flaeche entsprechend ein.
       --------------------------------------------------------------- */
    .karte {{
        text-align: center;
        padding: 10px 6px;
        border-radius: var(--radius);
        background: var(--flaeche);
        height: 100%;
    }}
    .karte--guenstig {{ background: rgba(46, 204, 113, 0.11); }}
    .karte--gefahr   {{ background: rgba(238, 21, 21, 0.10); }}

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

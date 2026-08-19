"""Seite: Pokedex.

Die uebrigen Seiten beantworten Turnierfragen. Diese Seite beantwortet die
Fragen davor und daneben -- die eines Gelegenheitsspielers, der schlicht etwas
nachschlagen will: Was ist das fuer ein Pokemon, welche Typen treffen es,
seit welcher Generation gibt es das, und **wo bekomme ich es in meinem Spiel**?

Drei Entscheidungen praegen die Seite:

* **Der Steckbrief umfasst den gesamten Pokedex**, nicht nur das Champions-
  Ranked. Wer auf dem DS Diamant gegen den Arenaleiter feststeckt, dem hilft
  eine Rangliste von 2026 nicht -- der Typen-Berater und die Basiswerte helfen
  immer.
* **Fundorte werden verlinkt, nicht kopiert.** Wo ein Pokemon in welchem Spiel
  zu fangen ist, pflegen Bisafans und PokeWiki seit Jahren je Spielstand --
  diese Tiefe laesst sich nicht sinnvoll ins Warehouse duplizieren, wohl aber
  praezise verlinken. Der deutsche Name aus der Dimension ist dabei der
  Schluessel zu den deutschsprachigen Nachschlagewerken.
* **Die Generationsstatistik laeuft auf der Zeitachse der Hauptspiele** (1996
  bis 2022, als Regelbasis in :mod:`bi.generationen`), nicht auf der
  Zeitdimension des Warehouse -- die beginnt erst 2026 und kann die Frage
  "wie ist der Pokedex gewachsen?" gar nicht darstellen.
"""

from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..analytics import saison
from ..config import ALLE_TYPEN, STANDARD_KAMPFFORMAT, sprite_url
from ..generationen import GENERATIONEN_INFO
from ..typechart import ausgehender_multiplikator, defensivprofil
from . import design
from .komponenten import (
    abfrage,
    hinweis_leere_datenbank,
    hole_verbindung,
    kennzahl_kachel,
    name_mit_deutsch,
    seitenkopf,
    tabelle,
    typ_abzeichen,
    typ_abzeichen_paar,
)

# Die Formzusaetze der deutschen Namen (siehe bi.etl.transform.deutscher_formname).
# Fuer die Nachschlagewerke muessen sie wieder herunter: der Bisafans- und der
# PokeWiki-Artikel heissen "Vulnona", nicht "Alola-Vulnona" -- die Formen stehen
# dort als Abschnitte im Artikel der Art.
_REGIONAL_PRAEFIXE = ("Alola-", "Galar-", "Hisui-", "Paldea-")


def artname_deutsch(name_de: str) -> str:
    """Reduziert einen deutschen Formnamen auf den Artnamen des Nachschlagewerks."""
    name = name_de.split(" (")[0].strip()
    for praefix in _REGIONAL_PRAEFIXE:
        if name.startswith(praefix):
            name = name[len(praefix):]
            break
    return name


def nachschlage_links(name_de: str | None, spezies: str) -> list[tuple[str, str]]:
    """Deutsche und englische Nachschlagewerke zu einem Pokemon.

    Bisafans fuehrt Artikel unter dem kleingeschriebenen deutschen Namen,
    PokeWiki als MediaWiki unter dem exakten Namen. Beide dokumentieren je
    Spiel, wo ein Pokemon zu fangen ist -- genau die Information, die keine
    der angebundenen Datenquellen liefert.
    """
    links: list[tuple[str, str]] = []
    if name_de:
        art = artname_deutsch(name_de)
        bisafans = art.lower()
        for umlaut, ersatz in (("ae", "ae"), ("ä", "ae"), ("ö", "oe"),
                               ("ü", "ue"), ("ß", "ss"), ("é", "e")):
            bisafans = bisafans.replace(umlaut, ersatz)
        bisafans = "".join(c for c in bisafans if c.isascii() and c.isalnum())
        links.append(("Bisafans-Pokedex", f"https://www.bisafans.de/pokedex/{bisafans}.php"))
        links.append(("PokeWiki", f"https://www.pokewiki.de/{quote(art)}"))
    links.append(("Pokemon-DB (englisch)", f"https://pokemondb.net/pokedex/{quote(spezies)}"))
    return links


def zeichne() -> None:
    conn = hole_verbindung()
    seitenkopf(
        "Pokedex",
        "Nachschlagen statt auswerten: Steckbrief, Typen-Berater und "
        "Fundort-Links -- auch ganz ohne Ranked-Ambition",
    )

    bestand = abfrage("""
        SELECT pokedex_id, slug, anzeigename, name_de, spezies, generation,
               typ1, typ2, rolle, offensiv_profil, speed_klasse,
               hp, attack, defense, sp_attack, sp_defense, speed,
               stufe50_hp, stufe50_attack, stufe50_defense,
               stufe50_sp_attack, stufe50_sp_defense, stufe50_speed,
               basiswert_summe
        FROM Dim_Pokemon WHERE ist_aktuell = 1
        ORDER BY pokedex_id, slug
    """)
    if bestand.empty:
        hinweis_leere_datenbank()
        return

    _kennzahlen(bestand, conn)

    st.markdown("### Steckbrief")
    gewaehlt = st.selectbox(
        "Pokemon nachschlagen", bestand["anzeigename"].tolist(),
        index=None, key="pokedex_wahl", format_func=name_mit_deutsch,
        placeholder="Name eintippen -- deutsch oder englisch ...",
        help="Die Suche findet beide Namen: 'Vulnona' trifft genauso wie "
             "'Ninetales'. Regionalformen sind eigene Eintraege.",
    )
    if gewaehlt:
        zeile = bestand.loc[bestand["anzeigename"] == gewaehlt].iloc[0]
        _steckbrief(zeile, conn)
        _typen_berater(zeile)
    else:
        st.caption(
            "Der Steckbrief umfasst alle Pokemon der Hauptspiele -- nicht nur "
            "die im Champions-Ranked gefuehrten."
        )

    _generationsstatistik(bestand, conn)


def _kennzahlen(bestand: pd.DataFrame, conn) -> None:
    im_ranked = pd.read_sql(saison.anwenden("""
        SELECT COUNT(DISTINCT slug) AS n FROM V_Usage_Aktuell
        WHERE saison_aktuell = 1
    """, conn), conn)["n"].iloc[0]

    kacheln = st.columns(4)
    with kacheln[0]:
        st.markdown(kennzahl_kachel(
            "Pokemon", str(bestand["spezies"].nunique()),
            "Arten im Pokedex"), unsafe_allow_html=True)
    with kacheln[1]:
        st.markdown(kennzahl_kachel(
            "Formen", str(len(bestand)),
            "einschliesslich Regional- und Sonderformen"), unsafe_allow_html=True)
    with kacheln[2]:
        st.markdown(kennzahl_kachel(
            "Generationen", str(bestand.loc[bestand["generation"] > 0, "generation"].nunique()),
            "1996 bis 2022"), unsafe_allow_html=True)
    with kacheln[3]:
        st.markdown(kennzahl_kachel(
            "Im Champions-Ranked", str(int(im_ranked)),
            "davon aktuell gewertet"), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Steckbrief
# --------------------------------------------------------------------------

_WERTE_BESCHRIFTUNG = [
    ("hp", "KP"), ("attack", "Angriff"), ("defense", "Verteidigung"),
    ("sp_attack", "Spezial-Angriff"), ("sp_defense", "Spezial-Verteidigung"),
    ("speed", "Initiative"),
]


def _steckbrief(zeile: pd.Series, conn) -> None:
    kopf = st.columns([1, 2, 2])
    with kopf[0]:
        st.image(sprite_url(int(zeile["pokedex_id"])), width=170)
    with kopf[1]:
        titel = zeile["name_de"] or zeile["anzeigename"]
        st.markdown(f"## {titel}")
        if zeile["name_de"] and zeile["name_de"] != zeile["anzeigename"]:
            st.caption(f"Englisch: {zeile['anzeigename']} · "
                       f"Pokedex-Nr. {int(zeile['pokedex_id'])}")
        else:
            st.caption(f"Pokedex-Nr. {int(zeile['pokedex_id'])}")
        st.markdown(typ_abzeichen_paar(zeile["typ1"], zeile.get("typ2")),
                    unsafe_allow_html=True)
        info = GENERATIONEN_INFO.get(int(zeile["generation"]))
        if info:
            st.markdown(
                f"**Seit Generation {info.nummer}** -- {info.spiele} "
                f"({info.region}), in Europa erschienen {info.jahr}."
            )
        st.caption(f"{zeile['rolle']} · {zeile['offensiv_profil']}er Angreifer · "
                   f"{zeile['speed_klasse']}")
    with kopf[2]:
        _meta_einordnung(zeile, conn)
        st.markdown("**Nachschlagen und Fundorte**")
        for beschriftung, url in nachschlage_links(zeile["name_de"], zeile["spezies"]):
            st.markdown(f"- [{beschriftung}]({url})")
        st.caption(
            "Wo es dieses Pokemon in welchem Spiel gibt -- Route, Tausch oder "
            "Entwicklung -- steht dort je Edition im Abschnitt zu den Fundorten."
        )

    werte = pd.DataFrame([
        {
            "Wert": beschriftung,
            "Basiswert (Hauptspiele)": int(zeile[feld]),
            "In Champions (Stufe 50)": int(zeile[f"stufe50_{feld}"]),
        }
        for feld, beschriftung in _WERTE_BESCHRIFTUNG
    ])
    tabelle(werte)
    st.caption(
        f"Basiswertsumme {int(zeile['basiswert_summe'])}. Die Champions-Spalte "
        "zeigt die Werte auf Turnierstufe 50 ohne Investition -- genau die "
        "Zahlen, die das Spiel selbst anzeigt."
    )


def _meta_einordnung(zeile: pd.Series, conn) -> None:
    """Aktueller Ranked-Stand, sofern das Pokemon gefuehrt wird."""
    raenge = pd.read_sql(saison.anwenden("""
        SELECT kampfformat_name, rang, erfasste_pokemon
        FROM V_Usage_Aktuell
        WHERE slug = ? AND saison_aktuell = 1
        ORDER BY kampfformat_name
    """, conn), conn, params=(zeile["slug"],))
    if raenge.empty:
        st.caption("Im Champions-Ranked derzeit nicht gewertet.")
        return
    staende = " · ".join(
        f"{z['kampfformat_name']}: Rang {int(z['rang'])} von {int(z['erfasste_pokemon'])}"
        for _, z in raenge.iterrows()
    )
    st.markdown(f"**Im Champions-Ranked:** {staende}")


# --------------------------------------------------------------------------
# Typen-Berater
# --------------------------------------------------------------------------

def _typen_berater(zeile: pd.Series) -> None:
    """Was trifft dieses Pokemon -- und was trifft es selbst?

    Beantwortet die Standardfrage jedes Kampfes gegen Arenaleiter und
    Top Vier, ganz ohne Ranked-Daten: reine Typenlehre aus der Regelbasis.
    """
    st.markdown("#### Typen im Kampf")
    profil = defensivprofil(zeile["typ1"], zeile.get("typ2"))

    spalten = st.columns(2)
    with spalten[0]:
        st.markdown("**Damit wird es getroffen**")
        _typzeile("Sehr effektiv dagegen",
                  {t: f for t, f in profil.items() if f >= 2})
        _typzeile("Wenig Wirkung",
                  {t: f for t, f in profil.items() if 0 < f < 1})
        _typzeile("Gar keine Wirkung",
                  {t: f for t, f in profil.items() if f == 0})

    with spalten[1]:
        st.markdown("**Damit trifft es selbst**")
        eigene = [t for t in (zeile["typ1"], zeile.get("typ2")) if t and pd.notna(t)]
        for typ in eigene:
            staerken = [ziel for ziel in ALLE_TYPEN
                        if ausgehender_multiplikator(typ, ziel) >= 2]
            abzeichen = "".join(typ_abzeichen(z) for z in staerken) or "&ndash;"
            st.markdown(
                f"{typ_abzeichen(typ)} Attacken treffen sehr effektiv: {abzeichen}",
                unsafe_allow_html=True)
        st.caption(
            "Gezeigt sind die eigenen Typen mit Gleichtyp-Bonus. Welche "
            "Attacken ein Set im Ranked tatsaechlich fuehrt, zeigt das "
            "Gegner-Scouting; ob ein Treffer reicht, der Schadensrechner."
        )


def _typzeile(beschriftung: str, typen: dict[str, float]) -> None:
    if not typen:
        return
    abzeichen = "".join(
        typ_abzeichen(t)
        + (f"<span style='font-size:0.72rem;opacity:0.7;'>x{f:g}&nbsp;&nbsp;</span>"
           if f else "")
        for t, f in sorted(typen.items(), key=lambda paar: -paar[1])
    )
    st.markdown(f"{beschriftung}:<br>{abzeichen}", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Generationsstatistik
# --------------------------------------------------------------------------

def _generationsstatistik(bestand: pd.DataFrame, conn) -> None:
    """Wie der Pokedex gewachsen ist -- auf der Zeitachse der Hauptspiele.

    Die Zeitdimension des Warehouse beginnt 2026 und kann diese Frage nicht
    darstellen; die Erscheinungsjahre kommen deshalb aus der Regelbasis
    :mod:`bi.generationen`.
    """
    st.markdown("### Wie der Pokedex gewachsen ist")

    je_generation = (
        bestand.loc[bestand["generation"] > 0]
        .groupby("generation")["spezies"].nunique()
        .rename("neue").reset_index()
    )
    je_generation["jahr"] = je_generation["generation"].map(
        lambda g: GENERATIONEN_INFO[g].jahr if g in GENERATIONEN_INFO else None)
    je_generation["spiele"] = je_generation["generation"].map(
        lambda g: GENERATIONEN_INFO[g].spiele if g in GENERATIONEN_INFO else "?")
    je_generation = je_generation.dropna(subset=["jahr"])
    je_generation["gesamt"] = je_generation["neue"].cumsum()

    figur = go.Figure()
    figur.add_bar(
        x=je_generation["jahr"], y=je_generation["neue"],
        name="Neue Pokemon", marker_color=design.BLAU_HELL,
        customdata=je_generation[["generation", "spiele"]],
        hovertemplate=("Generation %{customdata[0]} (%{customdata[1]}, %{x})"
                       "<br>%{y} neue Pokemon<extra></extra>"),
    )
    figur.add_scatter(
        x=je_generation["jahr"], y=je_generation["gesamt"],
        name="Gesamtbestand", mode="lines+markers",
        line={"color": design.DIAGRAMM_FOLGE[4]},
        hovertemplate="%{x}: %{y} Pokemon insgesamt<extra></extra>",
    )
    figur.update_layout(
        height=380,
        xaxis_title="Europaeischer Verkaufsstart der Generation",
        yaxis_title="Neue Pokemon",
        legend={"orientation": "h", "y": 1.1},
    )
    st.plotly_chart(figur, width="stretch")

    ranked = pd.read_sql(saison.anwenden("""
        SELECT generation, COUNT(DISTINCT spezies) AS im_ranked
        FROM V_Usage_Aktuell
        WHERE kampfformat = ? AND saison_aktuell = 1 AND generation > 0
        GROUP BY generation
    """, conn), conn, params=(STANDARD_KAMPFFORMAT,))

    uebersicht = je_generation.merge(ranked, on="generation", how="left")
    uebersicht["im_ranked"] = uebersicht["im_ranked"].fillna(0).astype(int)
    uebersicht["Anteil im Ranked (%)"] = (
        100 * uebersicht["im_ranked"] / uebersicht["neue"]).round(1)
    tabelle(uebersicht.rename(columns={
        "generation": "Generation", "jahr": "Jahr (Europa)", "spiele": "Spiele",
        "neue": "Neue Pokemon", "gesamt": "Bestand danach",
        "im_ranked": "Im Ranked (Doppel)",
    })[["Generation", "Jahr (Europa)", "Spiele", "Neue Pokemon",
        "Bestand danach", "Im Ranked (Doppel)", "Anteil im Ranked (%)"]])

    st.caption(
        "Gezaehlt werden Arten im Stammdatenbestand der PokeAPI; die "
        "Erscheinungsjahre sind die europaeischen Verkaufsstarts der "
        "jeweiligen Erstlinge. Die letzten Spalten schlagen die Bruecke "
        "zurueck zum Wettkampf: wie viele Arten jeder Generation aktuell im "
        "Champions-Doppel gewertet sind."
    )

"""Tests der Analyseschicht: Kennzahlen, OLAP-Operationen und Bedrohungsanalyse.

Der Schwerpunkt liegt auf dem **Messniveau**: die Quelle liefert die Nutzung
ordinal (Rang), nicht kardinal (Anteil). Die Tests sichern ab, dass die
Kennzahlen dazu passen -- Rangkorrelation statt Konzentrationsindex, und der
Herfindahl-Index ausschliesslich dort, wo echte Anteile vorliegen.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bi.analytics import kpi, olap, threat

# --------------------------------------------------------------------------
# Herfindahl -- nur auf echten Anteilen zulaessig
# --------------------------------------------------------------------------

def test_herfindahl_bei_gleichverteilung() -> None:
    """Bei n gleich grossen Anteilen betraegt der normierte Index 100/n."""
    assert kpi.herfindahl(pd.Series([10.0] * 10)) == pytest.approx(10.0)


def test_herfindahl_bei_voller_konzentration() -> None:
    """Ein einzelner Traeger ergibt den Hoechstwert von 100."""
    assert kpi.herfindahl(pd.Series([42.0])) == pytest.approx(100.0)


def test_herfindahl_steigt_mit_der_konzentration() -> None:
    breit = pd.Series([10.0] * 10)
    eng = pd.Series([60.0, 20.0, 10.0, 5.0, 5.0])
    assert kpi.herfindahl(eng) > kpi.herfindahl(breit)


def test_herfindahl_bei_leerer_reihe() -> None:
    assert kpi.herfindahl(pd.Series([], dtype=float)) == 0.0
    assert kpi.herfindahl(pd.Series([0.0, 0.0])) == 0.0


# --------------------------------------------------------------------------
# OLAP
# --------------------------------------------------------------------------

@pytest.fixture
def wuerfel() -> pd.DataFrame:
    """Kleiner, vollstaendiger Wuerfel fuer die Operationen."""
    return olap._zeitachse_ordnen(pd.DataFrame([
        {"anzeigename": "Garchomp", "spezies": "garchomp", "generation": 4,
         "typ1": "Dragon", "typ_kombination": "Dragon / Ground",
         "rolle": "Schneller Sweeper", "offensiv_profil": "Physisch",
         "speed_klasse": "Schnell (100-119)",
         "datum_iso": "2026-07-27", "tag_label": "27.07.2026",
         "monat_iso": "2026-07", "monat_name": "Juli 2026",
         "quartal_label": "Q3 2026", "jahr": 2026,
         "saison": "M4", "kampfformat": "Doubles",
         "rang": 2, "rang_perzentil": 99.0, "erfasste_pokemon": 200,
         "basiswert_summe": 600, "stufe50_speed": 122, "resistenz_wert": 1.0},
        {"anzeigename": "Garchomp", "spezies": "garchomp", "generation": 4,
         "typ1": "Dragon", "typ_kombination": "Dragon / Ground",
         "rolle": "Schneller Sweeper", "offensiv_profil": "Physisch",
         "speed_klasse": "Schnell (100-119)",
         "datum_iso": "2026-07-28", "tag_label": "28.07.2026",
         "monat_iso": "2026-07", "monat_name": "Juli 2026",
         "quartal_label": "Q3 2026", "jahr": 2026,
         "saison": "M4", "kampfformat": "Doubles",
         "rang": 1, "rang_perzentil": 100.0, "erfasste_pokemon": 200,
         "basiswert_summe": 600, "stufe50_speed": 122, "resistenz_wert": 1.0},
        {"anzeigename": "Incineroar", "spezies": "incineroar", "generation": 7,
         "typ1": "Fire", "typ_kombination": "Fire / Dark",
         "rolle": "Bulky Offense", "offensiv_profil": "Physisch",
         "speed_klasse": "Langsam (60-79)",
         "datum_iso": "2026-07-28", "tag_label": "28.07.2026",
         "monat_iso": "2026-07", "monat_name": "Juli 2026",
         "quartal_label": "Q3 2026", "jahr": 2026,
         "saison": "M4", "kampfformat": "Doubles",
         "rang": 2, "rang_perzentil": 99.5, "erfasste_pokemon": 200,
         "basiswert_summe": 530, "stufe50_speed": 80, "resistenz_wert": 2.0},
    ]))


def test_slice_filtert_eine_dimension(wuerfel) -> None:
    ergebnis = olap.slice_wuerfel(wuerfel, "tag_label", ["28.07.2026"])
    assert len(ergebnis) == 2


def test_dice_filtert_mehrere_dimensionen(wuerfel) -> None:
    ergebnis = olap.dice_wuerfel(
        wuerfel, {"tag_label": ["28.07.2026"], "typ1": ["Fire"]})
    assert len(ergebnis) == 1
    assert ergebnis.iloc[0]["anzeigename"] == "Incineroar"


def test_slice_ohne_werte_laesst_wuerfel_unveraendert(wuerfel) -> None:
    assert len(olap.slice_wuerfel(wuerfel, "tag_label", [])) == len(wuerfel)


def test_drill_down_und_roll_up_folgen_der_hierarchie() -> None:
    # Die Pokemon-Hierarchie hat zwei Stufen. Eine Zwischenebene fuer die
    # Spezies waere fast ueberall deckungsgleich mit der Form.
    assert olap.naechste_ebene("generation", "drill_down") == "anzeigename"
    assert olap.naechste_ebene("anzeigename", "roll_up") == "generation"
    # Die Zeitdimension reicht bis auf Tagesebene hinunter.
    assert olap.naechste_ebene("monat_name", "drill_down") == "tag_label"
    assert olap.naechste_ebene("tag_label", "roll_up") == "monat_name"


def test_pokemon_hierarchie_zeigt_lesbare_namen() -> None:
    """Die Auswertungsebene darf nicht den technischen Bezeichner ausgeben.

    ``spezies`` enthaelt den Slug in Kleinschreibung (``aegislash``),
    ``anzeigename`` den lesbaren Namen (``Aegislash Shield``).
    """
    schluessel = [m.schluessel for m in olap.HIERARCHIEN["Pokemon"]]
    assert "spezies" not in schluessel
    assert "anzeigename" in schluessel


def test_hierarchie_endet_an_den_raendern() -> None:
    assert olap.naechste_ebene("anzeigename", "drill_down") is None
    assert olap.naechste_ebene("generation", "roll_up") is None
    assert olap.naechste_ebene("tag_label", "drill_down") is None
    assert olap.naechste_ebene("gibtesnicht", "drill_down") is None


def test_zeitachse_ist_chronologisch(wuerfel) -> None:
    """Tage duerfen nicht alphabetisch sortiert werden."""
    tabelle = olap.verdichte(wuerfel, "anzeigename", "rang_bester", "tag_label")
    assert list(tabelle.columns) == ["27.07.2026", "28.07.2026"]


def test_pivot_vertauscht_die_achsen(wuerfel) -> None:
    a = olap.verdichte(wuerfel, "anzeigename", "rang_bester", "tag_label")
    b = olap.verdichte(wuerfel, "tag_label", "rang_bester", "anzeigename")
    assert list(a.index) == list(b.columns)
    assert list(a.columns) == list(b.index)


def test_keine_summenkennzahl_auf_raengen() -> None:
    """Raenge sind ordinal -- eine Summe waere fachlich nicht belastbar.

    Der Katalog darf deshalb keine Kennzahl mit Summenaggregation ueber den Rang
    anbieten.
    """
    for kennzahl in olap.KENNZAHLEN.values():
        if kennzahl.schluessel in ("rang", "rang_perzentil"):
            assert kennzahl.aggregation in ("min", "max", "median"), (
                f"{kennzahl.bezeichnung} verwendet {kennzahl.aggregation} auf einem Rang"
            )


def test_bester_rang_ist_das_minimum(wuerfel) -> None:
    """Ein kleinerer Rang ist besser -- die Verdichtung muss das abbilden."""
    ergebnis = olap.verdichte(wuerfel, "anzeigename", "rang_bester")
    garchomp = ergebnis[ergebnis["anzeigename"] == "Garchomp"]["Bester Rang"].iloc[0]
    assert garchomp == 1


def test_anzahl_zaehlt_eindeutige_pokemon(wuerfel) -> None:
    ergebnis = olap.verdichte(wuerfel, "generation", "anzahl")
    assert ergebnis["Anzahl Pokemon"].sum() == 2


def test_wuerfel_kennzahlen(wuerfel) -> None:
    werte = olap.wuerfel_kennzahlen(wuerfel)
    assert werte["zeilen"] == 3
    assert werte["pokemon"] == 2
    assert werte["tage"] == 2
    assert werte["bester_rang"] == 1


def test_leerer_wuerfel_bleibt_stabil() -> None:
    werte = olap.wuerfel_kennzahlen(pd.DataFrame())
    assert werte["zeilen"] == 0
    assert olap.verdichte(pd.DataFrame(), "anzeigename", "anzahl").empty


# --------------------------------------------------------------------------
# Bedrohungsanalyse
# --------------------------------------------------------------------------

@pytest.fixture
def team() -> pd.DataFrame:
    return pd.DataFrame([
        {"anzeigename": "Rillaboom", "typ1": "Grass", "typ2": None, "speed": 85},
        {"anzeigename": "Amoonguss", "typ1": "Grass", "typ2": "Poison", "speed": 30},
    ])


def test_defensivprofil_zaehlt_anfaelligkeiten(team) -> None:
    profil = threat.team_defensivprofil(team)
    feuer = profil[profil["angriffstyp"] == "Fire"].iloc[0]

    assert feuer["anfaellig"] == 2
    assert feuer["resistent"] == 0
    assert feuer["bewertung"].startswith(("Kritisch", "Warnung"))


def test_defensivprofil_erkennt_deckung() -> None:
    """Ein resistentes Mitglied entschaerft die Schwaeche eines anderen."""
    gemischt = pd.DataFrame([
        {"anzeigename": "Rillaboom", "typ1": "Grass", "typ2": None, "speed": 85},
        {"anzeigename": "Incineroar", "typ1": "Fire", "typ2": "Dark", "speed": 60},
    ])
    profil = threat.team_defensivprofil(gemischt)
    feuer = profil[profil["angriffstyp"] == "Fire"].iloc[0]

    assert feuer["anfaellig"] == 1
    assert feuer["resistent"] == 1
    assert feuer["risiko"] == 0.0, "Eine gedeckte Schwaeche darf kein Risiko ausweisen."


def test_risiko_beruecksichtigt_meta_praesenz(team) -> None:
    """Dieselbe Schwaeche wiegt schwerer, wenn der Angriffstyp haeufig ist."""
    selten = pd.DataFrame({"angriffstyp": ["Fire"], "anteil_prozent": [1.0]})
    haeufig = pd.DataFrame({"angriffstyp": ["Fire"], "anteil_prozent": [20.0]})

    wert_selten = threat.team_defensivprofil(team, selten).query(
        "angriffstyp == 'Fire'")["risiko"].iloc[0]
    wert_haeufig = threat.team_defensivprofil(team, haeufig).query(
        "angriffstyp == 'Fire'")["risiko"].iloc[0]
    assert wert_haeufig > wert_selten


def test_immunitaet_wird_als_deckung_gewertet() -> None:
    fliegend = pd.DataFrame([
        {"anzeigename": "Tornadus", "typ1": "Flying", "typ2": None, "speed": 111},
    ])
    boden = threat.team_defensivprofil(fliegend).query("angriffstyp == 'Ground'").iloc[0]

    assert boden["immun"] == 1
    assert boden["anfaellig"] == 0
    assert boden["risiko"] == 0.0


def test_defensivprofil_bei_leerem_team() -> None:
    ergebnis = threat.team_defensivprofil(pd.DataFrame())
    assert ergebnis.empty
    assert "risiko" in ergebnis.columns, "Auch leer muss die Struktur stimmen."


# --------------------------------------------------------------------------
# Richtung der Kennzahlen
# --------------------------------------------------------------------------

def _rangwuerfel() -> pd.DataFrame:
    """Zwei starke und ein schwaches Pokemon ueber zwei Tage.

    Watchog ist an beiden Tagen platziert und hat damit die groesste
    Rangsumme -- eine Auswahl ueber die Summe wuerde ausgerechnet dieses
    Pokemon als "Top" ausweisen.
    """
    saetze = []
    for name, raenge in (("Garchomp", (2, 1)), ("Incineroar", (5, 4)),
                         ("Watchog", (229, 230))):
        for tag, rang in zip(("27.07.2026", "28.07.2026"), raenge, strict=True):
            saetze.append({
                "anzeigename": name, "tag_label": tag, "typ1": "Normal",
                "datum_iso": f"2026-07-{tag[:2]}", "monat_iso": "2026-07",
                "monat_name": "Juli 2026", "quartal_label": "Q3 2026", "jahr": 2026,
                "rang": rang, "rang_perzentil": 100.0 - rang / 3,
            })
    return olap._zeitachse_ordnen(pd.DataFrame(saetze))


def test_bestenliste_waehlt_die_besten_und_nicht_die_schwaechsten() -> None:
    """Bei einem Rang ist 1 das beste Ergebnis, nicht das hoechste.

    Zuvor waehlte die Begrenzung die Zeilen mit der groessten Rangsumme aus.
    Das traf genau die Pokemon, die niemand spielt -- Garchomp auf Rang 1 fiel
    aus der Darstellung heraus, waehrend Watchog auf Rang 229 sie anfuehrte.
    """
    tabelle = olap.verdichte(_rangwuerfel(), "anzeigename", "rang_bester", "tag_label")

    beste = olap.beste_auspraegungen(tabelle, "rang_bester", 2)

    assert list(beste.index) == ["Garchomp", "Incineroar"]
    assert "Watchog" not in beste.index


def test_bestenliste_ohne_begrenzung_liefert_alles_geordnet() -> None:
    tabelle = olap.verdichte(_rangwuerfel(), "anzeigename", "rang_bester", "tag_label")

    alle = olap.beste_auspraegungen(tabelle, "rang_bester")

    assert list(alle.index) == ["Garchomp", "Incineroar", "Watchog"]
    assert len(alle) == len(tabelle)


def test_bestenliste_dreht_die_richtung_bei_groesser_ist_besser() -> None:
    """Das Rangperzentil ist auf 100 normiert -- dort ist gross gut."""
    tabelle = olap.verdichte(_rangwuerfel(), "anzeigename", "rang_perzentil", "tag_label")

    assert olap.beste_auspraegungen(tabelle, "rang_perzentil", 1).index[0] == "Garchomp"


def test_ranglueckenwerden_nicht_mit_null_gefuellt(wuerfel) -> None:
    """Ein Rang 0 existiert nicht und laese sich als besser denn Rang 1 lesen.

    Incineroar ist am 27.07. nicht platziert. Die Zelle muss leer bleiben.
    """
    tabelle = olap.verdichte(wuerfel, "anzeigename", "rang_bester", "tag_label")

    assert pd.isna(tabelle.loc["Incineroar", "27.07.2026"])
    assert (tabelle == 0).sum().sum() == 0


def test_zaehlung_fuellt_luecken_weiterhin_mit_null(wuerfel) -> None:
    """Bei einer Zaehlung bedeutet "nicht vorhanden" tatsaechlich null."""
    tabelle = olap.verdichte(wuerfel, "typ1", "anzahl", "tag_label")

    assert tabelle.loc["Fire", "27.07.2026"] == 0
    assert not tabelle.isna().any().any()


def test_einachsige_auswertung_beginnt_beim_besten() -> None:
    ergebnis = olap.kennzahl_mit_anteil(_rangwuerfel(), "anzeigename", "rang_bester")

    assert ergebnis.iloc[0]["anzeigename"] == "Garchomp"
    assert ergebnis.iloc[-1]["anzeigename"] == "Watchog"


def test_kein_anteil_auf_raengen() -> None:
    """Ein Prozentwert setzt voraus, dass die Summe etwas bedeutet.

    Die Summe aller Raenge tut das nicht -- ein daraus gebildeter Anteil
    taeuschte eine Verhaeltnisskala vor, die die Quelle nicht liefert.
    """
    ergebnis = olap.kennzahl_mit_anteil(_rangwuerfel(), "anzeigename", "rang_bester")

    assert "anteil_prozent" not in ergebnis.columns
    assert "kumuliert_prozent" not in ergebnis.columns


def test_anteil_bleibt_bei_zaehlgroessen_erhalten(wuerfel) -> None:
    """Anzahlen sind kardinal -- dort ist der Anteil zulaessig und nuetzlich."""
    ergebnis = olap.kennzahl_mit_anteil(wuerfel, "typ1", "anzahl")

    assert "anteil_prozent" in ergebnis.columns
    assert ergebnis["anteil_prozent"].sum() == pytest.approx(100.0, abs=0.2)


def test_jede_kennzahl_erklaert_ihre_richtung() -> None:
    """Ohne diese Angabe waehlte eine Bestenliste die schwaechsten Werte aus."""
    for schluessel, kennzahl in olap.KENNZAHLEN.items():
        assert isinstance(kennzahl.kleiner_ist_besser, bool), schluessel
        # Ein Anteil ist nur ueber additiven Groessen sinnvoll.
        if kennzahl.anteil_zulaessig:
            assert kennzahl.aggregation in ("nunique", "count", "sum"), schluessel


def test_achse_und_kennzahl_duerfen_dieselbe_spalte_sein(wuerfel) -> None:
    """"Anzahl Pokemon" je Pokemon zaehlt und gruppiert ueber dieselbe Spalte.

    pandas kann eine Spalte nicht zugleich als Gruppierung und als Wert
    verwenden; die Auswahl fuehrte deshalb zu einem Abbruch der Seite.
    """
    einachsig = olap.kennzahl_mit_anteil(wuerfel, "anzeigename", "anzahl")
    assert list(einachsig["anzeigename"]) == ["Garchomp", "Incineroar"]

    zweiachsig = olap.verdichte(wuerfel, "anzeigename", "anzahl", "tag_label")
    assert zweiachsig.loc["Garchomp", "27.07.2026"] == 1
    assert zweiachsig.loc["Incineroar", "27.07.2026"] == 0

    schlicht = olap.verdichte(wuerfel, "anzeigename", "anzahl")
    assert set(schlicht.columns) == {"anzeigename", "Anzahl Pokemon"}


def test_jede_achsen_und_kennzahlkombination_ist_lauffaehig(wuerfel) -> None:
    """Der Explorer laesst jede Kombination zu -- keine darf abbrechen."""
    merkmale = list(olap.ALLE_MERKMALE)
    for zeile in merkmale:
        for spalte in [None, *merkmale]:
            if spalte == zeile:
                continue
            for kennzahl in olap.KENNZAHLEN:
                tabelle = olap.verdichte(wuerfel, zeile, kennzahl, spalte)
                if spalte:
                    olap.beste_auspraegungen(tabelle, kennzahl, 5)
                else:
                    olap.kennzahl_mit_anteil(wuerfel, zeile, kennzahl)

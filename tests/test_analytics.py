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
    assert olap.naechste_ebene("generation", "drill_down") == "spezies"
    assert olap.naechste_ebene("spezies", "drill_down") == "anzeigename"
    assert olap.naechste_ebene("anzeigename", "roll_up") == "spezies"
    # Die Zeitdimension reicht jetzt bis auf Tagesebene hinunter.
    assert olap.naechste_ebene("monat_name", "drill_down") == "tag_label"
    assert olap.naechste_ebene("tag_label", "roll_up") == "monat_name"


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

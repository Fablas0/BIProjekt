"""Tests der Analyseschicht: Kennzahlen, OLAP-Operationen und Bedrohungsanalyse."""

from __future__ import annotations

import pandas as pd
import pytest

from bi.analytics import kpi, olap, threat

# --------------------------------------------------------------------------
# Kennzahlen
# --------------------------------------------------------------------------

def test_herfindahl_bei_gleichverteilung() -> None:
    """Bei n gleich grossen Anteilen betraegt der normierte Index 100/n."""
    gleich = pd.Series([10.0] * 10)
    assert kpi.herfindahl(gleich) == pytest.approx(10.0)


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
        {"anzeigename": "Incineroar", "spezies": "incineroar", "generation": 7,
         "typ1": "Fire", "typ_kombination": "Fire / Dark", "rolle": "Bulky Offense",
         "offensiv_profil": "Physisch", "speed_klasse": "Langsam (60-79)",
         "monat_iso": "2026-05", "monat_name": "Mai 2026", "quartal_label": "Q2 2026",
         "jahr": 2026, "saison": "VGC 2026", "regulation": "Reg I", "spielmodus": "Bo1",
         "usage_rate": 40.0, "raw_count": 100, "gxe_top": 86.0, "gxe_p50": 60.0,
         "basiswert_summe": 530, "speed": 60, "resistenz_wert": 2.0},
        {"anzeigename": "Incineroar", "spezies": "incineroar", "generation": 7,
         "typ1": "Fire", "typ_kombination": "Fire / Dark", "rolle": "Bulky Offense",
         "offensiv_profil": "Physisch", "speed_klasse": "Langsam (60-79)",
         "monat_iso": "2026-06", "monat_name": "Juni 2026", "quartal_label": "Q2 2026",
         "jahr": 2026, "saison": "VGC 2026", "regulation": "Reg I", "spielmodus": "Bo1",
         "usage_rate": 50.0, "raw_count": 120, "gxe_top": 88.0, "gxe_p50": 62.0,
         "basiswert_summe": 530, "speed": 60, "resistenz_wert": 2.0},
        {"anzeigename": "Miraidon", "spezies": "miraidon", "generation": 9,
         "typ1": "Electric", "typ_kombination": "Electric / Dragon",
         "rolle": "Schneller Sweeper", "offensiv_profil": "Speziell",
         "speed_klasse": "Schnell (100-119)",
         "monat_iso": "2026-06", "monat_name": "Juni 2026", "quartal_label": "Q2 2026",
         "jahr": 2026, "saison": "VGC 2026", "regulation": "Reg I", "spielmodus": "Bo1",
         "usage_rate": 30.0, "raw_count": 90, "gxe_top": 86.0, "gxe_p50": 61.0,
         "basiswert_summe": 670, "speed": 135, "resistenz_wert": 1.0},
    ]))


def test_slice_filtert_eine_dimension(wuerfel) -> None:
    ergebnis = olap.slice_wuerfel(wuerfel, "monat_name", ["Juni 2026"])
    assert len(ergebnis) == 2
    assert set(ergebnis["monat_name"]) == {"Juni 2026"}


def test_dice_filtert_mehrere_dimensionen(wuerfel) -> None:
    ergebnis = olap.dice_wuerfel(wuerfel, {"monat_name": ["Juni 2026"], "typ1": ["Fire"]})
    assert len(ergebnis) == 1
    assert ergebnis.iloc[0]["anzeigename"] == "Incineroar"


def test_slice_ohne_werte_laesst_wuerfel_unveraendert(wuerfel) -> None:
    assert len(olap.slice_wuerfel(wuerfel, "monat_name", [])) == len(wuerfel)


def test_drill_down_und_roll_up_folgen_der_hierarchie() -> None:
    assert olap.naechste_ebene("generation", "drill_down") == "spezies"
    assert olap.naechste_ebene("spezies", "drill_down") == "anzeigename"
    assert olap.naechste_ebene("anzeigename", "roll_up") == "spezies"
    assert olap.naechste_ebene("jahr", "drill_down") == "quartal_label"


def test_hierarchie_endet_an_den_raendern() -> None:
    """Am Ende eines Konsolidierungspfades gibt es keinen naechsten Schritt."""
    assert olap.naechste_ebene("anzeigename", "drill_down") is None
    assert olap.naechste_ebene("generation", "roll_up") is None
    assert olap.naechste_ebene("gibtesnicht", "drill_down") is None


def test_roll_up_verdichtet_die_kennzahl(wuerfel) -> None:
    """Auf groeberer Ebene muessen die Werte zusammengefasst werden."""
    fein = olap.verdichte(wuerfel, "anzeigename", "usage_rate")
    grob = olap.verdichte(wuerfel, "generation", "usage_rate")

    assert len(fein) == 2
    assert len(grob) == 2
    # Die Gesamtsumme bleibt bei einer reinen Verdichtung erhalten.
    assert fein["Nutzungsanteil (Summe)"].sum() == pytest.approx(
        grob["Nutzungsanteil (Summe)"].sum())


def test_pivot_vertauscht_die_achsen(wuerfel) -> None:
    a = olap.verdichte(wuerfel, "anzeigename", "usage_rate", "monat_name")
    b = olap.verdichte(wuerfel, "monat_name", "usage_rate", "anzeigename")
    assert list(a.index) == list(b.columns)
    assert list(a.columns) == list(b.index)


def test_zeitachse_ist_chronologisch(wuerfel) -> None:
    """Monate duerfen nicht alphabetisch sortiert werden."""
    tabelle = olap.verdichte(wuerfel, "anzeigename", "usage_rate", "monat_name")
    assert list(tabelle.columns) == ["Mai 2026", "Juni 2026"]


def test_aggregationsregel_gehoert_zur_kennzahl(wuerfel) -> None:
    """Nutzungsanteile werden summiert, GXE-Werte nicht."""
    summe = olap.verdichte(wuerfel, "generation", "usage_rate")
    maximum = olap.verdichte(wuerfel, "generation", "gxe_top")

    gen7_summe = summe[summe["generation"] == 7]["Nutzungsanteil (Summe)"].iloc[0]
    gen7_max = maximum[maximum["generation"] == 7]["Bestes GXE"].iloc[0]

    assert gen7_summe == pytest.approx(90.0)   # 40 + 50
    assert gen7_max == pytest.approx(88.0)     # Maximum, nicht 174


def test_kennzahl_mit_kumuliertem_anteil(wuerfel) -> None:
    ergebnis = olap.kennzahl_mit_anteil(wuerfel, "anzeigename")
    assert list(ergebnis["anzeigename"]) == ["Incineroar", "Miraidon"]
    assert ergebnis["anteil_prozent"].sum() == pytest.approx(100.0, abs=0.1)
    assert ergebnis["kumuliert_prozent"].iloc[-1] == pytest.approx(100.0, abs=0.1)


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

    # Beide Mitglieder sind Pflanze und damit gegen Feuer anfaellig.
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


def test_risiko_beruecksichtigt_meta_haeufigkeit(team) -> None:
    """Dieselbe Schwaeche wiegt schwerer, wenn der Angriffstyp haeufig ist."""
    selten = pd.DataFrame({"angriffstyp": ["Fire"], "anteil_prozent": [1.0]})
    haeufig = pd.DataFrame({"angriffstyp": ["Fire"], "anteil_prozent": [20.0]})

    risiko_selten = threat.team_defensivprofil(team, selten)
    risiko_haeufig = threat.team_defensivprofil(team, haeufig)

    wert_selten = risiko_selten[risiko_selten["angriffstyp"] == "Fire"]["risiko"].iloc[0]
    wert_haeufig = risiko_haeufig[risiko_haeufig["angriffstyp"] == "Fire"]["risiko"].iloc[0]
    assert wert_haeufig > wert_selten


def test_defensivprofil_bei_leerem_team() -> None:
    ergebnis = threat.team_defensivprofil(pd.DataFrame())
    assert ergebnis.empty
    assert "risiko" in ergebnis.columns, "Auch leer muss die Struktur stimmen."


def test_immunitaet_wird_als_deckung_gewertet() -> None:
    fliegend = pd.DataFrame([
        {"anzeigename": "Tornadus", "typ1": "Flying", "typ2": None, "speed": 111},
    ])
    profil = threat.team_defensivprofil(fliegend)
    boden = profil[profil["angriffstyp"] == "Ground"].iloc[0]

    assert boden["immun"] == 1
    assert boden["anfaellig"] == 0
    assert boden["risiko"] == 0.0

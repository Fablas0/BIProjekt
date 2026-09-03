"""Tests der Shiny-Jagd: Regelbasis, Statistik und Datenhaltung.

Die Regelbasis wird gegen die in der Gemeinde bekannten Zahlen geprueft
(Masuda 1 zu 683, Schillerpin 1 zu 1365) -- sie sind das Ergebnis der
Wurfrechnung, und ein Tippfehler in der Wurfzahl faellt genau dort auf.
"""

from __future__ import annotations

import math

import pytest

from bi import nutzerdaten, shiny, warehouse


@pytest.fixture
def conn(tmp_path):
    verbindung = warehouse.verbindung(str(tmp_path / "dwh.db"))
    nutzerdaten.anhaengen(verbindung, tmp_path / "nutzer.db")
    yield verbindung
    verbindung.close()


# --------------------------------------------------------------------------
# Regelbasis
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("methode", "nenner"), [
    ("gen6_voll", 4096),
    ("gen2_voll", 8192),
    ("gen6_pin", 1365.67),
    ("gen6_masuda", 683.08),
    ("gen6_masuda_pin", 512.25),
    ("gen5_masuda", 1365.83),
    ("go_wild", 512),
])
def test_bekannte_wahrscheinlichkeiten(methode: str, nenner: float) -> None:
    """Die Wurfrechnung muss die gelaeufigen Angaben reproduzieren."""
    assert shiny.METHODEN[methode].nenner == pytest.approx(nenner, rel=1e-3)


def test_jede_methode_ist_vollstaendig() -> None:
    for schluessel, methode in shiny.METHODEN.items():
        assert methode.schluessel == schluessel
        assert 0 < methode.wahrscheinlichkeit < 1
        assert methode.spiel in shiny.SPIELE
        assert methode.einheit.endswith(("en", "er", "e", "s"))


def test_mehr_wuerfe_bedeuten_bessere_chance() -> None:
    """Die Ordnung der Methoden ist eine fachliche Zusage."""
    p = {k: m.wahrscheinlichkeit for k, m in shiny.METHODEN.items()}
    assert p["gen6_voll"] < p["gen6_pin"] < p["gen6_masuda"] < p["gen6_masuda_pin"]
    assert p["gen2_voll"] < p["gen6_voll"]


# --------------------------------------------------------------------------
# Statistik
# --------------------------------------------------------------------------

def test_erwartungswert_und_median() -> None:
    p = 1 / 4096
    assert shiny.erwartungswert(p) == 4096
    # Der Median der geometrischen Verteilung liegt bei ln(2)/p, also rund 69 %.
    assert shiny.median_versuche(p) == pytest.approx(4096 * math.log(2), abs=2)


def test_kumulierte_wahrscheinlichkeit_am_erwartungswert() -> None:
    """Nach dem Erwartungswert sind rund 63 Prozent fuendig -- 1 - 1/e."""
    p = 1 / 4096
    assert shiny.kumuliert(p, 4096) == pytest.approx(1 - math.exp(-1), abs=1e-3)
    assert shiny.kumuliert(p, 0) == 0.0


def test_versuche_fuer_sicherheit() -> None:
    p = 1 / 4096
    n = shiny.versuche_fuer(p, 0.99)
    assert shiny.kumuliert(p, n) >= 0.99
    assert shiny.kumuliert(p, n - 1) < 0.99
    with pytest.raises(ValueError):
        shiny.versuche_fuer(p, 1.0)


def test_einordnung_stuft_nach_anteil() -> None:
    methode = shiny.METHODEN["gen6_voll"]
    assert shiny.einordnen(methode, 100).stufe == "frueh"
    assert shiny.einordnen(methode, 6000).stufe == "geduldig"
    assert shiny.einordnen(methode, 20000).stufe == "pech"
    assert shiny.einordnen(methode, 100, gefunden=True).stufe == "glueck"
    assert shiny.einordnen(methode, 3000, gefunden=True).stufe == "ueblich"
    assert shiny.einordnen(methode, 20000, gefunden=True).stufe == "pech"


def test_verteilung_endet_bei_99_prozent() -> None:
    punkte = shiny.verteilung(1 / 4096)
    assert punkte[0] == (0, 0.0)
    assert punkte[-1][1] >= 0.99
    assert all(a <= b for (_, a), (_, b) in zip(punkte, punkte[1:], strict=False))


# --------------------------------------------------------------------------
# Datenhaltung
# --------------------------------------------------------------------------

def test_jagd_zaehlen_und_abschliessen(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    jagd_id = shiny.jagd_anlegen(conn, nutzer.nutzer_id, "garchomp", "gen6_masuda")

    assert shiny.jagd_zaehlen(conn, nutzer.nutzer_id, jagd_id, 10) == 10
    assert shiny.jagd_zaehlen(conn, nutzer.nutzer_id, jagd_id, -20) == 0, "nie negativ"
    shiny.jagd_setzen(conn, nutzer.nutzer_id, jagd_id, 700)

    jagd = shiny.jagden_lesen(conn, nutzer.nutzer_id)[0]
    assert jagd["versuche"] == 700
    assert jagd["einheit"] == "Eier"
    assert jagd["einordnung"].stufe == "geduldig"

    shiny.jagd_abschliessen(conn, nutzer.nutzer_id, jagd_id, gefunden=True)
    jagd = shiny.jagden_lesen(conn, nutzer.nutzer_id)[0]
    assert jagd["status"] == "gefunden"
    assert jagd["beendet_am"]
    with pytest.raises(ValueError, match="abgeschlossen"):
        shiny.jagd_zaehlen(conn, nutzer.nutzer_id, jagd_id)


def test_unbekannte_methode_wird_abgelehnt(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    with pytest.raises(ValueError, match="Unbekannte Jagdmethode"):
        shiny.jagd_anlegen(conn, nutzer.nutzer_id, "garchomp", "wuenschelrute")


def test_jagden_sind_je_nutzer_getrennt(conn) -> None:
    a = nutzerdaten.anlegen(conn, "a", "sicheres-passwort")
    b = nutzerdaten.anlegen(conn, "b", "sicheres-passwort")
    jagd_id = shiny.jagd_anlegen(conn, a.nutzer_id, "garchomp", "gen6_voll")
    assert shiny.jagden_lesen(conn, b.nutzer_id) == []
    with pytest.raises(ValueError, match="nicht gefunden"):
        shiny.jagd_zaehlen(conn, b.nutzer_id, jagd_id)


def test_bilanz_mittelt_die_anteile_gefundener_jagden(conn) -> None:
    nutzer = nutzerdaten.anlegen(conn, "fabian", "sicheres-passwort")
    frueh = shiny.jagd_anlegen(conn, nutzer.nutzer_id, "garchomp", "gen6_voll", versuche=10)
    shiny.jagd_abschliessen(conn, nutzer.nutzer_id, frueh, gefunden=True)
    shiny.jagd_anlegen(conn, nutzer.nutzer_id, "pikachu", "gen6_voll", versuche=500)

    bilanz = shiny.bilanz(shiny.jagden_lesen(conn, nutzer.nutzer_id))
    assert bilanz == {
        "jagden": 2, "laufend": 1, "gefunden": 1, "versuche_gesamt": 510,
        "glueckswert": pytest.approx(shiny.kumuliert(1 / 4096, 10)),
    }

"""Tests der Spielweisen: die Gliederung der Navigation.

Die Spielweisen sind eine Zusage an die Bedienung: jede fuehrt nur Seiten, die
es gibt, und jede Seite der Anwendung ist ueber mindestens eine Spielweise
erreichbar -- sonst gaebe es eine Seite, die niemand findet.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bi.ui import spielweisen

WURZEL = Path(__file__).resolve().parents[1]


def _seiten_der_anwendung() -> dict:
    sys.path.insert(0, str(WURZEL))
    import app

    return app.SEITEN


def test_jede_spielweise_fuehrt_nur_bekannte_seiten() -> None:
    seiten = _seiten_der_anwendung()
    for spielweise in spielweisen.SPIELWEISEN.values():
        unbekannt = [s for s in spielweise.seiten if s not in seiten]
        assert not unbekannt, f"{spielweise.name} fuehrt unbekannte Seiten: {unbekannt}"
        assert spielweise.startseite in seiten
        assert spielweise.frage.endswith("?")


def test_jede_seite_ist_erreichbar() -> None:
    """Keine Seite ohne Spielweise -- ausser dem Start und dem Betrieb."""
    seiten = set(_seiten_der_anwendung()) - {"Start"}
    erreichbar = set(spielweisen.alle_seiten())
    assert seiten <= erreichbar, f"Unerreichbar: {sorted(seiten - erreichbar)}"


def test_spielweise_fuer_seite() -> None:
    assert spielweisen.spielweise_fuer_seite("Meta-Cockpit") == "champions"
    assert spielweisen.spielweise_fuer_seite("Shiny-Jagd") == "sammeln"
    assert spielweisen.spielweise_fuer_seite("Nuzlocke-Lauf") == "nuzlocke"
    assert spielweisen.spielweise_fuer_seite("GO-Meta") == "go"
    assert spielweisen.spielweise_fuer_seite("Gibt es nicht") == spielweisen.STANDARD


def test_pc_system_steht_in_jeder_spielweise() -> None:
    """Die Box ist der gemeinsame Bestand -- sie muss von ueberall erreichbar sein,
    wo eigene Pokemon vorkommen."""
    for schluessel in ("champions", "go", "nuzlocke", "durchspielen", "sammeln"):
        assert "PC-System" in spielweisen.SPIELWEISEN[schluessel].seiten

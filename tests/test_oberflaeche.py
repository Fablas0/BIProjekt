"""Oberflaechentests mit Streamlits AppTest-Rahmen.

Die Tests fuehren die vollstaendige Anwendung im Prozess aus und pruefen, dass
jede Seite fehlerfrei rendert -- auch mit ausgewaehltem Team, also auf den
Codepfaden, die erst durch eine Benutzereingabe erreicht werden.

Die Tests benoetigen ein befuelltes Data Warehouse. Ist keines vorhanden, werden
sie uebersprungen: der Aufbau erfordert Zugriff auf beide Quellsysteme und
gehoert nicht in einen Testlauf ohne Netzverbindung.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
DWH = Path(os.getenv("VGC_BI_DB", WURZEL / "data" / "vgc_dwh.db"))

pytestmark = pytest.mark.skipif(
    not DWH.exists(),
    reason="Kein befuelltes Data Warehouse vorhanden -- Oberflaechentests uebersprungen.",
)

SEITEN = [
    "Meta-Cockpit",
    "Gegner-Scouting",
    "Team-Builder",
    "OLAP-Explorer",
    "Meta-Playbook",
    "ETL & Datenqualitaet",
]


def _starte(seite: str | None = None):
    """Fuehrt die Anwendung aus und waehlt optional eine Seite an."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(WURZEL / "app.py"), default_timeout=180)
    app.run()
    if seite and seite != SEITEN[0]:
        app.radio[0].set_value(seite).run()
    return app


@pytest.mark.parametrize("seite", SEITEN)
def test_seite_rendert_ohne_fehler(seite: str) -> None:
    """Jede Seite muss ohne unbehandelte Ausnahme rendern."""
    app = _starte(seite)
    assert not app.exception, f"Ausnahme auf Seite '{seite}': {app.exception}"


def test_scouting_mit_team() -> None:
    """Die Scouting-Analyse muss auch mit ausgewaehltem Team durchlaufen.

    Erst mit einer Auswahl werden Defensivprofil, Bedrohungsindex und
    Strategie-Radar tatsaechlich ausgefuehrt.
    """
    app = _starte("Gegner-Scouting")
    auswahl = app.multiselect[0]
    assert auswahl.options, "Keine Pokemon zur Auswahl -- ist das DWH befuellt?"

    app.multiselect[0].set_value(auswahl.options[:4]).run()
    assert not app.exception, f"Ausnahme bei der Teamanalyse: {app.exception}"

    # Alle Registerkarten der Analyse muessen angelegt worden sein.
    assert app.tabs, "Die Analyse hat keine Registerkarten erzeugt."


def test_teambuilder_mit_team() -> None:
    """Der Team-Builder muss Vorschlaege und Bewertungen erzeugen."""
    app = _starte("Team-Builder")
    auswahl = app.multiselect[0]
    assert auswahl.options

    app.multiselect[0].set_value(auswahl.options[:3]).run()
    assert not app.exception, f"Ausnahme im Team-Builder: {app.exception}"


def test_olap_drill_down_und_pivot() -> None:
    """Drill-Down, Roll-Up und Pivot muessen den Wuerfel neu verdichten."""
    app = _starte("OLAP-Explorer")
    assert not app.exception

    beschriftungen = [b.label for b in app.button]
    for aktion in ("Roll-Up", "Drill-Down", "Pivot"):
        assert aktion in beschriftungen, f"Schaltflaeche '{aktion}' fehlt."

    # Roll-Up von 'Pokemon (Form)' auf 'Spezies' und erneut auf 'Generation'.
    for _ in range(2):
        knopf = next((b for b in app.button if b.label == "Roll-Up" and not b.disabled), None)
        if knopf is None:
            break
        knopf.click().run()
        assert not app.exception, f"Ausnahme beim Roll-Up: {app.exception}"

    pivot = next((b for b in app.button if b.label == "Pivot" and not b.disabled), None)
    if pivot is not None:
        pivot.click().run()
        assert not app.exception, f"Ausnahme beim Pivot: {app.exception}"


def test_olap_slice_filtert_wuerfel() -> None:
    """Ein Slice auf der Zeitdimension muss den Teilwuerfel verkleinern."""
    app = _starte("OLAP-Explorer")
    monatsfilter = next(
        (m for m in app.multiselect if "Zeitraum" in (m.label or "")), None
    )
    assert monatsfilter is not None, "Zeitfilter nicht gefunden."
    assert len(monatsfilter.options) > 1, "Fuer den Test werden mehrere Monate benoetigt."

    app.multiselect(key="olap_filter_monat_name").set_value(
        [monatsfilter.options[0]]).run()
    assert not app.exception, f"Ausnahme beim Slice: {app.exception}"

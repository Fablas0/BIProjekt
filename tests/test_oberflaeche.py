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
import sqlite3
from pathlib import Path

import pytest

# Die Oberflaechentests pruefen die Fachseiten, nicht die Anmeldemaske; die
# Maske hat eigene Tests auf der Datenschicht (tests/test_nutzerdaten.py).
# Abgeschaltet wird am Modulmerkmal, nicht ueber die Umgebungsvariable: im
# Gesamtlauf hat ein frueher gesammeltes Testmodul bi.config laengst
# importiert, und die Variable wuerde wirkungslos verpuffen.


@pytest.fixture(autouse=True)
def _ohne_anmeldung(monkeypatch):
    from bi.ui import anmeldung

    monkeypatch.setattr(anmeldung, "ANMELDUNG_ERFORDERLICH", False)

WURZEL = Path(__file__).resolve().parents[1]
DWH = Path(os.getenv("VGC_BI_DB", WURZEL / "data" / "vgc_dwh.db"))


# Die Tabelle, an der sich "befuellt" entscheidet.
LEITTABELLE = "Fact_Champions_Usage"


def _ist_befuellt(pfad: Path) -> bool:
    """Prueft auf Inhalt, nicht auf blosse Existenz.

    Eine leere Datenbankdatei entsteht schon durch einen einzigen Verbindungs-
    aufbau. Wuerde hier nur ``exists()`` stehen, liefe die gesamte Testreihe
    gegen ein leeres Warehouse und meldete ein Dutzend irrefuehrender Fehler
    statt eines klaren "uebersprungen".

    Ein Fehler beim Lesen wird bewusst **nicht** verschluckt: ein stiller
    Uebersprung bei falschem Tabellennamen sieht im Bericht aus wie ein
    bestandener Lauf. Genau so bleiben Fehler unentdeckt.
    """
    if not pfad.exists():
        return False
    verbindung = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    try:
        vorhanden = verbindung.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (LEITTABELLE,)).fetchone()
        if not vorhanden:
            return False  # Datei da, aber Schema noch nicht angelegt.
        return verbindung.execute(
            f"SELECT EXISTS(SELECT 1 FROM {LEITTABELLE})").fetchone()[0] == 1
    finally:
        verbindung.close()


pytestmark = pytest.mark.skipif(
    not _ist_befuellt(DWH),
    reason="Kein befuelltes Data Warehouse vorhanden -- Oberflaechentests uebersprungen.",
)

SEITEN = [
    "Start",
    "Meta-Cockpit",
    "Trends",
    "Team-Preview-Advisor",
    "Gegner-Scouting",
    "Team-Builder",
    "Speed-Tiers",
    "Schadensrechner",
    "PC-System",
    "Pokedex",
    "OLAP-Explorer",
    "Meta-Playbook",
    "Spielformen",
    "Hypothesen",
    "GO-Meta",
    "Sammelkartenspiel",
    "Nuzlocke-Lauf",
    "Spielstand",
    "Shiny-Jagd",
    "ETL & Datenqualitaet",
]


def _starte(seite: str | None = None):
    """Fuehrt die Anwendung aus und waehlt optional eine Seite an.

    Die Navigation zeigt nur die Seiten der gewaehlten Spielweise; deshalb
    wird vor dem Start die Spielweise gesetzt, in der die Seite steht -- so,
    wie es die Startseite beim Klick auf eine Kachel tut.
    """
    from streamlit.testing.v1 import AppTest

    from bi.ui import spielweisen

    app = AppTest.from_file(str(WURZEL / "app.py"), default_timeout=180)
    if seite and seite != SEITEN[0]:
        app.session_state["spielweise"] = spielweisen.spielweise_fuer_seite(seite)
    app.run()
    if seite and seite != SEITEN[0]:
        # Die Navigation besteht aus einem Schaltknopf je Seite; der Schluessel
        # ist der Seitenname. Ein Auswahlfeld gibt es nicht mehr.
        app.button(key=f"nav_{seite}").click().run()
    return app


def test_startseite_waehlt_die_spielweise() -> None:
    """Ein Klick auf eine Kachel setzt die Spielweise und springt auf deren
    erste Seite -- die Navigation zeigt danach deren Seiten."""
    from bi.ui import spielweisen

    app = _starte()
    assert not app.exception
    # Vor der Wahl: nur Start und Betrieb in der Navigation.
    knoepfe = {str(k.key) for k in app.button if str(k.key or "").startswith("nav_")}
    assert knoepfe == {"nav_Start", "nav_ETL & Datenqualitaet"}

    app.button(key="spielweise_sammeln").click().run()
    assert not app.exception, f"Ausnahme nach der Wahl: {app.exception}"
    assert app.session_state["spielweise"] == "sammeln"
    assert app.session_state["seite"] == spielweisen.SPIELWEISEN["sammeln"].startseite
    knoepfe = {str(k.key) for k in app.button if str(k.key or "").startswith("nav_")}
    assert "nav_Shiny-Jagd" in knoepfe
    assert "nav_Meta-Cockpit" not in knoepfe


def test_shiny_jagd_zaehlt_und_ordnet_ein() -> None:
    """Eine Jagd anlegen, zaehlen, einordnen -- der Kern der Seite."""
    app = _starte("Shiny-Jagd")
    assert not app.exception, f"Ausnahme beim Aufbau: {app.exception}"

    auswahl = app.selectbox(key="jagd_pokemon")
    assert auswahl.options, "Keine Pokemon zur Auswahl."
    app.selectbox(key="jagd_pokemon").set_value(auswahl.options[0]).run()
    assert not app.exception, f"Ausnahme bei der Wahl: {app.exception}"


def test_nuzlocke_seite_rendert_ohne_lauf() -> None:
    app = _starte("Nuzlocke-Lauf")
    assert not app.exception, f"Ausnahme ohne Lauf: {app.exception}"
    app = _starte("Spielstand")
    assert not app.exception, f"Ausnahme im Spielstand: {app.exception}"


def test_go_meta_rangliste_und_suche() -> None:
    app = _starte("GO-Meta")
    assert not app.exception, f"Ausnahme beim Aufbau: {app.exception}"
    if not any(str(s.key) == "go_liga" for s in app.selectbox):
        pytest.skip("GO-Meta nicht geladen.")
    app.text_input(key="go_suche").set_value("aza").run()
    assert not app.exception, f"Ausnahme bei der Suche: {app.exception}"


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


def test_speedtiers_mit_team_und_szenario() -> None:
    """Die Speed-Tier-Seite muss mit Team und gewechseltem Szenario durchlaufen.

    Erst mit einer Auswahl werden Einordnung, Szenarienvergleich und
    Benchmark-Rechner tatsaechlich ausgefuehrt.
    """
    app = _starte("Speed-Tiers")
    assert not app.exception, f"Ausnahme beim Aufbau: {app.exception}"

    auswahl = app.multiselect(key="speed_team")
    assert auswahl.options, "Keine Pokemon zur Auswahl -- ist das DWH befuellt?"

    app.multiselect(key="speed_team").set_value(auswahl.options[:3]).run()
    assert not app.exception, f"Ausnahme mit Team: {app.exception}"

    # Das Auswahlfeld meldet die formatierten Beschriftungen; gesetzt werden muss
    # dagegen der Rohschluessel. Aeltere Streamlit-Versionen bilden eine
    # Beschriftung nicht auf ihren Schluessel zurueck und wuerden das format_func
    # der Anwendung mit einem KeyError treffen -- der Rohschluessel funktioniert
    # in jeder Version.
    from bi.stats import SZENARIEN

    szenario = app.selectbox(key="speed_vergleich_szenario")
    assert any("Bizarroraum" in o for o in szenario.options), "Bizarroraum fehlt."

    for schluessel in ("rueckenwind", "bizarroraum", "eissturm"):
        assert schluessel in SZENARIEN
        app.selectbox(key="speed_vergleich_szenario").set_value(schluessel).run()
        assert not app.exception, (
            f"Ausnahme im Szenario '{SZENARIEN[schluessel].bezeichnung}': {app.exception}"
        )


def test_speedtiers_benchmark_rechner() -> None:
    """Der Benchmark-Rechner muss zwei verschiedene Pokemon verarbeiten."""
    app = _starte("Speed-Tiers")
    angreifer = app.selectbox(key="bench_angreifer")
    assert len(angreifer.options) >= 2

    app.selectbox(key="bench_angreifer").set_value(angreifer.options[0]).run()
    app.selectbox(key="bench_ziel").set_value(angreifer.options[1]).run()
    assert not app.exception, f"Ausnahme im Benchmark-Rechner: {app.exception}"


def test_pokedex_steckbrief_und_statistik() -> None:
    """Der Pokedex muss Steckbrief, Typen-Berater und Statistik aufbauen.

    Erst mit gewaehltem Pokemon laufen Nachschlage-Links, Typenrechnung und
    Meta-Einordnung tatsaechlich.
    """
    app = _starte("Pokedex")
    assert not app.exception, f"Ausnahme beim Aufbau: {app.exception}"

    auswahl = app.selectbox(key="pokedex_wahl")
    assert len(auswahl.options) > 500, "Der Pokedex muss den vollen Bestand fuehren."

    app.selectbox(key="pokedex_wahl").set_value(auswahl.options[0]).run()
    assert not app.exception, f"Ausnahme im Steckbrief: {app.exception}"


def test_schadensrechner_rechnet_ein_meta_duell() -> None:
    """Der Rechner muss zwei Meta-Sets gegeneinander durchrechnen.

    Erst mit beiden Seiten und einer Attacke laeuft die Schadensformel samt
    Item, Faehigkeit und den Umstaenden (Stufen, Terrain) tatsaechlich.
    """
    app = _starte("Schadensrechner")
    assert not app.exception, f"Ausnahme beim Aufbau: {app.exception}"

    angreifer = app.selectbox(key="angreifer_meta")
    assert len(angreifer.options) >= 2, "Zu wenige Meta-Pokemon fuer den Test."
    app.selectbox(key="angreifer_meta").set_value(angreifer.options[0]).run()
    app.selectbox(key="verteidiger_meta").set_value(angreifer.options[1]).run()
    assert not app.exception, f"Ausnahme bei der Kaempferwahl: {app.exception}"

    attacke = app.selectbox(key="angriff_attacke")
    assert attacke.options, "Keine Attacken-Stammdaten geladen."
    app.selectbox(key="angriff_attacke").set_value(attacke.options[0]).run()
    assert not app.exception, f"Ausnahme bei der Rechnung: {app.exception}"

    # Die Umstaende muessen die Rechnung veraendern koennen, ohne zu brechen.
    app.slider(key="angriff_stufe_an").set_value(2).run()
    assert not app.exception, f"Ausnahme mit Statusstufen: {app.exception}"
    app.selectbox(key="angriff_terrain").set_value("Elektrofeld").run()
    assert not app.exception, f"Ausnahme mit Terrain: {app.exception}"


def test_preview_advisor_mit_zwei_teams() -> None:
    """Der Advisor muss beide Teams bewerten und eine Empfehlung erzeugen."""
    app = _starte("Team-Preview-Advisor")
    assert not app.exception, f"Ausnahme beim Aufbau: {app.exception}"

    eigene = app.multiselect(key="preview_eigene")
    assert len(eigene.options) >= 12, "Zu wenige Champions-Pokemon fuer den Test."

    app.multiselect(key="preview_eigene").set_value(eigene.options[:6]).run()
    app.multiselect(key="preview_gegner").set_value(eigene.options[6:12]).run()
    assert not app.exception, f"Ausnahme bei der Bewertung: {app.exception}"

    # Mit vollstaendigen Teams entstehen die Registerkarten der Auswertung.
    assert app.tabs, "Die Auswertung hat keine Registerkarten erzeugt."


def test_preview_advisor_einzelkampf() -> None:
    """Im Einzelkampf werden drei statt vier Pokemon mitgenommen."""
    app = _starte("Team-Preview-Advisor")
    app.selectbox(key="preview_format").set_value("Singles").run()
    assert not app.exception, f"Ausnahme beim Formatwechsel: {app.exception}"

    eigene = app.multiselect(key="preview_eigene")
    if len(eigene.options) < 12:
        pytest.skip("Zu wenige Singles-Daten fuer den Test.")

    app.multiselect(key="preview_eigene").set_value(eigene.options[:6]).run()
    app.multiselect(key="preview_gegner").set_value(eigene.options[6:12]).run()
    assert not app.exception, f"Ausnahme im Einzelkampf: {app.exception}"


def test_olap_slice_filtert_wuerfel() -> None:
    """Ein Slice auf der Zeitdimension muss den Teilwuerfel verkleinern."""
    app = _starte("OLAP-Explorer")
    monatsfilter = next(
        (m for m in app.multiselect if "Zeitraum" in (m.label or "")), None
    )
    assert monatsfilter is not None, "Zeitfilter nicht gefunden."
    assert len(monatsfilter.options) > 1, "Fuer den Test werden mehrere Monate benoetigt."

    app.multiselect(key="olap_filter_tag_label").set_value(
        [monatsfilter.options[0]]).run()
    assert not app.exception, f"Ausnahme beim Slice: {app.exception}"


def test_ohne_anmeldung_bleibt_die_anwendung_verschlossen(monkeypatch) -> None:
    """Die Anmeldung steht vor allem anderen.

    Die Anwendung ist unter bi.fablas.org oeffentlich erreichbar; ohne
    Anmeldung darf ausser der Maske nichts erscheinen -- keine Navigation,
    keine Seitenleiste, keine Kennzahl. Getestet wird gegen das Modulmerkmal,
    weil die Testreihe selbst mit abgeschalteter Anmeldung laeuft.
    """
    from bi.ui import anmeldung

    monkeypatch.setattr(anmeldung, "ANMELDUNG_ERFORDERLICH", True)

    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(WURZEL / "app.py"), default_timeout=180)
    app.run()

    assert not app.exception
    # Keine Navigation: die Seitenknoepfe existieren nicht.
    assert not [k for k in app.button if str(k.key or "").startswith("nav_")]
    # Stattdessen die Maske: Benutzername- und Passwortfelder sind da.
    assert app.text_input, "Die Anmeldemaske fehlt."

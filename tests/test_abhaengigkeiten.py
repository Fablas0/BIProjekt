"""Tests, die die Lauffaehigkeit in einer sauberen Umgebung absichern.

Hintergrund: ``scipy`` war eine undeklarierte Laufzeitabhaengigkeit. Die
Kennzahl :func:`bi.analytics.kpi.meta_stabilitaet` verwendete
``Series.corr(method="spearman")``; pandas delegiert diesen Modus an
``scipy.stats.spearmanr``. Auf der Entwicklungsmaschine lag scipy zufaellig im
Interpreter, in der CI und auf Streamlit Cloud nicht -- dort scheiterte damit
die **Startseite** der Anwendung.

Die vorhandenen Oberflaechentests konnten das nicht finden: sie ueberspringen
sich selbst, solange kein befuelltes Data Warehouse vorliegt, und in der
Testmatrix liegt keines. Die Tests hier brauchen kein Warehouse -- sie bauen
sich eines im Arbeitsspeicher -- und laufen deshalb in jeder Umgebung mit.
"""

from __future__ import annotations

import builtins
import importlib
from pathlib import Path

import pytest

from bi import warehouse
from bi.analytics import kpi
from bi.etl import champions, load
from bi.etl.transform import transformiere_pokemon

# Pakete, die das Projekt bewusst NICHT voraussetzt. Sie liessen sich fuer die
# Zielumgebungen auch nicht einheitlich festlegen: scipy endet fuer Python 3.10
# bei 1.15.3 und beginnt fuer 3.14 erst bei 1.16.1 -- es gibt keine Version,
# die beide bedient.
UNERWUENSCHTE_ABHAENGIGKEITEN = ("scipy", "sklearn", "statsmodels", "matplotlib", "seaborn")


@pytest.fixture
def dwh():
    """Kleines Warehouse mit zwei Tagen -- genug fuer eine Rangkorrelation."""
    conn = warehouse.verbindung(":memory:")

    saetze = []
    for i, (name, basis) in enumerate([
        ("garchomp", 102), ("incineroar", 60), ("kingambit", 50),
        ("charizard", 100), ("whimsicott", 116),
    ]):
        satz, _ = transformiere_pokemon({
            "id": 100 + i, "name": name, "species": {"name": name},
            "types": [{"type": {"name": "normal"}}],
            "stats": [
                {"stat": {"name": "hp"}, "base_stat": 80},
                {"stat": {"name": "attack"}, "base_stat": 100},
                {"stat": {"name": "defense"}, "base_stat": 80},
                {"stat": {"name": "special-attack"}, "base_stat": 80},
                {"stat": {"name": "special-defense"}, "base_stat": 80},
                {"stat": {"name": "speed"}, "base_stat": basis},
            ],
        }, {name: 9})
        saetze.append(satz)

    load.lade_pokemon_dimension(conn, saetze, stichtag="2026-01-01")
    zeit = load.lade_zeit(conn, ["2026-07-27", "2026-07-28"])
    quelle_sk = load.lade_quelle(conn, "champions")
    formate = load.lade_alle_kampfformate(conn)
    saison_sk = load.lade_saison(conn, "M4", "Season 4", quelle_sk,
                                 ["2026-07-27", "2026-07-28"])
    pokemon = {z["slug"]: z["pokemon_sk"] for z in
               conn.execute("SELECT slug, pokemon_sk FROM Dim_Pokemon")}
    lauf = load.lauf_beginnen(conn, "Test", "abhaengigkeiten")

    # Zwei Tage mit leicht verschobener Rangfolge.
    for tag, reihenfolge in (
        ("2026-07-27", ["garchomp", "incineroar", "kingambit", "charizard", "whimsicott"]),
        ("2026-07-28", ["incineroar", "garchomp", "charizard", "kingambit", "whimsicott"]),
    ):
        champions.lade_fakten(
            conn,
            [champions.ChampionsSatz(slug, "M4", tag, "Doubles", rang, [])
             for rang, slug in enumerate(reihenfolge, start=1)],
            zeit, saison_sk, formate, quelle_sk, pokemon, {}, lauf,
        )

    yield conn
    conn.close()


def test_keine_undeklarierten_analysepakete_importiert() -> None:
    """Kein Modul des Projekts darf ein nicht deklariertes Paket importieren.

    Geprueft wird beim Import, nicht statisch: pandas laedt scipy erst beim
    Aufruf nach, ein Grep ueber die Quelldateien haette den Fehler daher nicht
    gefunden.
    """
    for modul in ("bi.analytics.kpi", "bi.analytics.olap", "bi.analytics.speed",
                  "bi.analytics.threat", "bi.analytics.preview", "bi.quality",
                  "bi.stats", "bi.warehouse"):
        importlib.import_module(modul)

    import sys
    geladen = {name.split(".")[0] for name in sys.modules}
    unerwuenscht = geladen & set(UNERWUENSCHTE_ABHAENGIGKEITEN)
    assert not unerwuenscht, (
        f"Nicht deklarierte Pakete geladen: {sorted(unerwuenscht)}. "
        "Entweder in requirements.txt aufnehmen oder die Verwendung ersetzen."
    )


def test_meta_stabilitaet_ohne_scipy(dwh, monkeypatch) -> None:
    """Die Rangkorrelation muss auch ohne scipy im Interpreter funktionieren.

    scipy wird waehrend des Aufrufs unauffindbar gemacht -- genau die Lage in
    der CI und auf Streamlit Cloud.
    """
    echter_import = builtins.__import__

    def ohne_scipy(name, *args, **kwargs):
        if name.split(".")[0] == "scipy":
            raise ModuleNotFoundError("No module named 'scipy'")
        return echter_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", ohne_scipy)

    wert = kpi.meta_stabilitaet(dwh, "2026-07-27", "2026-07-28")
    assert wert is not None
    assert -1.0 <= wert <= 1.0


def test_rangkorrelation_ist_rechnerisch_richtig(dwh) -> None:
    """Gegenprobe gegen den von Hand gerechneten Spearman-Wert.

    Die beiden Tage unterscheiden sich in zwei vertauschten Paaren. Bei fuenf
    Beobachtungen ohne Bindungen gilt rho = 1 - 6 * sum(d^2) / (n * (n^2 - 1));
    mit d = (-1, 1, -1, 1, 0) ergibt sum(d^2) = 4 und damit rho = 0,8.
    """
    assert kpi.meta_stabilitaet(dwh, "2026-07-27", "2026-07-28") == pytest.approx(0.8)


def test_identische_tage_ergeben_volle_korrelation(dwh) -> None:
    assert kpi.meta_stabilitaet(dwh, "2026-07-28", "2026-07-28") == pytest.approx(1.0)


def test_zu_wenige_gemeinsame_pokemon(dwh) -> None:
    """Unter drei Paaren ist keine belastbare Korrelation moeglich."""
    assert kpi.meta_stabilitaet(dwh, "2026-07-27", "2026-01-01") is None


def test_eckwerte_laufen_ohne_scipy(dwh, monkeypatch) -> None:
    """Der Aufrufpfad der Startseite muss vollstaendig durchlaufen.

    kpi.eckwerte ruft meta_stabilitaet auf; genau hier brach die Startseite in
    einer sauberen Umgebung ab.
    """
    echter_import = builtins.__import__

    def ohne_scipy(name, *args, **kwargs):
        if name.split(".")[0] == "scipy":
            raise ModuleNotFoundError("No module named 'scipy'")
        return echter_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", ohne_scipy)

    werte = kpi.eckwerte(dwh, "2026-07-28")
    assert werte["erfasste_pokemon"] == 5
    assert werte["spitzenreiter"] == "Incineroar"
    assert werte["stabilitaet"] == pytest.approx(0.8)


def test_stabilitaet_verlauf_ohne_scipy(dwh, monkeypatch) -> None:
    echter_import = builtins.__import__

    def ohne_scipy(name, *args, **kwargs):
        if name.split(".")[0] == "scipy":
            raise ModuleNotFoundError("No module named 'scipy'")
        return echter_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", ohne_scipy)

    verlauf = kpi.stabilitaet_verlauf(dwh)
    assert len(verlauf) == 1
    assert verlauf.iloc[0]["stabilitaet_zum_start"] == pytest.approx(0.8)


def test_ueberspringwaechter_der_oberflaechentests_trifft_zu(dwh) -> None:
    """Der Waechter darf die Oberflaechentests nicht versehentlich stilllegen.

    ``test_oberflaeche`` ueberspringt sich ohne befuelltes Warehouse selbst. Traefe
    der Waechter wegen eines umbenannten Tabellennamens *immer* zu, meldete der
    Bericht weiterhin "bestanden" -- waehrend in Wahrheit keine einzige Seite mehr
    geprueft wuerde. Dieselbe Fehlerklasse hatte zuvor eine nicht deklarierte
    Abhaengigkeit bis in den Produktivbetrieb durchgelassen.
    """
    from tests.test_oberflaeche import LEITTABELLE, _ist_befuellt

    assert dwh.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (LEITTABELLE,)).fetchone(), (
        f"Die Leittabelle '{LEITTABELLE}' gibt es im Schema nicht mehr -- "
        "der Waechter wuerde die Oberflaechentests dauerhaft ueberspringen."
    )
    assert dwh.execute(f"SELECT COUNT(*) FROM {LEITTABELLE}").fetchone()[0] > 0, (
        f"'{LEITTABELLE}' bleibt in der Testvorrichtung leer und taugt damit "
        "nicht als Nachweis fuer ein befuelltes Warehouse."
    )
    assert _ist_befuellt(Path("gibt-es-sicher-nicht.db")) is False

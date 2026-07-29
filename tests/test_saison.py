"""Tests der Saisonauswahl.

Bis zur Einfuehrung dieser Auswahl filterte jede Abfrage der Analyseschicht
fest auf die laufende Saison. Sobald Pokemon Champions eine neue eroeffnet,
haette das die gesamte archivierte Historie aus der Oberflaeche entfernt --
ausgerechnet die Daten, deren Sicherung der Zweck des Archivs ist.

Der entscheidende Test ist nicht, dass die Auswahl *funktioniert*, sondern dass
**keine Abfrage sie auslaesst**. Eine uebersehene Stelle liefert stillschweigend
die Zahlen der falschen Saison, statt abzubrechen.
"""

from __future__ import annotations

import pytest

from bi import warehouse
from bi.analytics import kpi, olap, saison


@pytest.fixture
def zwei_saisons():
    """Ein Warehouse mit einer abgelaufenen und einer laufenden Saison."""
    conn = warehouse.verbindung(":memory:")
    conn.executescript("""
        INSERT INTO Dim_Quelle (quelle_sk, schluessel, name, beschreibung,
                                ist_offiziell, granularitaet_zeit,
                                messniveau_nutzung, hat_partner_gewicht)
             VALUES (1, 'champions', 'Pokemon Champions', 'Testquelle',
                     1, 'Tag', 'ordinal', 1);
        INSERT INTO Dim_Kampfformat (kampfformat_sk, schluessel, bezeichnung,
                                     aktive_pokemon, mitnahme)
             VALUES (1, 'Doubles', 'Doppelkampf', 2, 4);
        INSERT INTO Dim_Saison (saison_sk, schluessel, bezeichnung, quelle_sk,
                                beginn, ende, ist_aktuell, erfasst_am)
             VALUES (1, 'M4', 'Season 4', 1, '2026-07-01', '2026-07-31', 0,
                     '2026-08-01'),
                    (2, 'M5', 'Season 5', 1, '2026-08-01', '2026-08-31', 1,
                     '2026-08-01');
    """)
    from bi.etl import load
    from bi.etl.transform import transformiere_pokemon

    zeit = load.lade_zeit(conn, ["2026-07-20", "2026-08-10"])
    lauf_id = load.lauf_beginnen(conn, "Champions", "Test")

    for slug, pid in (("garchomp", 445), ("incineroar", 727)):
        nutzlast = {
            "id": pid, "name": slug, "species": {"name": slug},
            "types": [{"type": {"name": "dragon"}}],
            "stats": [{"stat": {"name": s}, "base_stat": 100} for s in
                      ("hp", "attack", "defense", "special-attack",
                       "special-defense", "speed")],
        }
        satz, _ = transformiere_pokemon(nutzlast, {slug: 4})
        load.lade_pokemon_dimension(conn, [satz])

    # Garchomp fuehrt M4 an, Incineroar fuehrt M5 an -- daran laesst sich
    # ablesen, welche Saison eine Abfrage tatsaechlich ausgewertet hat.
    conn.executemany(
        f"""INSERT INTO Fact_Champions_Usage
               (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, quelle_sk,
                rang, rang_perzentil, erfasste_pokemon, etl_lauf_id)
           VALUES (?, ?, ?, ?, 1, ?, ?, 2, {lauf_id})""",
        [(1, zeit["2026-07-20"], 1, 1, 1, 100.0),
         (2, zeit["2026-07-20"], 1, 1, 2,  50.0),
         (2, zeit["2026-08-10"], 2, 1, 1, 100.0),
         (1, zeit["2026-08-10"], 2, 1, 2,  50.0)])
    conn.commit()
    yield conn
    conn.close()


def test_ohne_wahl_gilt_die_laufende_saison(zwei_saisons) -> None:
    """Das bisherige Verhalten bleibt die Vorgabe."""
    assert zwei_saisons.saison_wahl is None
    assert kpi.verfuegbare_tage(zwei_saisons) == ["2026-08-10"]
    assert kpi.datenbasis(zwei_saisons)["saison"] == "M5"


def test_wahl_schaltet_auf_die_abgelaufene_saison_um(zwei_saisons) -> None:
    """Der eigentliche Zweck: die archivierte Historie bleibt erreichbar."""
    zwei_saisons.saison_wahl = "M4"

    assert kpi.verfuegbare_tage(zwei_saisons) == ["2026-07-20"]
    assert kpi.datenbasis(zwei_saisons)["saison"] == "M4"

    rangliste = kpi.rangliste(zwei_saisons, "2026-07-20")
    assert rangliste.iloc[0]["anzeigename"] == "Garchomp"

    wuerfel = olap.lade_wuerfel(zwei_saisons)
    assert set(wuerfel["saison"]) == {"M4"}


def test_unbekannte_wahl_faellt_auf_die_laufende_zurueck(zwei_saisons) -> None:
    """Eine veraltete Auswahl in der Sitzung darf nichts lahmlegen."""
    zwei_saisons.saison_wahl = "M99"
    assert kpi.datenbasis(zwei_saisons)["saison"] == "M5"


def test_verfuegbare_saisons_werden_gelistet(zwei_saisons) -> None:
    saisons = saison.verfuegbare(zwei_saisons)

    assert [s.schluessel for s in saisons] == ["M5", "M4"], "Laufende zuerst."
    assert saisons[0].ist_aktuell is True
    assert saisons[1].tage == 1
    assert "laufend" in saisons[0].anzeige


def test_leeres_warehouse_liefert_nichts_statt_allem() -> None:
    """Ohne Saison darf das Praedikat nicht versehentlich alles durchlassen."""
    conn = warehouse.verbindung(":memory:")
    try:
        sql = saison.anwenden("SELECT * FROM V_Usage WHERE saison_aktuell = 1", conn)
        assert "1 = 0" in sql
        assert "saison_aktuell" not in sql
    finally:
        conn.close()


def test_alias_bleibt_beim_ersetzen_erhalten(zwei_saisons) -> None:
    """Aus ``u.saison_aktuell = 1`` muss ``u.saison_sk = N`` werden."""
    zwei_saisons.saison_wahl = "M4"
    sql = saison.anwenden("SELECT 1 FROM V_Usage u WHERE u.saison_aktuell = 1",
                          zwei_saisons)
    assert sql.endswith("u.saison_sk = 1")


def test_keine_abfrage_umgeht_den_saisonfilter(zwei_saisons, monkeypatch) -> None:
    """Der Test, auf den es ankommt.

    Geprueft wird nicht der Quelltext, sondern was tatsaechlich bei SQLite
    ankommt: keine ausgefuehrte Abfrage darf das Praedikat noch im Klartext
    tragen. Eine uebersehene Stelle wertet stillschweigend die falsche Saison
    aus -- ein Fehler, den keine Anzeige verraet.
    """
    import pandas as pd

    gesehen: list[str] = []
    echtes_read_sql = pd.read_sql
    echtes_execute = type(zwei_saisons).execute

    def merke_read_sql(sql, con, *a, **k):
        gesehen.append(str(sql))
        return echtes_read_sql(sql, con, *a, **k)

    def merke_execute(self, sql, *a, **k):
        gesehen.append(str(sql))
        return echtes_execute(self, sql, *a, **k)

    monkeypatch.setattr(pd, "read_sql", merke_read_sql)
    monkeypatch.setattr(type(zwei_saisons), "execute", merke_execute)

    zwei_saisons.saison_wahl = "M4"
    tag = "2026-07-20"

    # Jeder Einstiegspunkt, der Bewegungsdaten auswertet.
    kpi.verfuegbare_tage(zwei_saisons)
    kpi.datenbasis(zwei_saisons)
    kpi.rangliste(zwei_saisons, tag)
    kpi.meta_uebersicht(zwei_saisons, tag)
    kpi.eckwerte(zwei_saisons, tag)
    kpi.rangverlauf(zwei_saisons)
    kpi.rangbewegung(zwei_saisons, tag)
    kpi.verweildauer(zwei_saisons)
    kpi.vorhersagbarkeit(zwei_saisons, tag)
    kpi.teampartner(zwei_saisons, ["Garchomp"], tag)
    kpi.standardset(zwei_saisons, "Garchomp", tag)
    olap.lade_wuerfel(zwei_saisons)

    from bi.analytics import preview, speed, threat
    preview.lade_kaempfer(zwei_saisons, ["Garchomp"], tag, "Doubles")
    speed.speed_tier_liste(zwei_saisons, tag)
    speed.benchmark(zwei_saisons, "Garchomp", "Incineroar", tag)
    speed.team_einordnung(zwei_saisons, ["Garchomp"], tag)
    threat.angriffstyp_haeufigkeit(zwei_saisons, tag)
    team = kpi.rangliste(zwei_saisons, tag)
    threat.bedrohungsindex(zwei_saisons, team, tag)
    threat.offensive_abdeckung(zwei_saisons, ["Garchomp"], tag)
    threat.strategie_radar(zwei_saisons, ["Garchomp"], tag)

    durchgerutscht = [s for s in gesehen if "saison_aktuell" in s]
    assert not durchgerutscht, (
        f"{len(durchgerutscht)} Abfrage(n) erreichen die Datenbank mit dem "
        f"unersetzten Praedikat und werten damit immer die laufende Saison aus: "
        f"{[s[:110] for s in durchgerutscht]}")
    assert gesehen, "Es wurde keine Abfrage beobachtet -- der Test greift ins Leere."

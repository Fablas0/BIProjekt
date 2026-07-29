"""Physisches Datenmodell des Data Warehouse.

Aufbau in drei Schichten entsprechend der klassischen DWH-Architektur:

1. **Staging / ODS** (``Stage_*``) -- unveraenderte Rohdaten der Quellsysteme,
   je ETL-Lauf. Dient der Nachvollziehbarkeit und erlaubt ein erneutes
   Transformieren ohne neuen Quellzugriff.
2. **Core Data Warehouse** (``Dim_*`` / ``Fact_*``) -- integriertes,
   historisiertes Galaxy-Schema.
3. **Metadaten** (``ETL_Lauf``, ``DQ_Befund``) -- Protokollierung von
   Ladelaeufen und Datenqualitaetsbefunden.

Das Core-DWH ist ein **Galaxy-Schema** (Fact Constellation): sechs Faktentabellen
teilen sich die konformen Dimensionen ``Dim_Pokemon``, ``Dim_Zeit``,
``Dim_Regulation`` und ``Dim_Skill``.

Historisierung
--------------
``Dim_Pokemon`` ist **bi-temporal** ausgefuehrt: ``gueltig_ab`` / ``gueltig_bis``
bilden die fachliche Gueltigkeit ab, ``ist_aktuell`` erlaubt den schnellen Zugriff
auf den Ist-Stand ohne Datumsvergleich, ``dwh_geladen_am`` haelt den technischen
Ladezeitpunkt fest. Aenderungen werden ueber ``row_hash`` erkannt.

Die Faktentabellen sind nicht-volatil (Inmon): es wird ausschliesslich eingefuegt.
Ein erneuter Lauf desselben Monats aktualisiert ueber den fachlichen
Eindeutigkeitsschluessel (idempotenter Reload), loescht aber keine Historie.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DWH_PFAD, datenverzeichnis_anlegen

# Fernes Datum als offenes Ende eines Gueltigkeitszeitraums. Ein konkreter Wert
# statt NULL haelt Bereichsabfragen frei von Sonderbehandlung.
UNENDLICH = "9999-12-31"

SCHEMA_DDL = """
-- =====================================================================
-- SCHICHT 1: STAGING / OPERATIONAL DATA STORE
-- =====================================================================

CREATE TABLE IF NOT EXISTS Stage_Pokeapi (
    lauf_id      INTEGER NOT NULL,
    slug         TEXT    NOT NULL,
    nutzlast     TEXT    NOT NULL,          -- unveraendertes JSON der Quelle
    geladen_am   TEXT    NOT NULL,
    PRIMARY KEY (lauf_id, slug)
);

CREATE TABLE IF NOT EXISTS Stage_Smogon (
    lauf_id      INTEGER NOT NULL,
    format_code  TEXT    NOT NULL,
    elo_cutoff   INTEGER NOT NULL,
    monat_iso    TEXT    NOT NULL,
    quell_name   TEXT    NOT NULL,          -- Pokemon-Bezeichner wie von Smogon geliefert
    nutzlast     TEXT    NOT NULL,
    geladen_am   TEXT    NOT NULL,
    PRIMARY KEY (lauf_id, format_code, elo_cutoff, monat_iso, quell_name)
);

-- =====================================================================
-- SCHICHT 2: CORE DATA WAREHOUSE -- DIMENSIONEN
-- =====================================================================

-- Zeitdimension mit Konsolidierungspfad Monat -> Quartal -> Jahr.
CREATE TABLE IF NOT EXISTS Dim_Zeit (
    zeit_sk      INTEGER PRIMARY KEY,
    monat_iso    TEXT    NOT NULL UNIQUE,   -- '2026-06'
    jahr         INTEGER NOT NULL,
    quartal      INTEGER NOT NULL,
    monat        INTEGER NOT NULL,
    monat_name   TEXT    NOT NULL,
    quartal_label TEXT   NOT NULL,          -- 'Q2 2026'
    ist_letzter_monat INTEGER NOT NULL DEFAULT 0
);

-- Pokemon-Dimension, bi-temporal historisiert.
-- Konsolidierungspfad: Generation -> Spezies -> Form (slug).
CREATE TABLE IF NOT EXISTS Dim_Pokemon (
    pokemon_sk      INTEGER PRIMARY KEY AUTOINCREMENT,
    pokedex_id      INTEGER NOT NULL,       -- natuerlicher Schluessel (Quellsystem)
    slug            TEXT    NOT NULL,       -- formgenauer PokeAPI-Bezeichner
    anzeigename     TEXT    NOT NULL,
    spezies         TEXT    NOT NULL,       -- Hierarchieebene 2
    generation      INTEGER NOT NULL,       -- Hierarchieebene 1
    typ1            TEXT    NOT NULL,
    typ2            TEXT,
    typ_kombination TEXT    NOT NULL,       -- 'Water / Fighting' bzw. 'Water'
    hp              INTEGER NOT NULL,
    attack          INTEGER NOT NULL,
    defense         INTEGER NOT NULL,
    sp_attack       INTEGER NOT NULL,
    sp_defense      INTEGER NOT NULL,
    speed           INTEGER NOT NULL,
    basiswert_summe INTEGER NOT NULL,       -- Anreicherung
    offensiv_profil TEXT    NOT NULL,       -- Anreicherung: Physisch/Speziell/Gemischt
    rolle           TEXT    NOT NULL,       -- Anreicherung: Sweeper/Wall/Support/...
    speed_klasse    TEXT    NOT NULL,       -- Anreicherung: Speed-Tier-Klasse
    resistenz_wert  REAL    NOT NULL,       -- Anreicherung aus der Typen-Matrix
    -- Bi-temporale Delta-Historisierung
    row_hash        TEXT    NOT NULL,
    gueltig_ab      TEXT    NOT NULL,
    gueltig_bis     TEXT    NOT NULL DEFAULT '9999-12-31',
    ist_aktuell     INTEGER NOT NULL DEFAULT 1,
    dwh_geladen_am  TEXT    NOT NULL,
    UNIQUE (slug, gueltig_ab)
);

CREATE INDEX IF NOT EXISTS ix_dim_pokemon_aktuell ON Dim_Pokemon (slug, ist_aktuell);
CREATE INDEX IF NOT EXISTS ix_dim_pokemon_gen     ON Dim_Pokemon (generation, spezies);

-- Regulation/Format mit Konsolidierungspfad Format -> Regulation -> Generation.
CREATE TABLE IF NOT EXISTS Dim_Regulation (
    regulation_sk INTEGER PRIMARY KEY AUTOINCREMENT,
    format_code   TEXT    NOT NULL UNIQUE,  -- 'gen9vgc2026regi'
    regulation    TEXT    NOT NULL,         -- 'Reg I'
    spielmodus    TEXT    NOT NULL,         -- 'Bo1' | 'Bo3'
    saison        TEXT    NOT NULL,         -- 'VGC 2026'
    generation    TEXT    NOT NULL,         -- 'Gen 9'
    anzeige       TEXT    NOT NULL
);

-- Skill-Dimension (ELO-Grenzwert der Smogon-Auswertung).
CREATE TABLE IF NOT EXISTS Dim_Skill (
    skill_sk     INTEGER PRIMARY KEY AUTOINCREMENT,
    elo_cutoff   INTEGER NOT NULL UNIQUE,
    bezeichnung  TEXT    NOT NULL,
    stufe        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS Dim_Item (
    item_sk     INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,
    anzeigename TEXT NOT NULL,
    kategorie   TEXT NOT NULL DEFAULT 'Sonstige'
);

CREATE TABLE IF NOT EXISTS Dim_Faehigkeit (
    faehigkeit_sk INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    anzeigename   TEXT NOT NULL,
    effekt_klasse TEXT NOT NULL DEFAULT 'Sonstige'  -- Wetter/Terrain/Redirect/...
);

-- Attacken-Dimension mit Hierarchie Attacke -> Typ und Attacke -> Kategorie.
CREATE TABLE IF NOT EXISTS Dim_Attacke (
    attacke_sk    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    anzeigename   TEXT NOT NULL,
    typ           TEXT,
    kategorie     TEXT,                     -- physical | special | status
    basisschaden  INTEGER,
    genauigkeit   INTEGER,
    prioritaet    INTEGER,
    zielbereich   TEXT,                     -- z.B. all-opponents (Flaechenattacke)
    taktik_klasse TEXT NOT NULL DEFAULT 'Offensiv'  -- Anreicherung fuer den Strategie-Radar
);

CREATE TABLE IF NOT EXISTS Dim_Tera (
    tera_sk INTEGER PRIMARY KEY AUTOINCREMENT,
    typ     TEXT NOT NULL UNIQUE
);

-- =====================================================================
-- SCHICHT 2: CORE DATA WAREHOUSE -- FAKTEN (Galaxy-Schema)
-- =====================================================================

-- Zentrale Faktentabelle.
-- Granularitaet: ein Pokemon je Format, ELO-Stufe und Monat.
CREATE TABLE IF NOT EXISTS Fact_Usage (
    usage_sk       INTEGER PRIMARY KEY AUTOINCREMENT,
    pokemon_sk     INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk        INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    regulation_sk  INTEGER NOT NULL REFERENCES Dim_Regulation (regulation_sk),
    skill_sk       INTEGER NOT NULL REFERENCES Dim_Skill (skill_sk),
    usage_rate     REAL    NOT NULL,        -- Kennzahl: Nutzungsanteil in %
    raw_count      INTEGER NOT NULL,        -- Kennzahl: absolute Teamnennungen
    partien_gesamt INTEGER NOT NULL,        -- Kontext aus info.number of battles
    gxe_top        REAL,                    -- Kennzahl: bestes GXE (Viability Ceiling)
    gxe_p75        REAL,
    gxe_p50        REAL,
    rang           INTEGER NOT NULL,        -- Anreicherung: Usage-Rang im Monat
    etl_lauf_id    INTEGER NOT NULL,
    UNIQUE (pokemon_sk, zeit_sk, regulation_sk, skill_sk)
);

CREATE INDEX IF NOT EXISTS ix_fact_usage_zeit ON Fact_Usage (zeit_sk, regulation_sk, skill_sk);

-- Loadout-Fakten. Granularitaet jeweils: Pokemon x Format x ELO x Monat x Auspraegung.
CREATE TABLE IF NOT EXISTS Fact_Attacken_Nutzung (
    pokemon_sk    INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk       INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    regulation_sk INTEGER NOT NULL REFERENCES Dim_Regulation (regulation_sk),
    skill_sk      INTEGER NOT NULL REFERENCES Dim_Skill (skill_sk),
    attacke_sk    INTEGER NOT NULL REFERENCES Dim_Attacke (attacke_sk),
    anteil        REAL    NOT NULL,         -- Kennzahl: Anteil der Sets in %
    rang          INTEGER NOT NULL,
    PRIMARY KEY (pokemon_sk, zeit_sk, regulation_sk, skill_sk, attacke_sk)
);

CREATE TABLE IF NOT EXISTS Fact_Item_Nutzung (
    pokemon_sk    INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk       INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    regulation_sk INTEGER NOT NULL REFERENCES Dim_Regulation (regulation_sk),
    skill_sk      INTEGER NOT NULL REFERENCES Dim_Skill (skill_sk),
    item_sk       INTEGER NOT NULL REFERENCES Dim_Item (item_sk),
    anteil        REAL    NOT NULL,
    rang          INTEGER NOT NULL,
    PRIMARY KEY (pokemon_sk, zeit_sk, regulation_sk, skill_sk, item_sk)
);

CREATE TABLE IF NOT EXISTS Fact_Faehigkeit_Nutzung (
    pokemon_sk    INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk       INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    regulation_sk INTEGER NOT NULL REFERENCES Dim_Regulation (regulation_sk),
    skill_sk      INTEGER NOT NULL REFERENCES Dim_Skill (skill_sk),
    faehigkeit_sk INTEGER NOT NULL REFERENCES Dim_Faehigkeit (faehigkeit_sk),
    anteil        REAL    NOT NULL,
    rang          INTEGER NOT NULL,
    PRIMARY KEY (pokemon_sk, zeit_sk, regulation_sk, skill_sk, faehigkeit_sk)
);

CREATE TABLE IF NOT EXISTS Fact_Tera_Nutzung (
    pokemon_sk    INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk       INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    regulation_sk INTEGER NOT NULL REFERENCES Dim_Regulation (regulation_sk),
    skill_sk      INTEGER NOT NULL REFERENCES Dim_Skill (skill_sk),
    tera_sk       INTEGER NOT NULL REFERENCES Dim_Tera (tera_sk),
    anteil        REAL    NOT NULL,
    rang          INTEGER NOT NULL,
    PRIMARY KEY (pokemon_sk, zeit_sk, regulation_sk, skill_sk, tera_sk)
);

-- Beziehungsfakt: gemeinsames Auftreten zweier Pokemon in einem Team.
CREATE TABLE IF NOT EXISTS Fact_Teampartner (
    pokemon_sk    INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    partner_sk    INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk       INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    regulation_sk INTEGER NOT NULL REFERENCES Dim_Regulation (regulation_sk),
    skill_sk      INTEGER NOT NULL REFERENCES Dim_Skill (skill_sk),
    synergie_wert REAL    NOT NULL,         -- Kennzahl: gewichtete Ko-Nutzung
    rang          INTEGER NOT NULL,
    PRIMARY KEY (pokemon_sk, partner_sk, zeit_sk, regulation_sk, skill_sk)
);

-- =====================================================================
-- SCHICHT 3: METADATEN
-- =====================================================================

CREATE TABLE IF NOT EXISTS ETL_Lauf (
    lauf_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    gestartet_am     TEXT    NOT NULL,
    beendet_am       TEXT,
    quelle           TEXT    NOT NULL,      -- 'PokeAPI' | 'Smogon'
    parameter        TEXT,                  -- z.B. 'gen9vgc2026regi / ELO 1760 / 6 Monate'
    status           TEXT    NOT NULL,      -- 'laeuft' | 'erfolgreich' | 'fehler'
    zeilen_gelesen   INTEGER NOT NULL DEFAULT 0,
    zeilen_geladen   INTEGER NOT NULL DEFAULT 0,
    zeilen_abgewiesen INTEGER NOT NULL DEFAULT 0,
    dauer_sekunden   REAL,
    meldung          TEXT
);

CREATE TABLE IF NOT EXISTS DQ_Befund (
    befund_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    lauf_id     INTEGER NOT NULL REFERENCES ETL_Lauf (lauf_id),
    regel       TEXT    NOT NULL,
    dimension   TEXT    NOT NULL,           -- DQ-Dimension: Vollstaendigkeit/Konsistenz/...
    klasse      TEXT    NOT NULL,           -- 'Mangel 1. Klasse' | 'Mangel 2. Klasse'
    schweregrad TEXT    NOT NULL,           -- 'Info' | 'Warnung' | 'Fehler'
    entitaet    TEXT    NOT NULL,
    schluessel  TEXT,
    meldung     TEXT    NOT NULL,
    erfasst_am  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_dq_lauf ON DQ_Befund (lauf_id, schweregrad);
"""

# Sichten fuer die Analyseschicht. Sie kapseln die Star-Joins, damit die
# UI-Module keine Schluesselverknuepfungen mehr selbst formulieren muessen.
SICHTEN_DDL = """
DROP VIEW IF EXISTS V_Usage;
CREATE VIEW V_Usage AS
SELECT
    f.usage_sk, f.pokemon_sk, f.zeit_sk, f.regulation_sk, f.skill_sk,
    p.pokedex_id, p.slug, p.anzeigename, p.spezies, p.generation,
    p.typ1, p.typ2, p.typ_kombination,
    p.hp, p.attack, p.defense, p.sp_attack, p.sp_defense, p.speed,
    p.basiswert_summe, p.offensiv_profil, p.rolle, p.speed_klasse, p.resistenz_wert,
    z.monat_iso, z.jahr, z.quartal, z.quartal_label, z.monat_name, z.ist_letzter_monat,
    r.format_code, r.regulation, r.spielmodus, r.saison, r.anzeige AS format_anzeige,
    s.elo_cutoff, s.bezeichnung AS skill_bezeichnung,
    f.usage_rate, f.raw_count, f.partien_gesamt,
    f.gxe_top, f.gxe_p75, f.gxe_p50, f.rang
FROM Fact_Usage f
JOIN Dim_Pokemon    p ON p.pokemon_sk    = f.pokemon_sk
JOIN Dim_Zeit       z ON z.zeit_sk       = f.zeit_sk
JOIN Dim_Regulation r ON r.regulation_sk = f.regulation_sk
JOIN Dim_Skill      s ON s.skill_sk      = f.skill_sk;

DROP VIEW IF EXISTS V_Attacken;
CREATE VIEW V_Attacken AS
SELECT
    f.pokemon_sk, f.zeit_sk, f.regulation_sk, f.skill_sk,
    p.anzeigename, p.slug,
    z.monat_iso, r.format_code, s.elo_cutoff,
    a.slug AS attacke_slug, a.anzeigename AS attacke, a.typ AS attacke_typ,
    a.kategorie, a.basisschaden, a.prioritaet, a.zielbereich, a.taktik_klasse,
    f.anteil, f.rang
FROM Fact_Attacken_Nutzung f
JOIN Dim_Pokemon    p ON p.pokemon_sk    = f.pokemon_sk
JOIN Dim_Attacke    a ON a.attacke_sk    = f.attacke_sk
JOIN Dim_Zeit       z ON z.zeit_sk       = f.zeit_sk
JOIN Dim_Regulation r ON r.regulation_sk = f.regulation_sk
JOIN Dim_Skill      s ON s.skill_sk      = f.skill_sk;

DROP VIEW IF EXISTS V_Loadout;
CREATE VIEW V_Loadout AS
SELECT f.pokemon_sk, f.zeit_sk, f.regulation_sk, f.skill_sk,
       'Item' AS auspraegung_art, i.anzeigename AS auspraegung, f.anteil, f.rang
FROM Fact_Item_Nutzung f JOIN Dim_Item i ON i.item_sk = f.item_sk
UNION ALL
SELECT f.pokemon_sk, f.zeit_sk, f.regulation_sk, f.skill_sk,
       'Faehigkeit', a.anzeigename, f.anteil, f.rang
FROM Fact_Faehigkeit_Nutzung f JOIN Dim_Faehigkeit a ON a.faehigkeit_sk = f.faehigkeit_sk
UNION ALL
SELECT f.pokemon_sk, f.zeit_sk, f.regulation_sk, f.skill_sk,
       'Tera-Typ', t.typ, f.anteil, f.rang
FROM Fact_Tera_Nutzung f JOIN Dim_Tera t ON t.tera_sk = f.tera_sk;

DROP VIEW IF EXISTS V_Teampartner;
CREATE VIEW V_Teampartner AS
SELECT
    f.pokemon_sk, f.partner_sk, f.zeit_sk, f.regulation_sk, f.skill_sk,
    p.anzeigename AS pokemon, q.anzeigename AS partner,
    q.pokedex_id AS partner_pokedex_id, q.typ1 AS partner_typ1, q.typ2 AS partner_typ2,
    z.monat_iso, r.format_code, s.elo_cutoff,
    f.synergie_wert, f.rang
FROM Fact_Teampartner f
JOIN Dim_Pokemon    p ON p.pokemon_sk    = f.pokemon_sk
JOIN Dim_Pokemon    q ON q.pokemon_sk    = f.partner_sk
JOIN Dim_Zeit       z ON z.zeit_sk       = f.zeit_sk
JOIN Dim_Regulation r ON r.regulation_sk = f.regulation_sk
JOIN Dim_Skill      s ON s.skill_sk      = f.skill_sk;
"""


def verbindung(pfad: Path | str | None = None) -> sqlite3.Connection:
    """Oeffnet eine DWH-Verbindung und legt das Schema bei Bedarf an.

    ``check_same_thread=False`` ist noetig, weil Streamlit Callbacks in wechselnden
    Threads ausfuehrt. Der Zugriff erfolgt ausschliesslich lesend aus der UI und
    schreibend aus einem einzelnen ETL-Lauf, daher ist das unkritisch.
    """
    ziel = Path(pfad) if pfad else DWH_PFAD
    if str(ziel) != ":memory:":
        datenverzeichnis_anlegen()
        ziel.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(ziel), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_DDL)
    conn.executescript(SICHTEN_DDL)
    conn.commit()
    return conn


def ist_befuellt(conn: sqlite3.Connection) -> bool:
    """Prueft, ob Stammdaten und mindestens ein Faktensatz vorliegen."""
    dim = conn.execute("SELECT COUNT(*) FROM Dim_Pokemon WHERE ist_aktuell = 1").fetchone()[0]
    fakt = conn.execute("SELECT COUNT(*) FROM Fact_Usage").fetchone()[0]
    return dim > 0 and fakt > 0


def tabellen_statistik(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Zeilenanzahl je Tabelle -- Grundlage der Ladeuebersicht in der UI."""
    tabellen = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    ergebnis = []
    for tab in tabellen:
        anzahl = conn.execute(f"SELECT COUNT(*) FROM {tab}").fetchone()[0]  # noqa: S608
        schicht = (
            "Staging / ODS" if tab.startswith("Stage_")
            else "Dimension" if tab.startswith("Dim_")
            else "Fakt" if tab.startswith("Fact_")
            else "Metadaten"
        )
        ergebnis.append({"Tabelle": tab, "Schicht": schicht, "Zeilen": anzahl})
    return ergebnis


def zuruecksetzen(conn: sqlite3.Connection, nur_fakten: bool = False) -> None:
    """Leert das DWH.

    ``nur_fakten`` behaelt die teuer geladenen PokeAPI-Stammdaten und verwirft nur
    die Bewegungsdaten -- das ist der uebliche Fall beim Neuaufbau der Zeitreihe.
    """
    fakten = [
        "Fact_Usage", "Fact_Attacken_Nutzung", "Fact_Item_Nutzung",
        "Fact_Faehigkeit_Nutzung", "Fact_Tera_Nutzung", "Fact_Teampartner",
    ]
    stamm = [
        "Dim_Pokemon", "Dim_Zeit", "Dim_Regulation", "Dim_Skill",
        "Dim_Item", "Dim_Faehigkeit", "Dim_Attacke", "Dim_Tera",
    ]
    meta = ["Stage_Smogon", "Stage_Pokeapi", "DQ_Befund", "ETL_Lauf"]

    conn.execute("PRAGMA foreign_keys = OFF")
    for tab in fakten + ([] if nur_fakten else stamm) + meta:
        conn.execute(f"DELETE FROM {tab}")  # noqa: S608
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

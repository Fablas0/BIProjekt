"""Physisches Datenmodell des Data Warehouse.

Aufbau in drei Schichten entsprechend der klassischen DWH-Architektur:

1. **Staging / Archiv** (``Stage_Pokeapi``, ``Archiv_Champions``) -- unveraenderte
   Rohdaten der Quellsysteme. Das Champions-Archiv ist dabei mehr als ein
   Zwischenspeicher: die Quelle haelt nur rund zwei Wochen vor, weshalb jeder
   gesicherte Tag dauerhaft erhalten bleibt.
2. **Core Data Warehouse** (``Dim_*`` / ``Fact_*``) -- integriertes,
   historisiertes Star-Schema.
3. **Metadaten** (``ETL_Lauf``, ``DQ_Befund``) -- Protokollierung von
   Ladelaeufen und Datenqualitaetsbefunden.

Quellsysteme
------------
* **PokeAPI** -- Stammdaten der Hauptspiele: Typen, Basiswerte, Attacken-,
  Item- und Faehigkeitseigenschaften. Champions liefert zu Items und
  Faehigkeiten nur den Namen; ihre Wirkung steht in den Hauptspielen.
* **Pokemon Champions** -- Bewegungsdaten der offiziellen Wettkampfplattform:
  taegliche Nutzungsraenge sowie Attacken, Items, Faehigkeiten, Wesen und
  Statuspunkte je Pokemon, getrennt nach Einzel- und Doppelkampf.

Messniveau
----------
Champions liefert die Nutzung eines Pokemon **ordinal** (Rang), nicht kardinal
(Anteil in Prozent). Das Datenmodell bildet das ehrlich ab: ``Fact_Champions_Usage``
fuehrt einen Rang, keine erfundene Quote. Merkmalsanteile innerhalb eines Pokemon
(welche Attacke in wie viel Prozent der Sets) sind dagegen echte Anteile und
liegen als solche in ``Fact_Champions_Merkmal``.

Historisierung
--------------
``Dim_Pokemon`` ist **bi-temporal** ausgefuehrt: ``gueltig_ab`` / ``gueltig_bis``
bilden die fachliche Gueltigkeit ab, ``ist_aktuell`` erlaubt den schnellen Zugriff
auf den Ist-Stand ohne Datumsvergleich, ``dwh_geladen_am`` haelt den technischen
Ladezeitpunkt fest. Aenderungen werden ueber ``row_hash`` erkannt. Damit sind
Balance-Anpassungen zwischen Saisons nachvollziehbar.
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
-- SCHICHT 1: STAGING UND ARCHIV
-- =====================================================================

CREATE TABLE IF NOT EXISTS Stage_Pokeapi (
    lauf_id      INTEGER NOT NULL,
    slug         TEXT    NOT NULL,
    nutzlast     TEXT    NOT NULL,          -- unveraendertes JSON der Quelle
    geladen_am   TEXT    NOT NULL,
    PRIMARY KEY (lauf_id, slug)
);

-- Rohdatenarchiv der Champions-Strecke.
--
-- Die Quelle haelt nur rund zwei Wochen vor. Ohne eigenes Archiv waere jede
-- laengere Zeitreihe unwiederbringlich verloren, sobald ein Tag aus der Quelle
-- faellt. Diese Tabelle wird deshalb ausdruecklich **nie** bereinigt.
CREATE TABLE IF NOT EXISTS Archiv_Champions (
    saison        TEXT NOT NULL,
    datum_iso     TEXT NOT NULL,
    kampfformat   TEXT NOT NULL,
    quell_name    TEXT NOT NULL,
    nutzlast      TEXT NOT NULL,            -- unveraenderte CSV-Zeilen als JSON
    archiviert_am TEXT NOT NULL,
    lauf_id       INTEGER NOT NULL,
    PRIMARY KEY (saison, datum_iso, kampfformat, quell_name)
);

CREATE INDEX IF NOT EXISTS ix_archiv_champ ON Archiv_Champions (saison, datum_iso);

-- =====================================================================
-- SCHICHT 2: CORE DATA WAREHOUSE -- DIMENSIONEN
-- =====================================================================

-- Zeitdimension mit Konsolidierungspfad Tag -> Monat -> Quartal -> Jahr.
CREATE TABLE IF NOT EXISTS Dim_Zeit (
    zeit_sk       INTEGER PRIMARY KEY,      -- JJJJMMTT
    datum_iso     TEXT    NOT NULL UNIQUE,  -- '2026-07-28'
    jahr          INTEGER NOT NULL,
    quartal       INTEGER NOT NULL,
    monat         INTEGER NOT NULL,
    tag           INTEGER NOT NULL,
    monat_iso     TEXT    NOT NULL,         -- '2026-07'
    monat_name    TEXT    NOT NULL,
    quartal_label TEXT    NOT NULL,         -- 'Q3 2026'
    tag_label     TEXT    NOT NULL,         -- '28.07.2026'
    wochentag     TEXT    NOT NULL,
    ist_letzter_tag INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_dim_zeit_monat ON Dim_Zeit (monat_iso);

-- Pokemon-Dimension, bi-temporal historisiert.
-- Konsolidierungspfad: Generation -> Spezies -> Form.
--
-- Die Basiswerte sind die Werte der Hauptreihe. Pokemon Champions zeigt im Spiel
-- bereits die daraus abgeleiteten Werte auf Turnierstufe 50 ohne Investition an;
-- diese stehen in den ``stufe50_*``-Spalten und entsprechen der Anzeige im Spiel.
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
    hp              INTEGER NOT NULL,       -- Basiswerte der Hauptreihe
    attack          INTEGER NOT NULL,
    defense         INTEGER NOT NULL,
    sp_attack       INTEGER NOT NULL,
    sp_defense      INTEGER NOT NULL,
    speed           INTEGER NOT NULL,
    stufe50_hp         INTEGER NOT NULL,    -- Anzeigewerte im Spiel, ohne Investition
    stufe50_attack     INTEGER NOT NULL,
    stufe50_defense    INTEGER NOT NULL,
    stufe50_sp_attack  INTEGER NOT NULL,
    stufe50_sp_defense INTEGER NOT NULL,
    stufe50_speed      INTEGER NOT NULL,
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

-- Quellsystem. Die Faehigkeiten stehen als Merkmale in der Dimension, damit die
-- Auswertung sie pruefen kann, statt sie fest zu verdrahten.
CREATE TABLE IF NOT EXISTS Dim_Quelle (
    quelle_sk            INTEGER PRIMARY KEY AUTOINCREMENT,
    schluessel           TEXT NOT NULL UNIQUE,
    name                 TEXT NOT NULL,
    beschreibung         TEXT NOT NULL,
    ist_offiziell        INTEGER NOT NULL DEFAULT 0,
    granularitaet_zeit   TEXT NOT NULL,
    messniveau_nutzung   TEXT NOT NULL,     -- 'ordinal' (Rang) | 'kardinal' (Quote)
    hat_partner_gewicht  INTEGER NOT NULL DEFAULT 0,
    vorhaltung_tage      INTEGER            -- wie lange die Quelle selbst archiviert
);

-- Saison bzw. Regulationszeitraum.
--
-- Zweck: Pokemon, die in einer spaeteren Saison nicht mehr zugelassen sind oder
-- deren Werte angepasst wurden, duerfen die Auswertung der aktuellen Saison nicht
-- verfaelschen. Jeder Faktensatz traegt deshalb seine Saison.
CREATE TABLE IF NOT EXISTS Dim_Saison (
    saison_sk     INTEGER PRIMARY KEY AUTOINCREMENT,
    schluessel    TEXT    NOT NULL UNIQUE,  -- 'M4'
    bezeichnung   TEXT    NOT NULL,
    quelle_sk     INTEGER NOT NULL REFERENCES Dim_Quelle (quelle_sk),
    beginn        TEXT,                     -- erster beobachteter Tag
    ende          TEXT,                     -- letzter beobachteter Tag
    ist_aktuell   INTEGER NOT NULL DEFAULT 1,
    erfasst_am    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_dim_saison_aktuell ON Dim_Saison (quelle_sk, ist_aktuell);

-- Kampfformat. ``mitnahme`` ist die Zahl der im Team-Preview zu waehlenden
-- Pokemon und damit der zentrale Parameter des Preview-Advisors.
CREATE TABLE IF NOT EXISTS Dim_Kampfformat (
    kampfformat_sk INTEGER PRIMARY KEY AUTOINCREMENT,
    schluessel     TEXT NOT NULL UNIQUE,    -- 'Singles' | 'Doubles'
    bezeichnung    TEXT NOT NULL,
    aktive_pokemon INTEGER NOT NULL,        -- 1 bzw. 2 gleichzeitig auf dem Feld
    mitnahme       INTEGER NOT NULL         -- 3 bzw. 4 aus sechs im Team-Preview
);

-- Attacken-Dimension mit Hierarchie Attacke -> Typ und Attacke -> Kategorie.
-- Quelle sind die PokeAPI-Stammdaten; Champions liefert nur den Anzeigenamen.
CREATE TABLE IF NOT EXISTS Dim_Attacke (
    attacke_sk    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,     -- kompakt, z.B. 'dragonclaw'
    anzeigename   TEXT NOT NULL,
    typ           TEXT,
    kategorie     TEXT,                     -- physical | special | status
    basisschaden  INTEGER,
    genauigkeit   INTEGER,
    prioritaet    INTEGER,
    zielbereich   TEXT,                     -- z.B. all-opponents (Flaechenattacke)
    taktik_klasse TEXT NOT NULL DEFAULT 'Offensiv'  -- Anreicherung fuer den Strategie-Radar
);

-- Item-Dimension. Quelle sind die Hauptspiele ueber die PokeAPI: Champions
-- liefert nur den Anzeigenamen des getragenen Items, nicht seine Wirkung.
--
-- Ohne diese Dimension bliebe die Itemauswertung eine Zeichenkette. Erst
-- Kategorie und Wirkungsklasse machen aus "Focus Sash" die Aussage "ein Item,
-- das einen Treffer ueberleben laesst" -- und erst damit ist der Schadens-
-- rechner in der Lage, das Item zu verrechnen.
CREATE TABLE IF NOT EXISTS Dim_Item (
    item_sk        INTEGER PRIMARY KEY AUTOINCREMENT,
    slug           TEXT NOT NULL UNIQUE,    -- kompakt, z.B. 'focussash'
    pokeapi_slug   TEXT,                    -- 'focus-sash'
    anzeigename    TEXT NOT NULL,
    kategorie      TEXT,                    -- Kategorie der PokeAPI
    wirkung_klasse TEXT NOT NULL DEFAULT 'Sonstige',  -- Anreicherung
    effekt_kurz    TEXT,
    ist_kampfrelevant INTEGER NOT NULL DEFAULT 1,
    fling_staerke  INTEGER
);

-- Faehigkeiten-Dimension, ebenfalls aus den Hauptspielen.
CREATE TABLE IF NOT EXISTS Dim_Faehigkeit (
    faehigkeit_sk  INTEGER PRIMARY KEY AUTOINCREMENT,
    slug           TEXT NOT NULL UNIQUE,    -- kompakt, z.B. 'intimidate'
    pokeapi_slug   TEXT,
    anzeigename    TEXT NOT NULL,
    wirkung_klasse TEXT NOT NULL DEFAULT 'Sonstige',  -- Anreicherung
    effekt_kurz    TEXT,
    generation     INTEGER
);

-- =====================================================================
-- SCHICHT 2: CORE DATA WAREHOUSE -- FAKTEN
-- =====================================================================

-- Zentrale Faktentabelle.
-- Granularitaet: ein Pokemon je Kampfformat, Saison und Tag.
--
-- Die Kennzahl ist ein **Rang**, keine Quote. Die Quelle liefert keine
-- Nutzungsquote; ein Platzhalter waere eine Erfindung. Ergaenzt wird ein auf
-- 0 bis 100 normiertes Rangperzentil, das Tage mit unterschiedlich vielen
-- erfassten Pokemon vergleichbar macht und ausdruecklich abgeleitet ist.
CREATE TABLE IF NOT EXISTS Fact_Champions_Usage (
    pokemon_sk     INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk        INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    saison_sk      INTEGER NOT NULL REFERENCES Dim_Saison (saison_sk),
    kampfformat_sk INTEGER NOT NULL REFERENCES Dim_Kampfformat (kampfformat_sk),
    quelle_sk      INTEGER NOT NULL REFERENCES Dim_Quelle (quelle_sk),
    rang           INTEGER NOT NULL,        -- Kennzahl (ordinal)
    rang_perzentil REAL    NOT NULL,        -- Anreicherung: Rang auf 0-100 normiert
    erfasste_pokemon INTEGER NOT NULL,      -- Bezugsgroesse des Rangs an diesem Tag
    etl_lauf_id    INTEGER NOT NULL,
    PRIMARY KEY (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk)
);

CREATE INDEX IF NOT EXISTS ix_fact_champ_usage_zeit
    ON Fact_Champions_Usage (saison_sk, kampfformat_sk, zeit_sk, rang);

-- Merkmalsfakt. Die Quelle liefert Attacken, Items, Faehigkeiten, Wesen und
-- Statuspunkte in einer einheitlichen Satzstruktur; sie wird hier beibehalten,
-- statt sie kuenstlich auf fuenf Tabellen aufzuteilen.
--
-- ``anteil`` ist hier ein **echter Anteil** in Prozent: der Anteil der Sets eines
-- Pokemon, die dieses Merkmal fuehren. Auf dieser Ebene sind daher auch
-- kardinale Kennzahlen wie ein Konzentrationsindex zulaessig.
CREATE TABLE IF NOT EXISTS Fact_Champions_Merkmal (
    pokemon_sk     INTEGER NOT NULL REFERENCES Dim_Pokemon (pokemon_sk),
    zeit_sk        INTEGER NOT NULL REFERENCES Dim_Zeit (zeit_sk),
    saison_sk      INTEGER NOT NULL REFERENCES Dim_Saison (saison_sk),
    kampfformat_sk INTEGER NOT NULL REFERENCES Dim_Kampfformat (kampfformat_sk),
    kategorie      TEXT    NOT NULL,        -- move | held_item | ability | nature | spread | teammate
    rang           INTEGER NOT NULL,
    bezeichnung    TEXT    NOT NULL,
    anteil         REAL,                    -- Kennzahl in %; bei Teampartnern leer
    attacke_sk     INTEGER REFERENCES Dim_Attacke (attacke_sk),        -- kategorie='move'
    item_sk        INTEGER REFERENCES Dim_Item (item_sk),              -- kategorie='held_item'
    faehigkeit_sk  INTEGER REFERENCES Dim_Faehigkeit (faehigkeit_sk),  -- kategorie='ability'
    -- Nur bei kategorie = 'spread' belegt
    wesen             TEXT,
    punkte_hp         INTEGER,
    punkte_attack     INTEGER,
    punkte_defense    INTEGER,
    punkte_sp_attack  INTEGER,
    punkte_sp_defense INTEGER,
    punkte_speed      INTEGER,
    punkte_summe      INTEGER,
    -- Anreicherung: die tatsaechlichen Statuswerte auf Turnierstufe 50
    wert_hp           INTEGER,
    wert_attack       INTEGER,
    wert_defense      INTEGER,
    wert_sp_attack    INTEGER,
    wert_sp_defense   INTEGER,
    wert_speed        INTEGER,
    PRIMARY KEY (pokemon_sk, zeit_sk, saison_sk, kampfformat_sk, kategorie, rang)
);

CREATE INDEX IF NOT EXISTS ix_fact_champ_merkmal
    ON Fact_Champions_Merkmal (saison_sk, kampfformat_sk, kategorie, pokemon_sk);

-- =====================================================================
-- SCHICHT 3: METADATEN
-- =====================================================================

CREATE TABLE IF NOT EXISTS ETL_Lauf (
    lauf_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    gestartet_am     TEXT    NOT NULL,
    beendet_am       TEXT,
    quelle           TEXT    NOT NULL,      -- 'PokeAPI' | 'Champions'
    parameter        TEXT,
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
    f.pokemon_sk, f.zeit_sk, f.saison_sk, f.kampfformat_sk,
    p.pokedex_id, p.anzeigename, p.slug, p.spezies, p.generation,
    p.typ1, p.typ2, p.typ_kombination,
    p.hp, p.attack, p.defense, p.sp_attack, p.sp_defense, p.speed,
    p.stufe50_hp, p.stufe50_attack, p.stufe50_defense,
    p.stufe50_sp_attack, p.stufe50_sp_defense, p.stufe50_speed,
    p.basiswert_summe, p.rolle, p.offensiv_profil, p.speed_klasse, p.resistenz_wert,
    z.datum_iso, z.tag_label, z.monat_iso, z.monat_name, z.jahr, z.quartal_label,
    z.wochentag, z.ist_letzter_tag,
    s.schluessel AS saison, s.bezeichnung AS saison_bezeichnung,
    s.ist_aktuell AS saison_aktuell,
    k.schluessel AS kampfformat, k.bezeichnung AS kampfformat_name,
    k.mitnahme, k.aktive_pokemon,
    q.name AS quelle, q.messniveau_nutzung,
    f.rang, f.rang_perzentil, f.erfasste_pokemon
FROM Fact_Champions_Usage f
JOIN Dim_Pokemon     p ON p.pokemon_sk     = f.pokemon_sk
JOIN Dim_Zeit        z ON z.zeit_sk        = f.zeit_sk
JOIN Dim_Saison      s ON s.saison_sk      = f.saison_sk
JOIN Dim_Kampfformat k ON k.kampfformat_sk = f.kampfformat_sk
JOIN Dim_Quelle      q ON q.quelle_sk      = f.quelle_sk;

-- Juengster Stand je Saison und Format -- Grundlage aller Auswertungen, die den
-- aktuellen Zustand des Metagames brauchen.
DROP VIEW IF EXISTS V_Usage_Aktuell;
CREATE VIEW V_Usage_Aktuell AS
SELECT u.*
FROM V_Usage u
JOIN (
    SELECT saison_sk, kampfformat_sk, MAX(zeit_sk) AS zeit_sk
    FROM Fact_Champions_Usage GROUP BY saison_sk, kampfformat_sk
) neueste
  ON neueste.saison_sk      = u.saison_sk
 AND neueste.kampfformat_sk = u.kampfformat_sk
 AND neueste.zeit_sk        = u.zeit_sk
WHERE u.saison_aktuell = 1;

DROP VIEW IF EXISTS V_Merkmal;
CREATE VIEW V_Merkmal AS
SELECT
    m.pokemon_sk, m.zeit_sk, m.saison_sk, m.kampfformat_sk,
    p.anzeigename, p.slug, p.pokedex_id, p.typ1, p.typ2,
    z.datum_iso, z.monat_iso,
    s.schluessel AS saison, s.ist_aktuell AS saison_aktuell,
    k.schluessel AS kampfformat,
    m.kategorie, m.rang, m.bezeichnung, m.anteil,
    m.wesen, m.punkte_hp, m.punkte_attack, m.punkte_defense,
    m.punkte_sp_attack, m.punkte_sp_defense, m.punkte_speed, m.punkte_summe,
    m.wert_hp, m.wert_attack, m.wert_defense,
    m.wert_sp_attack, m.wert_sp_defense, m.wert_speed,
    a.typ AS attacke_typ, a.kategorie AS attacke_kategorie,
    a.basisschaden, a.prioritaet, a.zielbereich, a.taktik_klasse,
    i.wirkung_klasse AS item_klasse, i.kategorie AS item_kategorie,
    i.effekt_kurz AS item_effekt,
    fa.wirkung_klasse AS faehigkeit_klasse, fa.effekt_kurz AS faehigkeit_effekt
FROM Fact_Champions_Merkmal m
JOIN Dim_Pokemon     p ON p.pokemon_sk     = m.pokemon_sk
JOIN Dim_Zeit        z ON z.zeit_sk        = m.zeit_sk
JOIN Dim_Saison      s ON s.saison_sk      = m.saison_sk
JOIN Dim_Kampfformat k ON k.kampfformat_sk = m.kampfformat_sk
LEFT JOIN Dim_Attacke    a  ON a.attacke_sk    = m.attacke_sk
LEFT JOIN Dim_Item       i  ON i.item_sk       = m.item_sk
LEFT JOIN Dim_Faehigkeit fa ON fa.faehigkeit_sk = m.faehigkeit_sk;

DROP VIEW IF EXISTS V_Merkmal_Aktuell;
CREATE VIEW V_Merkmal_Aktuell AS
SELECT m.*
FROM V_Merkmal m
JOIN (
    SELECT saison_sk, kampfformat_sk, MAX(zeit_sk) AS zeit_sk
    FROM Fact_Champions_Merkmal GROUP BY saison_sk, kampfformat_sk
) neueste
  ON neueste.saison_sk      = m.saison_sk
 AND neueste.kampfformat_sk = m.kampfformat_sk
 AND neueste.zeit_sk        = m.zeit_sk
WHERE m.saison_aktuell = 1;
"""


class Verbindung(sqlite3.Connection):
    """Datenbankverbindung, die die gewaehlte Saison mitfuehrt.

    Die Analyseschicht filtert jede Abfrage auf eine Saison. Diese Auswahl ist
    eine Entscheidung der Oberflaeche, nicht der Abfrage -- sie als Parameter
    durch ueber zwanzig Funktionen zu reichen haette jede Signatur und jede
    Aufrufstelle beruehrt, ohne dass eine davon inhaltlich etwas mit der Wahl
    zu tun hat.

    ``sqlite3.Connection`` nimmt von sich aus keine zusaetzlichen Merkmale auf;
    die Ableitung schafft genau eines. ``None`` bedeutet "die laufende Saison"
    und ist damit das bisherige Verhalten.

    Zu beachten: die Verbindung wird von der Anwendung gemeinsam genutzt. Bei
    mehreren gleichzeitigen Betrachtern mit unterschiedlicher Saisonwahl waere
    sie zu trennen -- fuer den vorliegenden Einsatz mit einer Handvoll Nutzern
    ist das nicht erforderlich.
    """

    saison_wahl: str | None = None


def verbindung(pfad: Path | str | None = None) -> Verbindung:
    """Oeffnet eine DWH-Verbindung und legt das Schema bei Bedarf an.

    ``check_same_thread=False`` ist noetig, weil Streamlit Callbacks in wechselnden
    Threads ausfuehrt. Der Zugriff erfolgt ausschliesslich lesend aus der UI und
    schreibend aus einem einzelnen ETL-Lauf, daher ist das unkritisch.
    """
    ziel = Path(pfad) if pfad else DWH_PFAD
    if str(ziel) != ":memory:":
        datenverzeichnis_anlegen()
        ziel.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(ziel), check_same_thread=False, timeout=30,
                           factory=Verbindung)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_DDL)
    _spalten_nachziehen(conn)
    # Die Sichten entstehen bei jedem Verbindungsaufbau neu und beruecksichtigen
    # damit nachgezogene Spalten sofort.
    conn.executescript(SICHTEN_DDL)
    conn.commit()
    return conn


# Spalten, die spaeter zu einer bestehenden Tabelle hinzugekommen sind.
# ``CREATE TABLE IF NOT EXISTS`` legt eine vorhandene Tabelle nicht neu an --
# eine bestehende Datenbank bekaeme die neuen Spalten sonst nie. Ein
# Loeschen und Neuanlegen scheidet aus: ``Archiv_Champions`` haelt Tagesstaende,
# die die Quelle nicht mehr fuehrt.
NACHGEREICHTE_SPALTEN: dict[str, dict[str, str]] = {
    "Fact_Champions_Merkmal": {
        "item_sk": "INTEGER REFERENCES Dim_Item (item_sk)",
        "faehigkeit_sk": "INTEGER REFERENCES Dim_Faehigkeit (faehigkeit_sk)",
    },
}


def _spalten_nachziehen(conn: sqlite3.Connection) -> list[str]:
    """Ergaenzt fehlende Spalten in bereits bestehenden Tabellen.

    Bewusst schlicht gehalten: es wird ausschliesslich hinzugefuegt, nie
    umbenannt oder entfernt. Damit bleibt der Schritt gefahrlos wiederholbar
    und kann bei jedem Verbindungsaufbau laufen. Fuer mehr braeuchte es ein
    echtes Migrationswerkzeug -- fuer ein Projekt mit einer Datenbankdatei,
    die sich jederzeit aus dem Archiv neu aufbauen laesst, waere das
    unverhaeltnismaessig.
    """
    ergaenzt: list[str] = []
    for tabelle, spalten in NACHGEREICHTE_SPALTEN.items():
        vorhanden = {z[1] for z in conn.execute(f"PRAGMA table_info({tabelle})")}
        if not vorhanden:
            continue  # Tabelle wurde soeben angelegt und ist vollstaendig.
        for spalte, typ in spalten.items():
            if spalte not in vorhanden:
                conn.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")  # noqa: S608
                ergaenzt.append(f"{tabelle}.{spalte}")
    if ergaenzt:
        conn.commit()
    return ergaenzt


def ist_befuellt(conn: sqlite3.Connection) -> bool:
    """Prueft, ob Stammdaten und mindestens ein Faktensatz vorliegen."""
    dim = conn.execute("SELECT COUNT(*) FROM Dim_Pokemon WHERE ist_aktuell = 1").fetchone()[0]
    fakt = conn.execute("SELECT COUNT(*) FROM Fact_Champions_Usage").fetchone()[0]
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
            "Staging / Archiv" if tab.startswith(("Stage_", "Archiv_"))
            else "Dimension" if tab.startswith("Dim_")
            else "Fakt" if tab.startswith("Fact_")
            else "Metadaten"
        )
        ergebnis.append({"Tabelle": tab, "Schicht": schicht, "Zeilen": anzahl})
    return ergebnis


def zuruecksetzen(conn: sqlite3.Connection, nur_fakten: bool = False,
                  archiv_verwerfen: bool = False) -> None:
    """Leert das DWH.

    ``nur_fakten`` behaelt die teuer geladenen PokeAPI-Stammdaten und verwirft nur
    die Bewegungsdaten.

    ``Archiv_Champions`` bleibt standardmaessig **erhalten**, auch beim
    vollstaendigen Zuruecksetzen. Die Quelle haelt nur rund zwei Wochen vor;
    einmal verworfene Tage sind endgueltig verloren und nicht nachladbar.
    Das Verwerfen muss deshalb ausdruecklich verlangt werden.
    """
    fakten = ["Fact_Champions_Usage", "Fact_Champions_Merkmal"]
    stamm = ["Dim_Pokemon", "Dim_Zeit", "Dim_Attacke", "Dim_Item", "Dim_Faehigkeit",
             "Dim_Saison", "Dim_Kampfformat", "Dim_Quelle"]
    meta = ["Stage_Pokeapi", "DQ_Befund", "ETL_Lauf"]

    conn.execute("PRAGMA foreign_keys = OFF")
    for tab in fakten + ([] if nur_fakten else stamm) + meta:
        conn.execute(f"DELETE FROM {tab}")  # noqa: S608
    if archiv_verwerfen:
        conn.execute("DELETE FROM Archiv_Champions")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def archiv_umfang(conn: sqlite3.Connection) -> dict[str, object]:
    """Kennzahlen des Champions-Rohdatenarchivs.

    Macht sichtbar, wie viel Historie ueber die Vorhaltezeit der Quelle hinaus
    bereits gesichert ist -- der eigentliche Mehrwert des Archivs.
    """
    zeile = conn.execute("""
        SELECT COUNT(*) AS saetze,
               COUNT(DISTINCT datum_iso) AS tage,
               COUNT(DISTINCT saison) AS saisons,
               MIN(datum_iso) AS erster_tag,
               MAX(datum_iso) AS letzter_tag
        FROM Archiv_Champions
    """).fetchone()
    return dict(zeile) if zeile else {}

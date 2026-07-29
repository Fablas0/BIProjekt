# VGC Business Intelligence

Business-Intelligence-Lösung für das kompetitive Pokémon-Doppelkampfformat (VGC).
Das Projekt führt Stammdaten der PokeAPI und die monatlichen Nutzungsstatistiken
von Smogon in einem historisierten Data Warehouse zusammen und stellt darauf ein
Dashboard mit Kennzahlen, OLAP-Auswertung und Team-Analysen bereit.

Hochschulprojekt im Modul *Business Intelligence*, Duales Studium
Wirtschaftsinformatik, WiSe 2025/26.

---

## Fachliche Fragestellung

Wer ein Team für ein VGC-Turnier vorbereitet, trifft Entscheidungen unter
Unsicherheit: Welche Pokémon dominieren das Format? Wie entwickelt sich das
Metagame? Wo ist das eigene Team angreifbar, und welche Gegner sind ihm
gefährlich? Die Antworten stecken in öffentlich verfügbaren Daten — aber verteilt
über zwei Quellsysteme, in unterschiedlichen Formaten und ohne gemeinsamen
Schlüssel.

Die Lösung beantwortet fünf Leitfragen:

| Leitfrage | Umsetzung |
|---|---|
| Wie sieht das Format aktuell aus? | Meta-Cockpit mit Kennzahlen und Nutzungsverteilung |
| Wohin entwickelt es sich? | Zeitreihe über mehrere Monate, Momentum-Kennzahl, Konzentrationsindex |
| Was spielt der Gegner? | Gegner-Scouting mit erwarteter Konfiguration und Strategie-Erkennung |
| Wo ist mein Team verwundbar? | Defensivprofil, gewichtet mit der tatsächlichen Meta-Häufigkeit |
| Welcher Partner passt noch? | Team-Builder mit Synergievorschlägen aus dem Beziehungsfakt |

---

## Architektur

```
┌──────────────┐   ┌──────────────┐
│   PokeAPI    │   │ Smogon Stats │      Quellsysteme
│ (REST/JSON)  │   │  (JSON-Dump) │
└──────┬───────┘   └──────┬───────┘
       │  EXTRACT         │              parallelisiert, mit Wiederholungslogik
       └────────┬─────────┘
                ▼
       ┌─────────────────┐
       │  Stage_Pokeapi  │              Schicht 1: Staging / ODS
       │  Stage_Smogon   │              unveränderte Rohnutzlast
       └────────┬────────┘
                │  TRANSFORM
                │  Filterung · Harmonisierung · Aggregation · Anreicherung
                ▼
   ┌────────────────────────────┐
   │   Core Data Warehouse      │       Schicht 2: Galaxy-Schema
   │   8 Dimensionen            │       Dim_Pokemon bi-temporal historisiert
   │   6 Faktentabellen         │       Fakten nicht-volatil (insert/upsert)
   └────────────┬───────────────┘
                │
       ┌────────┴────────┐
       ▼                 ▼
┌─────────────┐   ┌──────────────┐
│ ETL_Lauf    │   │  Analytics   │      Schicht 3: Metadaten
│ DQ_Befund   │   │  KPI · OLAP  │      + Analyseschicht
└─────────────┘   └──────┬───────┘
                         ▼
                  ┌─────────────┐
                  │  Streamlit  │       Präsentationsschicht
                  └─────────────┘
```

### Datenmodell — Galaxy-Schema

Sechs Faktentabellen teilen sich die **konformen Dimensionen** `Dim_Pokemon`,
`Dim_Zeit`, `Dim_Regulation` und `Dim_Skill`:

| Faktentabelle | Granularität | Kennzahlen |
|---|---|---|
| `Fact_Usage` | Pokémon × Format × ELO × Monat | Nutzungsanteil, Teamnennungen, GXE, Rang |
| `Fact_Attacken_Nutzung` | … × Attacke | Anteil der Sets |
| `Fact_Item_Nutzung` | … × Item | Anteil der Sets |
| `Fact_Faehigkeit_Nutzung` | … × Fähigkeit | Anteil der Sets |
| `Fact_Tera_Nutzung` | … × Tera-Typ | Anteil der Sets |
| `Fact_Teampartner` | … × Partner-Pokémon | Synergiewert (Ko-Nutzung) |

**Dimensionshierarchien** (Konsolidierungspfade für Drill-Down und Roll-Up):

- Zeit: `Jahr → Quartal → Monat`
- Pokémon: `Generation → Spezies → Form`
- Typ: `Primärtyp → Typ-Kombination`
- Rolle: `Offensivprofil → Teamrolle → Speed-Klasse`
- Format: `Saison → Regulation → Spielmodus`

### Historisierung

`Dim_Pokemon` ist **bi-temporal** ausgeführt — die Kombination aus
Delta-Verfahren und Gültigkeitszeiträumen:

| Feld | Zweck |
|---|---|
| `gueltig_ab` / `gueltig_bis` | fachlicher Gültigkeitszeitraum |
| `ist_aktuell` | schneller Zugriff auf den Ist-Stand ohne Datumsvergleich |
| `dwh_geladen_am` | technischer Ladezeitpunkt |
| `row_hash` | Änderungserkennung über die fachlich relevanten Attribute |

Ändert sich ein Attribut, wird der bisherige Satz zum Vortag abgegrenzt und ein
neuer Zeitraum eröffnet. Auswertungen zu einem historischen Stichtag bleiben
dadurch möglich.

Die Faktentabellen sind **nicht-volatil** (Inmon): es wird ausschließlich
eingefügt oder auf dem fachlichen Schlüssel aktualisiert. Ein wiederholter Lauf
desselben Monats ist idempotent und lässt die übrige Zeitreihe unberührt.

---

## Kennzahlen

**Absolut** — erfasste Partien, Teamnennungen, Anzahl geführter Pokémon.

**Relativ** — Nutzungsanteil in Prozent, Anteil einer Attacke an den Sets,
Anteil eines Archetyps am Metagame.

**Zeitbezogen** — Momentum (Veränderung gegenüber dem Vormonat), Rangänderung,
Entwicklung der Konzentration.

**Verdichtet** — Herfindahl-Hirschman-Index der Nutzungsverteilung als Maß der
Meta-Konzentration; Top-10-Anteil; Risikokennzahl je Angriffstyp aus
ungedeckten Anfälligkeiten × Meta-Häufigkeit.

**Abgeleitet (Anreicherung)** — Basiswertsumme, Offensivprofil, Teamrolle,
Speed-Klasse, defensive Resistenzkennzahl, taktische Klasse einer Attacke,
Bedrohungsindex.

---

## OLAP-Operationen

Der Würfel wird relational gehalten (ROLAP). Alle Operationen sind im
OLAP-Explorer bedienbar:

| Operation | Bedienung |
|---|---|
| Slice | Filter auf einer Dimension |
| Dice | Filter auf mehreren Dimensionen |
| Drill-Down / Roll-Up | Schaltflächen am Konsolidierungspfad |
| Pivot (Rotation) | Achsen vertauschen |
| Split / Merge | Spaltenachse hinzunehmen bzw. entfernen |

Jede Kennzahl trägt ihre Aggregationsregel: Nutzungsanteile sind additiv,
GXE-Werte nicht — dort ist nur das Maximum fachlich sinnvoll.

---

## Datenqualität

Zweistufig geprüft:

**Während des Ladens** (`bi.etl.transform`) — Vollständigkeit von Pflichtfeldern,
Wertebereiche, Auflösbarkeit der Bezeichner, Eindeutigkeit des Schlüssels,
Plausibilität der Gewichtssummen. Befunde werden nach **Mangel 1. Klasse**
(automatisch erkennbar und korrigierbar) und **Mangel 2. Klasse** (erkennbar,
erfordert fachliche Entscheidung) unterschieden und in `DQ_Befund` protokolliert.

**Nach dem Laden** (`bi.quality`) — zehn Regeln auf dem Gesamtbestand entlang der
Qualitätsdimensionen Vollständigkeit, Konsistenz, Eindeutigkeit, Genauigkeit und
Aktualität. Der verdichtete **Qualitätsindex** dient als Qualitätstor in der CI.

### Befunde aus der Quellanalyse

Drei Punkte, die die Umsetzung geprägt haben:

1. **`Checks and Counters` ist in den VGC-Daten durchgängig leer.** Geprüft über
   alle geladenen Monate für sämtliche erfassten Pokémon. Eine Auswertung, die
   sich darauf stützt, liefert nie ein Ergebnis, ohne dass ein Fehler sichtbar
   würde. Die Bedrohungsanalyse wird deshalb aus Typen-Regelbasis, Basiswerten,
   tatsächlich gespielten Attacken und Nutzungshäufigkeit **selbst berechnet**.

2. **Es gibt keine Siegquote je Pokémon.** Die Quelle liefert stattdessen das
   *Viability Ceiling* (GXE-Werte der besten, der oberen 25 % und der mittleren
   Spieler). Diese Kennzahl wird geführt, statt eine nicht belegbare Siegquote
   auszuweisen.

3. **19 von 245 Bezeichnern sind nicht regelbasiert auflösbar.** Smogon führt die
   dominante Form ohne Suffix (`Landorus`), die PokeAPI benennt jede Form explizit
   (`landorus-incarnate`). Ein Rückfall auf den Namensteil vor dem ersten
   Bindestrich würde `Ogerpon-Cornerstone`, `-Hearthflame` und `-Wellspring` auf
   dieselbe Entität werfen — bei unterschiedlichem Typ und unterschiedlicher Rolle.
   Gelöst über eine explizite Zuordnungstabelle; verbleibende Nicht-Treffer werden
   protokolliert statt geraten. Aktuelle Trefferquote: **100 %**.

---

## Installation und Betrieb

```bash
git clone https://github.com/Fablas0/BIProjekt.git
cd BIProjekt
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Beim ersten Start ist das Data Warehouse leer. Unter *ETL & Datenqualität*
nacheinander **Stammdaten laden** und **Bewegungsdaten laden** ausführen — der
vollständige Aufbau dauert rund 20 Sekunden.

### Kopfloser Betrieb

```bash
python -m scripts.etl_lauf --elo 1760 --monate 6
```

```bash
python -m scripts.qualitaet_pruefen --mindestindex 90
```

### Tests

```bash
pip install -r requirements-dev.txt && pytest -q && ruff check .
```

Die Oberflächentests überspringen sich selbst, solange kein befülltes Data
Warehouse vorliegt.

---

## CI/CD

Zwei GitHub-Actions-Workflows:

**`ci.yml`** — bei jedem Push und Pull Request: Ruff-Linting, Tests auf Python
3.10 und 3.12, und auf dem Hauptzweig zusätzlich ein Integrationslauf gegen die
echten Quellsysteme mit anschließendem Qualitätstor.

**`etl_refresh.yml`** — Operationalisierung: monatlich am 5. um 04:00 Uhr, wenn
Smogon die Auswertung des Vormonats veröffentlicht hat. Baut das Warehouse neu
auf, prüft die Qualität und stellt das Ergebnis als Artefakt bereit.

### Deployment

Die Anwendung ist für **Streamlit Community Cloud** ausgelegt: Repository
verbinden, `app.py` als Einstiegspunkt wählen, `requirements.txt` wird automatisch
installiert. Die Datenbank wird im Container über die Oberfläche aufgebaut; das
Verzeichnis `data/` ist bewusst nicht versioniert.

---

## Projektstruktur

```
├── app.py                        Einstiegspunkt (Streamlit)
├── src/bi/
│   ├── config.py                 zentrale Konfiguration
│   ├── typechart.py              Typen-Regelbasis
│   ├── warehouse.py              Schema-DDL, Sichten, Verbindung
│   ├── quality.py                Qualitätsregeln auf dem Bestand
│   ├── etl/
│   │   ├── extract.py            Datenabzug aus beiden Quellsystemen
│   │   ├── mapping.py            Harmonisierung der Bezeichner
│   │   ├── transform.py          Filterung · Aggregation · Anreicherung
│   │   ├── load.py               Historisierung, Faktenladung, Protokoll
│   │   └── pipeline.py           Orchestrierung der Ladeläufe
│   ├── analytics/
│   │   ├── kpi.py                Kennzahlen
│   │   ├── olap.py               Würfeloperationen
│   │   └── threat.py             Bedrohungs- und Abdeckungsanalyse
│   └── ui/                       sechs Seitenmodule + gemeinsame Bausteine
├── scripts/                      kopflose ETL- und Prüfläufe
├── tests/                        92 Tests
└── .github/workflows/            CI und geplanter Refresh
```

---

## Zuordnung zum Projektbericht

| Kapitel | Fundstelle im Code |
|---|---|
| Problem- und Datenbeschreibung | dieses README, `bi/etl/extract.py` |
| ETL | `bi/etl/` — je ein Modul pro Prozessschritt |
| Datenmodellierung | `bi/warehouse.py` (DDL mit Begründungen) |
| Datenanalyse | `bi/analytics/kpi.py`, `bi/analytics/threat.py` |
| Datenvisualisierung / Dashboard | `bi/ui/` |
| Datenqualität | `bi/quality.py`, `bi/etl/transform.py` |
| Operationalisierung | `scripts/`, `.github/workflows/` |

---

## Quellen und Rechtliches

- [PokeAPI](https://pokeapi.co) — Stammdaten
- [Smogon Usage Statistics](https://www.smogon.com/stats/) — Bewegungsdaten

Rein akademisches Projekt ohne kommerzielle Nutzung. Es besteht keine Verbindung
zu Nintendo, Game Freak, The Pokémon Company oder Smogon.

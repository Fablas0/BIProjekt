# VGC Business Intelligence

Business-Intelligence-Lösung für **Pokémon Champions**, die seit April 2026
offizielle Wettkampfplattform des Pokémon-Turnierbetriebs.

Das Projekt lädt die täglichen Ranked-Daten von Champions, reichert sie mit
Stammdaten der PokeAPI an, archiviert sie dauerhaft in einem historisierten Data
Warehouse und stellt darauf ein Dashboard mit Kennzahlen, OLAP-Auswertung,
Team-Analysen und einem Team-Preview-Advisor bereit.

**Live: <https://biprojekt-9uepcwtgxhxxmgkyv8furo.streamlit.app>**

Hochschulprojekt im Modul *Business Intelligence*, Duales Studium
Wirtschaftsinformatik, WiSe 2025/26.

---

## Fachliche Fragestellung

Wer ein Team für ein VGC-Turnier vorbereitet, trifft Entscheidungen unter
Unsicherheit: Welche Pokémon dominieren das Format? Wohin bewegt es sich? Wo ist
das eigene Team angreifbar? Und — die Frage, die unter Zeitdruck fällt — welche
vier der sechs Pokémon nehme ich im Team-Preview mit?

| Leitfrage | Umsetzung |
|---|---|
| Wie sieht das Format aktuell aus? | Meta-Cockpit mit Rangliste und Kennzahlen |
| Wie stabil ist es? | Rangkorrelation nach Spearman, Top-N-Fluktuation |
| Wer bewegt sich? | Rangveränderung gegenüber einem früheren Tag |
| Wer hält sich dauerhaft oben? | Verweildauer in der Spitzengruppe |
| Was spielt der Gegner? | Gegner-Scouting mit erwarteter Konfiguration |
| Wo ist mein Team verwundbar? | Defensivprofil, gewichtet mit der Meta-Präsenz |
| Wer handelt zuerst? | Speed-Tiers aus den real gespielten Statuspunkten |
| **Welche 4 nehme ich mit?** | **Team-Preview-Advisor** |

---

## Architektur

```
┌──────────────────┐        ┌──────────────────────┐
│     PokeAPI      │        │  Pokémon Champions   │   Quellsysteme
│   (Stammdaten)   │        │  (Ranked, täglich)   │
└────────┬─────────┘        └──────────┬───────────┘
         │      EXTRACT                │   parallelisiert, mit Retry
         └───────────┬─────────────────┘
                     ▼
        ┌────────────────────────┐
        │  Stage_Pokeapi         │        Schicht 1: Staging + Archiv
        │  Archiv_Champions      │        wird NIE geleert
        └───────────┬────────────┘
                    │  TRANSFORM
                    │  Filterung · Harmonisierung · Anreicherung
                    ▼
        ┌────────────────────────┐
        │  Core Data Warehouse   │        Schicht 2: Star-Schema
        │  7 Dimensionen         │        Dim_Pokemon bi-temporal
        │  2 Faktentabellen      │        Fakten nicht-volatil
        └───────────┬────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌──────────────┐        ┌──────────────┐
│  ETL_Lauf    │        │  Analytics   │        Schicht 3: Metadaten
│  DQ_Befund   │        │  KPI · OLAP  │        + Analyseschicht
│  Quelle_Stand│        │              │        was die Quelle anbot
└──────────────┘        └──────┬───────┘
                               ▼
                        ┌─────────────┐
                        │  Streamlit  │        Präsentationsschicht
                        └─────────────┘
```

### Datenmodell

| Faktentabelle | Granularität | Kennzahlen |
|---|---|---|
| `Fact_Champions_Usage` | Pokémon × Kampfformat × Saison × **Tag** | Nutzungsrang, Rangperzentil |
| `Fact_Champions_Merkmal` | … × Merkmal | Anteil, Statuspunkte, berechnete Statuswerte |

Der Merkmalsfakt hält Attacken, Items, Fähigkeiten, Wesen, Punkteverteilungen und
Teampartner in einer Satzstruktur — genau so, wie die Quelle sie liefert. Eine
künstliche Aufteilung auf sechs Tabellen hätte die Struktur der Quelle verdeckt,
ohne etwas zu gewinnen.

**Konforme Dimensionen:** `Dim_Pokemon`, `Dim_Zeit`, `Dim_Saison`,
`Dim_Kampfformat`, `Dim_Quelle`, `Dim_Attacke`.

**Dimensionshierarchien** (Konsolidierungspfade für Drill-Down und Roll-Up):

- Zeit: `Jahr → Quartal → Monat → Tag`
- Pokémon: `Generation → Pokémon`
- Typ: `Primärtyp → Typ-Kombination`
- Rolle: `Offensivprofil → Teamrolle → Speed-Klasse`
- Format: `Saison → Kampfformat`

---

## Das Messniveau bestimmt die Kennzahl

**Der zentrale Befund der Datenanalyse.** Champions gibt die Nutzung eines
Pokémon als **Rang** aus, nicht als Anteil. Das ist eine ordinale Größe: Rang 1
ist besser als Rang 2, aber *um wie viel* sagt die Zahl nicht.

Damit sind Summen und Mittelwerte über Ränge fachlich nicht belastbar. Ein
Herfindahl-Index etwa, der quadrierte Anteile aufsummiert, lässt sich darauf
**nicht** anwenden. Die Kennzahlen sind deshalb konsequent auf zulässige
Statistiken für Rangdaten ausgelegt:

| Fragestellung | Kennzahl | Warum zulässig |
|---|---|---|
| Wer steigt, wer fällt? | Rangdifferenz zum Vergleichstag | Differenzen von Rängen sind interpretierbar |
| Wie stabil ist das Format? | **Spearman-Rangkorrelation** | genau für ordinale Daten definiert |
| Wie fest ist die Spitze? | Top-N-Fluktuation | reine Mengenoperation |
| Wer hält sich oben? | Verweildauer in Tagen | Zählung, keine Verrechnung |

Auf der **Merkmalsebene** — welche Attacke in wie viel Prozent der Sets vorkommt —
liefert die Quelle dagegen echte Anteile. Dort ist der Herfindahl-Index zulässig
und wird eingesetzt: als Maß für die Vorhersagbarkeit eines Sets.

Zwei Tests sichern das strukturell ab: der Kennzahlenkatalog des OLAP-Explorers
darf keine Summenaggregation über einen Rang anbieten, und ein Anteil in Prozent
entsteht nur bei additiven Kennzahlen.

Die zweite Regel ist teuer erkauft. Der Explorer wies den Anteil zuvor für jede
Kennzahl aus — ein Rang wurde durch die Summe aller Ränge geteilt, und daraus
entstand die Aussage „120 von 235 Ausprägungen decken 80 Prozent ab". Sie war
ohne Gehalt, und sie widersprach genau dem Grundsatz, den dieser Abschnitt
aufstellt. Jede Kennzahl trägt jetzt selbst, ob ein Anteil über ihr zulässig ist
und ob ein kleinerer Wert der bessere ist.

---

## Das Trainingssystem von Pokémon Champions

Champions hat die Fleißpunkte und Determinationswerte der Hauptreihe ersetzt:

| | Hauptreihe | Pokémon Champions |
|---|---|---|
| Investition | Fleißpunkte, 0–252 je Wert, 510 gesamt | **Statuspunkte**, 0–32 je Wert, **66 gesamt** |
| Wirkung | 4 Fleißpunkte = +1 Statuspunkt | **1 Statuspunkt = +1 Endwert** (Stufe 50) |
| Determinationswerte | 0–31, züchtbar | **fest 31**, nicht veränderbar |
| Wesen | Natur | *Stat Alignment*, gleiche Wirkung |

Die im Spiel als „Base stats" angezeigten Werte sind bereits die Werte auf Stufe
50 ohne Investition. Für Knackrack zeigt das Spiel 183/150/115/100/105/122 —
`bi.stats.stufe50_grundwerte` reproduziert genau diese Zahlen, was als Test
hinterlegt ist.

In der Praxis werden meist zwei Werte auf 32 gesetzt und die verbleibenden zwei
Punkte auf einen dritten verteilt. Knackrack mit `Jolly 2/32/0/0/0/32` erreicht
damit 169 Initiative und 182 Angriff.

**Folge für Bizarroraum-Sets:** In der Hauptreihe macht man ein Pokémon über null
Determinationswerte bewusst langsam. In Champions ist das **unmöglich** — die
Werte liegen fest bei 31. Dort bleibt allein das Wesen.

---

## Team-Preview-Advisor

Im Turnier bringt jede Seite sechs Pokémon mit, sieht im Team-Preview die sechs
des Gegners und wählt daraus die Kämpfer: **vier** im Doppelkampf, **drei** im
Einzelkampf.

Die Quelle veröffentlicht nicht, welche Pokémon tatsächlich mitgenommen wurden —
diese Kennzahl existiert öffentlich nicht. Sie wird auch nicht gebraucht: eine
Durchschnittsquote sagte nur, was Spieler *im Mittel* bringen, nicht was gegen
*dieses eine* Team richtig ist.

Stattdessen wird die Entscheidung durchgerechnet: 15 × 15 = 225 Paarungen im
Doppelkampf, 20 × 20 = 400 im Einzelkampf — in unter 0,1 Sekunden. Je Paarung
werden drei Größen verrechnet:

| Anteil | Größe | Grundlage |
|---|---|---|
| 45 % | Offensive | tatsächlich gespielte Attacken gegen die Typen des Gegners |
| 35 % | Defensive | dieselbe Rechnung in der Gegenrichtung |
| 20 % | Initiative | reale Werte aus den Statuspunkten |

Die Gesamtwertung verrechnet den Mittelwert mit dem ungünstigsten Fall (30 %
Risikoabschlag), damit keine Auswahl gewinnt, die im Mittel gut dasteht, aber
gegen eine bestimmte Aufstellung einbricht. Ausgegeben werden die empfohlene
Auswahl, der Beitrag je Pokémon, die riskanteste gegnerische Auswahl und eine
Begründung im Klartext.

---

## Archivierung: die Quelle vergisst, das Warehouse nicht

Champions hält nur rund **14 Tage** Tagesstände vor. Fällt ein Tag heraus, ist er
nicht nachladbar. Jeder Lauf schreibt die Rohnutzlast deshalb nach
`Archiv_Champions` — eine Tabelle, die auch beim vollständigen Zurücksetzen des
Warehouse **erhalten bleibt** und nur auf ausdrückliche Anweisung geleert wird.

Damit wächst eine Zeitreihe, die an der Quelle selbst nicht existiert. Das Archiv
erlaubt außerdem, geänderte Ableitungsregeln auf alle je gesicherten Tage
anzuwenden, ohne die Quelle erneut anzufragen — 2 Sekunden statt 30.

### Zwei Stufen, weil eine nicht reicht

Eine Tabelle allein genügt nicht: `data/` ist nicht versioniert, und ein
CI-Läufer beginnt jedes Mal mit leerer Platte. Die Datenbanktabelle überlebt
zwar jedes Zurücksetzen des Warehouse, aber keinen neuen Rechner. Deshalb wird
das Archiv zusätzlich als Datei abgelegt und **mitversioniert**:

```
archiv/M4/Doubles/2026-07-28.ndjson.gz        ~0,3 MB je Tag
archiv/stammdaten/Dim_Pokemon.ndjson.gz        0,11 MB, einmalig
archiv/stammdaten/Dim_Attacke.ndjson.gz        0,01 MB, einmalig
```

Eine Zeile je Rohdatensatz, gzip-komprimiert, deterministisch sortiert und ohne
Zeitstempel im gzip-Kopf. Ob eine Datei neu geschrieben wird, entscheidet ein
Vergleich der **entpackten Nutzlast** — nicht der komprimierten Bytes: zlib
liefert je nach Fassung und Betriebssystem unterschiedliche Kompressate für
denselben Eingang. Ein Byte-Vergleich schrieb im Betrieb das gesamte Archiv neu,
sobald der Lauf vom Entwicklungsrechner auf den Linux-Runner wanderte.

Der Stammdatenauszug liegt daneben, weil Champions nur Namen und Ränge liefert:
Typ, Basiswerte und Attackeneigenschaften stammen aus der PokeAPI. Er wird
**tabellengetreu** gesichert, samt Gültigkeitszeiträumen — eine Neuladung über
den regulären Weg würde die bi-temporale Historie von `Dim_Pokemon` verlieren.

Der ETL-Lauf liest dieses Verzeichnis vor jedem Zugriff auf die Quelle ein; der
tägliche Workflow schreibt es danach zurück. Erst dieser Kreislauf lässt die
Zeitreihe die 14-Tage-Grenze überschreiten.

```bash
python -m scripts.archiv_export        # Datenbank  → Dateien
python -m scripts.etl_lauf             # Dateien    → Datenbank, dann Quelle
python -m scripts.etl_lauf --ohne-archiv   # Dateiarchiv übergehen
```

### Das Warehouse entsteht beim Start neu

Die Anwendung baut das Data Warehouse beim ersten Aufruf aus dem Archiv auf.
Der Grund steht in den Größenverhältnissen — gemessen an 6 gegenüber 13 Tagen:

| Bestand | je Tag | je Jahr | wiederbeschaffbar? |
|---|---|---|---|
| Rohdatenarchiv | 0,3 MB | ~110 MB | **nein** — die Quelle vergisst nach 14 Tagen |
| Data Warehouse | 6,0 MB | ~2,2 GB | ja — in Sekunden aus dem Archiv |

Gesichert wird deshalb das Kleine und Unersetzliche, aufgebaut wird das Große
und Ableitbare. Das ist zugleich die Kernidee der Staging-Schicht: die Rohdaten
sind die Wahrheit, das Warehouse ist eine Ableitung.

Praktisch löst das ein reales Betriebsproblem: `data/` ist nicht versioniert,
und Streamlit Community Cloud setzt bei jedem Deployment einen frischen Behälter
auf — auch beim täglichen Archiv-Commit. Ohne diesen Schritt stünde die
Anwendung dort jeden Tag wieder ohne Daten da.

Der Aufbau läuft in `bi.bootstrap`, hängt in `hole_verbindung()` und geschieht
über `st.cache_resource` genau einmal je Behälter. Er kommt **ohne jeden
Netzzugriff** aus — ein Test schaltet die Verbindung dafür ab. Gemessen dauert
er 7 Sekunden für 13 Tage; für Mitte September sind rund 30 Sekunden zu
erwarten, einmalig nach jedem Deployment.

Drei Qualitätsregeln sichern das ab: *Lückenlosigkeit des Archivs* meldet
ausgelassene Ladeläufe, solange sich noch etwas retten lässt,
*Archivdeckung der Fakten* stellt sicher, dass jeder geladene Tag gesichert ist,
und der Export-Import-Weg selbst ist durch Tests abgedeckt — einschließlich der
Byte-Gleichheit unveränderter Tage.

### Saisonabgrenzung

Jeder Faktensatz trägt seine Saison. Genau eine Saison je Quelle gilt als
aktuell; alle Auswertungen filtern darauf. Damit verfälschen Pokémon aus
abgelaufenen Regulationen die laufende Saison nicht.

Der Saisonzeitraum wächst mit dem Archiv: früher gesicherte Tage bleiben Teil der
Saison, auch wenn die Quelle sie nicht mehr führt. Balance-Anpassungen an den
Pokémon selbst deckt die bi-temporale Historisierung von `Dim_Pokemon` ab.

---

## Historisierung

`Dim_Pokemon` ist **bi-temporal** ausgeführt — Delta-Verfahren kombiniert mit
Gültigkeitszeiträumen:

| Feld | Zweck |
|---|---|
| `gueltig_ab` / `gueltig_bis` | fachlicher Gültigkeitszeitraum |
| `ist_aktuell` | schneller Zugriff auf den Ist-Stand |
| `dwh_geladen_am` | technischer Ladezeitpunkt |
| `row_hash` | Änderungserkennung über die fachlich relevanten Attribute |

Ändert sich ein Attribut — etwa durch eine Balance-Anpassung zwischen zwei
Saisons — wird der bisherige Satz zum Vortag abgegrenzt und ein neuer eröffnet.
Auswertungen zu einem historischen Stichtag bleiben möglich.

Die Faktentabellen sind **nicht-volatil** (Inmon): es wird ausschließlich
eingefügt oder auf dem fachlichen Schlüssel aktualisiert. Ein wiederholter Lauf
desselben Tages ist idempotent und lässt die übrige Zeitreihe unberührt.

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

Jede Kennzahl trägt ihre Aggregationsregel — und für Ränge sind nur Minimum,
Maximum, Median und Anzahl zugelassen.

---

## Datenqualität

Zweistufig geprüft:

**Während des Ladens** — Vollständigkeit von Pflichtfeldern, Auflösbarkeit der
Bezeichner, Regelkonformität der Statuspunkte. Befunde werden nach **Mangel
1. Klasse** (automatisch erkennbar und korrigierbar) und **Mangel 2. Klasse**
(erkennbar, erfordert fachliche Entscheidung) unterschieden und in `DQ_Befund`
protokolliert.

**Nach dem Laden** (`bi.quality`) — 15 Regeln auf dem Gesamtbestand entlang der
Dimensionen Vollständigkeit, Konsistenz, Eindeutigkeit, Wertebereich und
Aktualität. Der verdichtete **Qualitätsindex** dient als Qualitätstor in der CI.

### Bewertet wird, was steuerbar ist

Zwei Regeln — Lückenlosigkeit des Archivs und Aktualität — hingen ursprünglich am
Kalender: jede Lücke galt als Mangel, und der jüngste geladene Tag wurde gegen
*heute* gemessen. Beides bewertet in Wahrheit das Verhalten der Quelle. Als
Champions ab dem 04.08.2026 keine neuen Tagesstände mehr veröffentlichte, fiel
der Index deshalb dauerhaft auf 86,7 % und färbte jeden täglichen Lauf rot —
ohne dass irgendein Lauf daran etwas hätte ändern können. Ein Alarm, der sich
nicht abstellen lässt, wird überlesen; genau das entwertet ein Qualitätstor.

Beide Regeln messen daher jetzt gegen das **Angebot der Quelle**: Jeder Tag, den
Champions führt, muss archiviert und geladen sein. Was die Quelle nicht mehr
führt, ist unwiederbringlich und wird ausgewiesen, aber nicht bewertet.
Grundlage ist `Quelle_Stand` — jeder Lauf hält dort fest, welche Tage die Quelle
angeboten hat. Ohne diesen Vergleichswert (etwa beim Aufbau allein aus dem
Archiv) bleiben die Regeln stumm statt zu raten.

Der Stillstand der Quelle verschwindet damit nicht aus dem Bericht, er wechselt
nur die Rubrik: **Beobachtungen** stehen unter dem Regelwerk, gehen nicht in den
Index ein und erscheinen in GitHub Actions als Warnung. Ein verpasster Tag, den
die Quelle noch führt, reißt dagegen weiterhin zwei Regeln und damit das Tor.

### Befunde aus der Quellanalyse

1. **Keine Nutzungsquote, nur ein Rang.** Geprüft über alle 236 Pokémon und alle
   geladenen Tage. Das Datenmodell bildet das ehrlich ab und erfindet keinen
   Platzhalter; die Kennzahlen sind entsprechend ordinal ausgelegt.

2. **Teampartner ohne Gewicht.** 2330 Zeilen, davon 0 mit Prozentwert. Die
   Partnervorschläge zählen deshalb Nennungen aus und mitteln keine Anteile.

3. **121 von 48.740 Punkteverteilungen verletzen die Spielregeln** — bis zu 200
   Punkte in einem Einzelwert (Maximum 32) und Summen bis 130 (Budget 66). Im
   Spiel unmöglich. Die Sätze werden geladen, aber ausgewiesen.

4. **26 von 236 Bezeichnern sind nicht direkt auflösbar.** Champions schreibt
   Formen aus und stellt die Region voran (`Alolan Ninetales`), die PokeAPI hängt
   sie an (`ninetales-alola`). Regelbasiert gelöst statt über eine Einzelliste;
   verbleibende Nicht-Treffer werden protokolliert statt geraten. Aktuelle
   Trefferquote: **100 %**.

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
nacheinander **Stammdaten laden** und **Champions-Daten laden** ausführen — der
vollständige Aufbau dauert rund 30 Sekunden.

### Kopfloser Betrieb

```bash
python -m scripts.etl_lauf
```

Nur die tägliche Strecke (so sollte der geplante Lauf aussehen):

```bash
python -m scripts.etl_lauf --nur-champions
```

Qualitätstor:

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

**`ci.yml`** — bei jedem Push und Pull Request: Ruff-Linting, Tests auf Python
3.10 und 3.12, und auf dem Hauptzweig zusätzlich ein Integrationslauf gegen die
echte Quelle mit anschließendem Qualitätstor. Der Lauf protokolliert die
installierten Versionen; die meisten Befunde, die lokal nicht auftreten, sind
Versionsunterschiede. Ist die Quelle nicht erreichbar (Rückgabewert 75), wird der
Integrationsteil übersprungen statt rot gemeldet — ein fremder Ausfall ist kein
Codefehler.

**`etl_taeglich.yml`** — Operationalisierung: **täglich** um 05:00 Uhr. Der
tägliche Rhythmus ist keine Kür, sondern Pflicht: die Quelle hält nur 14 Tage
vor. Der Lauf liest das versionierte Dateiarchiv ein, holt den neuen Tag, schreibt
das Archiv zurück ins Repository und prüft **erst danach** die Qualität — sonst
könnte ein Qualitätsmangel einen unwiederbringlichen Tagesstand kosten.

Rot wird der Lauf hier, wo etwas zu retten war und nicht gerettet wurde: ist die
Quelle nicht erreichbar oder bietet sie einen Tag an, den der Lauf nicht geholt
hat, muss das auffallen — nach der Vorhaltezeit ist der Tag endgültig verloren.
Veröffentlicht die Quelle dagegen selbst nichts mehr, erscheint das als Warnung
am Lauf. Diese Unterscheidung ist der Grund, warum jeder Lauf protokolliert,
welche Tage die Quelle angeboten hat: „nichts Neues geladen“ und „das Angebot der
Quelle nicht mehr lesbar“ sähen im Protokoll sonst gleich aus.

### Deployment

Ausgelegt für **Streamlit Community Cloud**: Repository verbinden, `app.py` als
Einstiegspunkt, `requirements.txt` wird automatisch installiert. Das Verzeichnis
`data/` ist bewusst nicht versioniert, `archiv/` dagegen schon — die Cloud baut
das Warehouse beim ersten Aufruf daraus auf. Es ist also nichts einzurichten:
Repository verbinden, fertig.

Die Abhängigkeiten sind exakt festgelegt und auf **Python 3.10 bis 3.14** geprüft:
für jede dieser Versionen existiert von jedem Paket ein fertiges Wheel. Ohne diese
Prüfung übersetzt die Cloud pandas aus dem Quelltext — der Aufbau dauert dann
45 Minuten statt einer.

---

## Projektstruktur

```
├── app.py                        Einstiegspunkt (Streamlit)
├── src/bi/
│   ├── config.py                 zentrale Konfiguration
│   ├── typechart.py              Typen-Regelbasis
│   ├── stats.py                  Statuspunkte, Wesen, Initiative-Szenarien
│   ├── warehouse.py              Schema-DDL, Sichten, Verbindung
│   ├── quality.py                15 Qualitätsregeln
│   ├── etl/
│   │   ├── extract.py            PokeAPI-Stammdaten
│   │   ├── champions.py          Champions-Strecke inkl. Archivierung
│   │   ├── archivdatei.py        Determinismus-Zusage der Archivdateien
│   │   ├── stammarchiv.py        Versionierter Auszug der Stammdaten
│   │   ├── mapping.py            Harmonisierung der Bezeichner
│   │   ├── transform.py          Filterung · Anreicherung · Zeitdimension
│   │   ├── load.py               Historisierung, Dimensionen, Protokoll
│   │   └── pipeline.py           Orchestrierung
│   ├── analytics/
│   │   ├── kpi.py                ordinale Kennzahlen, Rangkorrelation
│   │   ├── olap.py               Würfeloperationen
│   │   ├── speed.py              Speed-Tiers, Szenarien, Benchmark
│   │   ├── threat.py             Bedrohungs- und Abdeckungsanalyse
│   │   └── preview.py            Team-Preview-Advisor
│   └── ui/                       acht Seitenmodule + gemeinsame Bausteine
├── scripts/                      kopflose ETL- und Prüfläufe
├── tests/                        178 Tests
└── .github/workflows/            CI und täglicher Ladelauf
```

---

## Zuordnung zum Projektbericht

| Kapitel | Fundstelle |
|---|---|
| Problem- und Datenbeschreibung | dieses README, `bi/etl/champions.py` |
| ETL | `bi/etl/` — je ein Modul pro Prozessschritt |
| Datenmodellierung | `bi/warehouse.py` (DDL mit Begründungen) |
| Datenanalyse | `bi/analytics/` |
| Datenvisualisierung / Dashboard | `bi/ui/` |
| Datenqualität | `bi/quality.py` |
| Operationalisierung | `scripts/`, `.github/workflows/` |

---

## Quellen und Rechtliches

- [Pokémon Champions Battle Data](https://championsbattledata.com/) — Bewegungsdaten
- [PokeAPI](https://pokeapi.co) — Stammdaten

Rein akademisches Projekt ohne kommerzielle Nutzung. Es besteht keine Verbindung
zu Nintendo, Game Freak oder The Pokémon Company.

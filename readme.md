# 🌦️ OpenWeatherMap Big Data Streaming Projekt

## 🎯 Zielsetzung
Ziel dieses Projekts ist es, eine skalierbare, containerisierte Streaming-Pipeline zur Analyse und Visualisierung von Wetterdaten in Echtzeit aufzubauen. Dabei stehen Robustheit, Erweiterbarkeit (z. B. Anomalieerkennung) sowie Transparenz der Verarbeitung (z. B. durch Zeitstempel & Lag-Analyse) im Fokus.

---

## 🗂️ Projektübersicht
Dieses Projekt streamt Wetterdaten von OpenWeatherMap in Echtzeit und verarbeitet sie über eine Event-Streaming-Pipeline. Die Daten werden in einer PostgreSQL-Datenbank gespeichert und mit Grafana visualisiert.

<pre><code>```text
OPENWEATHERMAP-BIGDATA-PROJECT/
├── ai_model/
│   ├── data/                            # Trainingsdaten für das ML-Modell
│   │   ├── 2022_05_01.xlsx
│   │   ├── 2022_05_02.xlsx
│   │   ├── 2022_05_03.xlsx
│   │   └── anomalie.xlsx               # Validierungsset mit Labels
│   ├── model/                          # Serialisiertes Modell und Scaler
│   │   ├── isolation_forest_model.pkl
│   │   └── scaler.pkl
│   ├── 01_training.ipynb               # Notebook zum Training (inkl. Export)
│   └── 02_predict_anomalies.ipynb      # Notebook zur Validierung & Analyse
├── weather_producer.py                 # Producer: API-Aufrufe & Kafka-Push
├── weather_beam.py                     # Beam-Consumer mit Preprocessing + ML
├── Dockerfile-producer                 # Container-Konfiguration Producer
├── Dockerfile-beam                     # Container-Konfiguration Beam + ML
├── docker-compose.yml                  # Orchestriert alle Services
├── grafana_json_export.json            # Importierbares Dashboard
├── .env                                # Lokale Umgebungsvariablen (nicht committet)
├── .env.example                        # Beispielhafte .env-Datei
├── .gitignore                          # Ignoriert sensible / temporäre Dateien
├── requirements.txt                    # Python-Abhängigkeiten
└── readme.md                           # Projektdokumentation (dieses File)
```</code></pre>

---

**Architektur:**  
OpenWeatherMap → Kafka → Apache Beam → PostgreSQL → Grafana

Alle Komponenten laufen containerisiert über Docker Compose.

---

## 🔧 Komponenten
| Komponente                        | Aufgabe                                       																			|
|----------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| Kafka & Zookeeper                | Event-Streaming                               																				|
| PostgreSQL                       | Speicherung der Wetterdaten                   																				|
| Grafana                          | Visualisierung                                																				|
| weather_producer.py (Container)  | Holt Wetterdaten, ergänzt event_time & received_time und sendet an Kafka       											|
| weather_beam.py (Container)      | Liest von Kafka, ergänzt processing_time, filtert, erkennt Anomalien und speichert in PostgreSQL (inkl. Idempotenz)     	|


---

## 📋 Gespeicherte Wetterdaten (weather_data)
| Feld             | Einheit / Typ        | Beschreibung                         					|
|------------------|----------------------|---------------------------------------------------------|
| city             | Text                 | Stadtname                            					|
| temperature      | °C                   | Temperatur                           					|
| humidity         | %                    | Luftfeuchtigkeit                     					|
| pressure         | hPa                  | Luftdruck                            					|
| wind_speed       | km/h                 | Windgeschwindigkeit (berechnet)      					|
| cloud_coverage   | %                    | Bewölkungsgrad                       					|
| weather_main     | Text                 | Wetterkategorie                      					|
| weather_description | Text              | Beschreibung                         					|
| timestamp        | Unix Time (s)        | Zeitpunkt der Messung                					|
| lon / lat        | Koordinaten          | Geografische Lage                    					|
| sys_country      | Ländercode           | Nur CH wird gespeichert             					|
| event_time       | Unix Time (s)        | Zeitpunkt der Wettermessung (von API)           		|
| received_time    | Unix Time (s)        | Zeitpunkt, wann die Nachricht im Producer ankam 		|
| processing_time  | Unix Time (s)        | Zeitpunkt, wann der Datensatz in Beam verarbeitet wurde |

---

## 🧪 Verarbeitungsschritte in der Apache Beam Pipeline
| Schritt                          | Beam-Typ         | Beschreibung                                                                 											|
|----------------------------------|------------------|-------------------------------------------------------------------------------------------------------------------------|
| Batch laden                      | beam.Create      | Lädt 10 gesammelte Kafka-Nachrichten in die Pipeline                         											|
| Debug falsche sys_country        | beam.Map         | Gibt Einträge mit sys_country ≠ 'CH' zur Kontrolle aus                       											|
| Filtere nur sys_country = CH     | beam.Filter      | Lässt nur Datensätze mit sys_country = 'CH' durch                            											|
| Debug ungültige Werte            | beam.Map         | Gibt Datensätze mit fehlenden numerischen Werten (None) aus                  											|
| Filtere nur gültige Werte        | beam.Filter      | Filtert nur Datensätze mit vollständigen Werten (temperature, pressure, etc.)											|
| Windgeschwindigkeit umrechnen    | beam.Map         | Rechnet wind_speed von m/s in **km/h** um (Feldname bleibt gleich)           											|
| Processing-Zeit ergänzen		   | beam.Map		  | Fügt processing_time als Unix-Zeit hinzu									 											|
| Anomalie erkennen                | beam.Map         | Erkennt Anomalien mit einem ML-Modell (Isolation Forest, via sklearn + pandas)              							|
| In PostgreSQL schreiben          | beam.Map         | Speichert die bereinigten Datensätze in der PostgreSQL-Tabelle weather_data (mit Idempotenz (UNIQUE(city, timestamp))) 	|

---

## 🧰 Erweiterungen (Idempotenz, Zeitstempel, Retention, Anomalieerkennung mit Machine Learning)
**Zeitstempel:** Jeder Datensatz enthält drei Zeitpunkte für vollständige Nachvollziehbarkeit:
- `event_time`: Zeitpunkt der Messung laut OpenWeatherMap
- `received_time`: Zeitpunkt, wann der Producer die Daten empfangen hat
- `processing_time`: Zeitpunkt, wann Apache Beam den Datensatz verarbeitet hat

**Idempotenz:**  
Duplikate werden vermieden durch `UNIQUE(city, timestamp)` in PostgreSQL + `ON CONFLICT DO NOTHING`.

**Retention:**  
Kafka ist auf eine standardmässige Aufbewahrung von 7 Tagen konfiguriert (`KAFKA_LOG_RETENTION_HOURS = 168`).

**Verzögerungsanalyse (Lag):**  
Durch Vergleich von `processing_time` und `event_time` kann die Systemlatenz berechnet und visualisiert werden.

**Windowing & Triggering**  
In Apache Beam sind Zeitfenster und Trigger entscheidend für kontinuierliche Streamingverarbeitung. Da in diesem Projekt jedoch feste 10er-Batches verarbeitet werden, erfolgt keine explizite Zeitfensterung (`WindowInto`) oder Trigger-Logik. Die Batchebene übernimmt implizit die Fensterlogik. Daher wird auch kein Watermark oder `AccumulationMode` benötigt. Die Verarbeitung erfolgt mit dem Modus „discarding“ durch das explizite Überschreiben der Datenbank.
→ Vorteil: einfache Kontrolle, deterministisches Verhalten und keine verzögerten Nachlieferungen.

**Anomalieerkennung mit Machine Learningg**  
Der Unterordner ai_model/model/ enthält das produktive Machine-Learning-Modell (isolation_forest_model.pkl) und den zugehörigen StandardScaler (scaler.pkl) zur Anomalieerkennung. Das Notebook 01_training.ipynb dokumentiert den gesamten Trainingsprozess und erlaubt ein späteres Nachtraining oder Fine-Tuning des Modells mit aktualisierten Daten.

Enthaltene Dateien:
- 2022_05_01.xlsx, 2022_05_02.xlsx, 2022_05_03.xlsx: Rohdaten für das Training (wurden im Rahmen einer anderen Weiterbildung von Philippe Christen erhoben)
- anomalie.xlsx: validierte Anomalien zur Modell-Evaluierung (stark vereinfacht)
- training.ipynb: Jupyter Notebook zum Training inkl. Feature-Engineering & Modellpersistenz

Ziel: Reproduzierbarkeit und einfache Anpassung bei Modell-Drift oder veränderten Datenmustern.

---

## 🔑 Konfiguration (.env)
Im Repository befindet sich die Datei `.env.example`.
Bitte kopiere diese und benenne sie in `.env` um.
Anschliessend trägst du deinen persönlichen API_KEY ein (wird im Rahmen des Projekts per E-Mail bereitgestellt)

---

## ▶️ Starten
Docker Desktop starten

**Build & Start der gesamten Umgebung:**
docker-compose build --no-cache  
docker-compose up -d

**Logs prüfen (optional):**
docker logs openweathermap-bigdata-project-producer-1  
docker logs openweathermap-bigdata-project-beam-1

**Kafka Live-Stream prüfen (optional --> Consumer wird in temporären Container gestartet):**
docker run -it --network=openweathermap-bigdata-project_default confluentinc/cp-kafka:7.5.0 \
kafka-console-consumer --bootstrap-server kafka:9092 --topic weather_data --from-beginning

**psql Abfrage (optional):**
docker exec -it openweathermap-bigdata-project-postgres-1 psql -U user -d weather
    SELECT * FROM weather_data ORDER BY timestamp DESC LIMIT 100;

**Stoppen:**
docker-compose down --remove-orphans

---

## 🔑 Zugangsdaten & Ports

| Dienst     | Adresse/Port          | Zugangsdaten   |
|------------|-----------------------|----------------|
| Kafka      | localhost:9092        | -              |
| PostgreSQL | localhost:5432        | user / pass    |
| Grafana    | http://localhost:3000 | admin / admin  |

---

## 📊 Grafana einrichten

### Datenquelle hinzufügen
1. Links: ⚙ Data Sources → PostgreSQL auswählen.
2. Host: postgres:5432
3. Database: weather
4. User: user, Passwort: pass
5. Save & Test → sollte „Database OK“ anzeigen.

### Panel erstellen — Beispiel-Querys

**Temperatur über Zeit:**
SELECT timestamp * 1000 AS "time", temperature  
FROM weather_data  
ORDER BY timestamp ASC;

**Luftfeuchtigkeit über Zeit:**
SELECT timestamp * 1000 AS "time", humidity  
FROM weather_data  
ORDER BY timestamp ASC;

**Lag-Analyse:**
SELECT (processing_time - event_time) AS lag_seconds 
FROM weather_data;

**Anomaly-Analyse:**
SELECT
  to_timestamp(processing_time) AS time,
  city, temperature, wind_speed, pressure, humidity
FROM
  weather_data
WHERE
  anomaly = true
ORDER BY
  processing_time DESC;

**Anomaly-Analyse Heatmap:**
SELECT city, COUNT(*) AS anomaly_count
FROM weather_data
WHERE anomaly = true
GROUP BY city
ORDER BY anomaly_count DESC;


**Importiertes Dashboard**
Das vorkonfigurierte Grafana-Dashboard ist als Datei grafana_json_export.json im Projekt enthalten.
Du kannst es wie folgt importieren:
	1.	Öffne Grafana unter http://localhost:3000
	2.	Klicke auf „+“ → „Import“
	3.	Lade die Datei grafana_json_export.json hoch oder füge den JSON-Inhalt ein
	4.	Wähle die PostgreSQL-Datenquelle aus und bestätige mit Import


---

## ⚙️ .env-Konfiguration
Alle Parameter werden über die .env-Datei gesteuert:

**Beispielhafte Parameter:**
- `API_KEY` – OpenWeatherMap API Key
- `CITIES` – Städte im Format: `Zürich, CH;Bern, CH;Basel, CH`
- `TOPIC` – Kafka Topic
- `PG_HOST`, `PG_DB`, `PG_USER`, `PG_PASSWORD`, `PG_PORT`

---

## 🐍 Lokales Testing (ohne Container)
Falls du das System ohne Docker testen möchtest:
pip install -r requirements.txt

Dann in zwei Terminals ausführen:
python weather_producer.py  
python weather_beam.py

---

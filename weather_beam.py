import json
import logging
import os
import time
import joblib
from typing import Any, Dict, List, Optional

import apache_beam as beam
import psycopg2
from apache_beam.options.pipeline_options import PipelineOptions
from dotenv import load_dotenv
from kafka import KafkaConsumer, errors
import numpy as np
import pandas as pd

# === Logging konfigurieren ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Umgebungsvariablen laden ===
load_dotenv()

# PostgreSQL Konfiguration
PG_HOST = os.getenv("PG_HOST")
PG_DB = os.getenv("PG_DB")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")
PG_PORT = int(os.getenv("PG_PORT", "5432"))

# Kafka-Konfiguration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
TOPIC = os.getenv("TOPIC")

if not all(
    [PG_HOST, PG_DB, PG_USER, PG_PASSWORD, PG_PORT, KAFKA_BOOTSTRAP_SERVERS, TOPIC]
):
    logger.error("Fehlende Umgebungsvariablen. Bitte .env prüfen.")
    exit(1)

# === Modell & Scaler laden ===
model = joblib.load("ai_model/model/isolation_forest_model.pkl")
scaler = joblib.load("ai_model/model/scaler.pkl")


# === Funktion: Datensatz in PostgreSQL schreiben ===
def write_to_postgres(record: Dict[str, Any]) -> None:
    try:
        conn = psycopg2.connect(
            host=PG_HOST,
            database=PG_DB,
            user=PG_USER,
            password=PG_PASSWORD,
            port=PG_PORT,
        )
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_data (
                city VARCHAR(50),
                temperature REAL,
                humidity INTEGER,
                pressure INTEGER,
                wind_speed REAL,
                cloud_coverage INTEGER,
                weather_main TEXT,
                weather_description TEXT,
                timestamp BIGINT,
                lon REAL,
                lat REAL,
                sys_country VARCHAR(10),
                event_time BIGINT,
                received_time BIGINT,
                processing_time BIGINT,
                anomaly BOOLEAN,
                UNIQUE (city, timestamp)
            );
            """
        )

        # Konvertiere anomaly explizit zu bool
        anomaly_bool = True if record.get("anomaly") == 1 else False

        cur.execute(
            """
            INSERT INTO weather_data (
                city, temperature, humidity, pressure, wind_speed, cloud_coverage,
                weather_main, weather_description, timestamp, lon, lat, sys_country,
                event_time, received_time, processing_time, anomaly
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
            ON CONFLICT DO NOTHING
            """,
            (
                record.get("city"),
                record.get("temperature"),
                record.get("humidity"),
                record.get("pressure"),
                record.get("wind_speed"),
                record.get("cloud_coverage"),
                record.get("weather_main"),
                record.get("weather_description"),
                record.get("timestamp"),
                record.get("lon"),
                record.get("lat"),
                record.get("sys_country"),
                record.get("event_time"),
                record.get("received_time"),
                record.get("processing_time"),
                anomaly_bool,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

    except Exception as error:
        logger.error("PostgreSQL Fehler: %s", error)


# === Gültigkeitsprüfung ===
def is_valid_record(x: Dict[str, Any]) -> bool:
    if x.get("sys_country") != "CH":
        return False
    required_keys = [
        "temperature",
        "humidity",
        "pressure",
        "wind_speed",
        "cloud_coverage",
    ]
    return all(x.get(k) is not None for k in required_keys)


# === Anomalie erkennen ===
def add_anomaly_prediction(record: Dict[str, Any]) -> Dict[str, Any]:
    try:
        features_df = pd.DataFrame(
            [
                {
                    "temperature": record["temperature"],
                    "wind_speed": record["wind_speed"],
                    "pressure": record["pressure"],
                    "humidity": record["humidity"],
                    "lat": record["lat"],
                    "lon": record["lon"],
                }
            ]
        )

        features_scaled = scaler.transform(features_df)
        prediction = model.predict(features_scaled)[0]  # -1 = Anomalie
        record["anomaly"] = 1 if prediction == -1 else 0
        return record
    except Exception as e:
        logger.error("Fehler bei Anomalievorhersage: %s", e)
        record["anomaly"] = None
        return record


# === Kafka Consumer + Beam Pipeline ===
def consume_and_process(batch_size: int = 10) -> None:
    consumer: Optional[KafkaConsumer] = None

    # Kafka-Verbindung mit Retry
    for attempt in range(10):
        try:
            consumer = KafkaConsumer(
                TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                auto_offset_reset="earliest",
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            logger.info("Kafka Consumer verbunden.")
            break
        except errors.NoBrokersAvailable:
            logger.warning(
                "Kafka nicht erreichbar, Versuch %s/10. Warte 5 Sekunden...",
                attempt + 1,
            )
            time.sleep(5)

    if not consumer:
        raise ConnectionError("Kafka Consumer konnte nicht verbunden werden.")

    logger.info("Starte Batch-Verarbeitung in 10er-Schritten...")
    buffer: List[Dict[str, Any]] = []

    for message in consumer:
        data = message.value
        logger.info("Empfangen von Kafka: %s", data)
        buffer.append(data)

        if len(buffer) >= batch_size:
            logger.info("Verarbeite Batch mit %d Nachrichten via Beam...", len(buffer))

            with beam.Pipeline(options=PipelineOptions()) as pipeline:
                (
                    pipeline
                    | "Batch laden" >> beam.Create(buffer)
                    | "Nur gültige CH-Daten behalten" >> beam.Filter(is_valid_record)
                    | "Processing-Zeit ergänzen"
                    >> beam.Map(lambda x: {**x, "processing_time": int(time.time())})
                    | "Windgeschwindigkeit umrechnen (km/h)"
                    >> beam.Map(
                        lambda x: {**x, "wind_speed": round(x["wind_speed"] * 3.6, 1)}
                    )
                    | "Anomalie erkennen" >> beam.Map(add_anomaly_prediction)
                    | "In PostgreSQL schreiben" >> beam.Map(write_to_postgres)
                )

            buffer.clear()


# === Main ===
if __name__ == "__main__":
    consume_and_process(batch_size=5)

import json
import logging
import os
import time
from typing import Optional, List, Dict, Any

import requests
from dotenv import load_dotenv
from kafka import KafkaProducer, errors
from datetime import datetime

# === Logging konfigurieren ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Umgebungsvariablen laden ===
load_dotenv()

API_KEY: Optional[str] = os.getenv("API_KEY")
CITY_STRING: Optional[str] = os.getenv("CITIES")
KAFKA_BOOTSTRAP_SERVERS: Optional[str] = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
TOPIC: Optional[str] = os.getenv("TOPIC")

if not all([API_KEY, CITY_STRING, KAFKA_BOOTSTRAP_SERVERS, TOPIC]):
    logger.error("Fehlende Umgebungsvariablen. Bitte .env prüfen.")
    exit(1)

# === Mehrere Städte aus .env extrahieren ===
CITIES: List[str] = [city.strip() for city in CITY_STRING.split(";") if city.strip()]

# === Kafka Producer mit Retry-Mechanismus ===
producer: Optional[KafkaProducer] = None

for attempt in range(10):
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        logger.info("Kafka Producer verbunden.")
        break
    except errors.NoBrokersAvailable:
        logger.warning(
            "Kafka nicht erreichbar, Versuch %s/10. Warte 5 Sekunden...",
            attempt + 1,
        )
        time.sleep(5)

if not producer:
    raise ConnectionError("Kafka Producer konnte nicht verbunden werden.")


# === Wetterdaten extrahieren ===
def extract_weather_data(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "city": data.get("name"),
        "temperature": data.get("main", {}).get("temp"),
        "humidity": data.get("main", {}).get("humidity"),
        "pressure": data.get("main", {}).get("pressure"),
        "wind_speed": data.get("wind", {}).get("speed"),
        "cloud_coverage": data.get("clouds", {}).get("all"),
        "weather_main": data.get("weather", [{}])[0].get("main"),
        "weather_description": data.get("weather", [{}])[0].get("description"),
        "timestamp": data.get("dt"),
        "lon": data.get("coord", {}).get("lon"),
        "lat": data.get("coord", {}).get("lat"),
        "sys_country": data.get("sys", {}).get("country"),
    }


# === Wetterdaten abrufen und an Kafka senden ===
def stream_weather_data() -> None:
    while True:
        for city in CITIES:
            try:
                url = (
                    f"http://api.openweathermap.org/data/2.5/weather?"
                    f"q={city}&appid={API_KEY}&units=metric&lang=de"
                )
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()

                weather_data = extract_weather_data(data)

                # Event- & Empfangszeit ergänzen
                event_time = weather_data["timestamp"]
                received_time = int(time.time())
                weather_data["event_time"] = event_time
                weather_data["received_time"] = received_time

                logger.info("Sende an Kafka: %s", weather_data)
                producer.send(TOPIC, value=weather_data)

            except Exception as error:
                logger.error("Fehler bei %s: %s", city, error)

            time.sleep(1)  # Schonung der API

        logger.info("Warte 10 Minuten bis zur nächsten Abfrage...")
        time.sleep(600)


if __name__ == "__main__":
    stream_weather_data()

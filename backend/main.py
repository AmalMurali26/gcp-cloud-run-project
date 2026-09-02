import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from redis import Redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend-service")

# Cloud Run injects these environment variables and Secret Manager values[cite: 2]
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")[cite: 2]
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")[cite: 2]
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")[cite: 2]

# Enforce secure secret loading without hardcoded default fallback
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")[cite: 2]
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))[cite: 2]

redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)[cite: 2]

class PersonData(BaseModel):[cite: 2]
    name: str[cite: 2]
    email: str[cite: 2]

def get_db_connection():
    if not POSTGRES_PASSWORD:
        raise ValueError("POSTGRES_PASSWORD environment variable is not configured.")
    return psycopg2.connect(
        host=DB_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        connect_timeout=5
    )[cite: 2]

def init_db():
    retries = 5
    while retries > 0:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS people (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL
                );
            """)[cite: 2]
            conn.commit()[cite: 2]
            cur.close()[cite: 2]
            conn.close()[cite: 2]
            logger.info("Database tables initialized successfully.")
            return
        except Exception as e:
            retries -= 1
            logger.warning(f"Database connection waiting (retries left: {retries}): {e}")
            time.sleep(3)

@asynccontextmanager
async def lifespan(app: FastAPI):[cite: 2]
    init_db()[cite: 2]
    yield[cite: 2]

app = FastAPI(lifespan=lifespan)[cite: 2]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)[cite: 2]

@app.get("/health")
def health_check():
    return {"status": "healthy"}[cite: 2]

@app.get("/api/v1/data")
def read_data():
    try:
        hits = redis_client.incr("hits")[cite: 2]
    except Exception as e:
        logger.error(f"Redis error: {e}")[cite: 2]
        hits = "Redis Connection Error"[cite: 2]

    return {
        "message": "Hello from the backend API running on GCP!",[cite: 2]
        "redis_visit_count": hits,[cite: 2]
        "database_status": "Connected"[cite: 2]
    }

@app.post("/api/v1/people")
def add_person(person: PersonData):[cite: 2]
    try:
        conn = get_db_connection()
        cur = conn.cursor()[cite: 2]
        cur.execute(
            "INSERT INTO people (name, email) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING;",
            (person.name, person.email)
        )[cite: 2]
        conn.commit()[cite: 2]
        inserted = cur.rowcount > 0[cite: 2]
        cur.close()[cite: 2]
        conn.close()[cite: 2]
        return {"status": "success" if inserted else "warning", "message": f"Processed {person.name}"}[cite: 2]
    except Exception as e:
        logger.error(f"DB Error: {e}")[cite: 2]
        return {"status": "error", "message": str(e)}[cite: 2]

@app.get("/api/v1/people")
def get_people():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            cursor_factory=RealDictCursor,
            connect_timeout=5
        )[cite: 2]
        cur = conn.cursor()[cite: 2]
        cur.execute("SELECT id, name, email FROM people ORDER BY id DESC;")[cite: 2]
        records = cur.fetchall()[cite: 2]
        cur.close()[cite: 2]
        conn.close()[cite: 2]
        return {"status": "success", "data": records}[cite: 2]
    except Exception as e:
        logger.error(f"DB Fetch Error: {e}")[cite: 2]
        return {"status": "error", "message": "Failed to retrieve records."}[cite: 2]
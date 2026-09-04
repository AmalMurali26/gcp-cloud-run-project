import os
import time
import math
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

# Cloud Run injects these environment variables and Secret Manager values
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")

# Read from Secret Manager
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

class PersonData(BaseModel):
    name: str
    email: str

def get_db_connection():
    if not POSTGRES_PASSWORD:
        raise ValueError("POSTGRES_PASSWORD environment variable is not configured.")
    return psycopg2.connect(
        host=DB_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        connect_timeout=5
    )

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
            """)
            conn.commit()
            cur.close()
            conn.close()
            logger.info("Database tables initialized successfully.")
            return
        except Exception as e:
            retries -= 1
            logger.warning(f"Database connection waiting (retries left: {retries}): {e}")
            time.sleep(3)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/api/v1/data")
def read_data():
    try:
        hits = redis_client.incr("hits")
        try:
            redis_client.bgsave()
        except Exception as save_err:
            logger.warning(f"Redis bgsave skipped or in progress: {save_err}")
    except Exception as e:
        logger.error(f"Redis error: {e}")
        hits = "Redis Connection Error"

    return {
        "message": "Hello from the backend API running on GCP!",
        "redis_visit_count": hits,
        "database_status": "Connected"
    }

@app.post("/api/v1/people")
def add_person(person: PersonData):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO people (name, email) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING;",
            (person.name, person.email)
        )
        conn.commit()
        inserted = cur.rowcount > 0
        cur.close()
        conn.close()
        return {"status": "success" if inserted else "warning", "message": f"Processed {person.name}"}
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return {"status": "error", "message": str(e)}

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
        )
        cur = conn.cursor()
        cur.execute("SELECT id, name, email FROM people ORDER BY id DESC;")
        records = cur.fetchall()
        cur.close()
        conn.close()
        return {"status": "success", "data": records}
    except Exception as e:
        logger.error(f"DB Fetch Error: {e}")
        return {"status": "error", "message": "Failed to retrieve records."}

# --- Test Endpoints for Alert Simulation ---

@app.get("/api/v1/test/cpu-load")
def trigger_cpu_load(seconds: int = 45):
    end_time = time.time() + seconds
    while time.time() < end_time:
        _ = [math.sqrt(x) for x in range(1000)]
    return {"status": "success", "message": f"Consumed CPU for {seconds} seconds"}

memory_leak_simulator = []

@app.get("/api/v1/test/memory-load")
def trigger_memory_load(megabytes: int = 250):
    global memory_leak_simulator
    for _ in range(megabytes):
        memory_leak_simulator.append(b"x" * (1024 * 1024))
    return {
        "status": "success",
        "allocated_mb": megabytes,
        "total_chunks": len(memory_leak_simulator),
    }

@app.get("/api/v1/test/memory-clear")
def clear_memory():
    global memory_leak_simulator
    memory_leak_simulator.clear()
    return {"status": "success", "message": "Simulated memory cleared"}
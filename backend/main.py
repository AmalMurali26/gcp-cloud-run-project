import os
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

# GCP Cloud Run / GKE injects these as Environment Variables
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "mysecretpassword")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

class PersonData(BaseModel):
    name: str
    email: str

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        connect_timeout=5
    )

def init_db():
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
        logger.info("Database tables initialized.")
    except Exception as e:
        logger.warning(f"Database table initialization warning: {e}")

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
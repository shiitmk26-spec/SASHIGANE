"""SQLite accumulation layer for GLMM test-data Excel uploads."""

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "data" / "sashigane.db"

# Fixed schema: row 1 of the Excel file holds Japanese labels, row 2 holds
# these English keys, data starts from row 3.
EXPECTED_COLUMNS = [
    "learner_id",
    "region",
    "pref",
    "year",
    "group_name",
    "video",
    "practice",
    "trial",
    "item",
    "score",
    "max_score",
]


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS test_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learner_id TEXT NOT NULL,
                region TEXT,
                pref TEXT,
                year TEXT,
                group_name TEXT,
                video TEXT,
                practice TEXT,
                trial INTEGER,
                item TEXT NOT NULL,
                score REAL,
                max_score REAL,
                source_file TEXT,
                uploaded_at TEXT,
                UNIQUE (learner_id, item, trial)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                uploaded_at TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                inserted_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL
            )
            """
        )


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def file_already_uploaded(file_hash: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT file_name FROM upload_history WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return row[0] if row else None


def parse_excel(file_bytes: bytes) -> pd.DataFrame:
    """Read an upload, using row 2 (English keys) as the header."""
    df = pd.read_excel(BytesIO(file_bytes), header=1, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"必要な列が見つかりません: {', '.join(missing)}")

    df = df[EXPECTED_COLUMNS].dropna(how="all")
    df["trial"] = pd.to_numeric(df["trial"], errors="coerce").astype("Int64")
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["max_score"] = pd.to_numeric(df["max_score"], errors="coerce")
    df = df.dropna(subset=["learner_id", "item"])
    return df


def insert_records(df: pd.DataFrame, file_name: str) -> tuple[int, int]:
    """Insert rows, skipping ones that duplicate an existing
    (learner_id, item, trial). Returns (inserted_count, duplicate_count)."""
    uploaded_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with get_connection() as conn:
        for _, row in df.iterrows():
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO test_records
                    (learner_id, region, pref, year, group_name, video, practice,
                     trial, item, score, max_score, source_file, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["learner_id"],
                    row["region"],
                    row["pref"],
                    row["year"],
                    row["group_name"],
                    row["video"],
                    row["practice"],
                    None if pd.isna(row["trial"]) else int(row["trial"]),
                    row["item"],
                    None if pd.isna(row["score"]) else float(row["score"]),
                    None if pd.isna(row["max_score"]) else float(row["max_score"]),
                    file_name,
                    uploaded_at,
                ),
            )
            inserted += cur.rowcount
    return inserted, len(df) - inserted


def record_upload(
    file_name: str, file_hash: str, row_count: int, inserted: int, duplicates: int
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO upload_history
                (file_name, file_hash, uploaded_at, row_count, inserted_count, duplicate_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                file_name,
                file_hash,
                datetime.now(timezone.utc).isoformat(),
                row_count,
                inserted,
                duplicates,
            ),
        )


def fetch_all_records() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM test_records ORDER BY id", conn)


def fetch_upload_history() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM upload_history ORDER BY id DESC", conn)

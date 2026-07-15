"""SQLite accumulation layer for GLMM test-data Excel uploads."""

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "data" / "sashigane.db"

# Fixed schema: some files have a "テスト名" (test name) row before the
# headers, some don't. The header row (English keys) is located by scanning
# the first few rows rather than assuming a fixed offset.
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

TABLE_COLUMNS = ["test_name"] + EXPECTED_COLUMNS


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _create_test_records_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_name TEXT,
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
            UNIQUE (learner_id, test_name, item, trial)
        )
        """
    )


def init_db() -> None:
    with get_connection() as conn:
        _create_test_records_table(conn)

        # Migrate older databases that predate the test_name column.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(test_records)")}
        if "test_name" not in columns:
            conn.execute("ALTER TABLE test_records RENAME TO test_records_old")
            _create_test_records_table(conn)
            conn.execute(
                """
                INSERT INTO test_records
                    (learner_id, region, pref, year, group_name, video, practice,
                     trial, item, score, max_score, source_file, uploaded_at)
                SELECT
                    learner_id, region, pref, year, group_name, video, practice,
                    trial, item, score, max_score, source_file, uploaded_at
                FROM test_records_old
                """
            )
            conn.execute("DROP TABLE test_records_old")

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


def _find_header_row(raw: pd.DataFrame) -> int:
    for i in range(min(10, len(raw))):
        row_values = {str(v).strip() for v in raw.iloc[i].tolist() if v is not None}
        if set(EXPECTED_COLUMNS) <= row_values:
            return i
    raise ValueError("英語キーの見出し行が見つかりません")


def _find_test_name(raw: pd.DataFrame, header_row_idx: int) -> str | None:
    for i in range(header_row_idx):
        row = raw.iloc[i].tolist()
        if row and str(row[0]).strip() == "テスト名" and len(row) > 1 and row[1] is not None:
            return str(row[1]).strip()
    return None


def parse_excel(file_bytes: bytes) -> pd.DataFrame:
    """Read an upload, auto-detecting the English-key header row and an
    optional preceding "テスト名" (test name) row."""
    raw = pd.read_excel(BytesIO(file_bytes), header=None, dtype=str)

    header_row_idx = _find_header_row(raw)
    test_name = _find_test_name(raw, header_row_idx)

    df = raw.iloc[header_row_idx + 1 :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[header_row_idx].tolist()]

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"必要な列が見つかりません: {', '.join(missing)}")

    df = df[EXPECTED_COLUMNS].dropna(how="all")
    df["trial"] = pd.to_numeric(df["trial"], errors="coerce").astype("Int64")
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["max_score"] = pd.to_numeric(df["max_score"], errors="coerce")
    df["test_name"] = test_name
    df = df.dropna(subset=["learner_id", "item"])
    return df


def insert_records(df: pd.DataFrame, file_name: str) -> tuple[int, int]:
    """Insert rows, skipping ones that duplicate an existing
    (learner_id, test_name, item, trial). Returns (inserted_count, duplicate_count)."""
    uploaded_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with get_connection() as conn:
        for _, row in df.iterrows():
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO test_records
                    (test_name, learner_id, region, pref, year, group_name, video, practice,
                     trial, item, score, max_score, source_file, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["test_name"],
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

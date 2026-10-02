"""SQLite storage: videos + places/events + FTS5 + usage. Migrated via PRAGMA user_version."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reelmind.llm import Usage
from reelmind.models import Analysis, FetchedVideo, VideoRef

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    video_id TEXT NOT NULL,
    url TEXT NOT NULL,
    author TEXT DEFAULT '',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    upload_date TEXT,
    duration REAL,
    transcript TEXT DEFAULT '',
    category TEXT,
    summary TEXT,
    analysis_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','failed')),
    error TEXT,
    added_at TEXT NOT NULL,
    processed_at TEXT,
    UNIQUE(platform, video_id)
);
CREATE TABLE IF NOT EXISTS places (
    video_pk INTEGER NOT NULL REFERENCES videos(pk) ON DELETE CASCADE,
    name TEXT, kind TEXT, address TEXT, city TEXT, country TEXT, price_range TEXT
);
CREATE TABLE IF NOT EXISTS events (
    video_pk INTEGER NOT NULL REFERENCES videos(pk) ON DELETE CASCADE,
    name TEXT, venue TEXT, city TEXT,
    start_date TEXT, end_date TEXT, time TEXT, price TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
    title, summary, description, transcript, tags, names
);
CREATE TABLE IF NOT EXISTS usage (
    ts TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL
);
"""


def _quote_fts(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


class Storage:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # one shared connection, guarded
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self._conn.executescript(_SCHEMA)
        if version < 2:
            # LLMs used to store "" for unknown event dates — normalize to NULL
            self._conn.execute(
                "UPDATE events SET start_date=NULL WHERE trim(coalesce(start_date,''))=''"
            )
            self._conn.execute(
                "UPDATE events SET end_date=NULL WHERE trim(coalesce(end_date,''))=''"
            )
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    # --- writes ---------------------------------------------------------------

    def add_pending(self, ref: VideoRef) -> bool:
        """Enqueue a video. Returns True if newly inserted."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO videos (platform, video_id, url, status, added_at)"
                " VALUES (?, ?, ?, 'pending', ?)",
                (ref.platform, ref.video_id, ref.url, datetime.now().isoformat()),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_pending(
        self, retry_failed: bool = False, limit: int | None = None
    ) -> list[sqlite3.Row]:
        statuses = ("pending", "failed") if retry_failed else ("pending",)
        sql = f"SELECT * FROM videos WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY pk"
        params: list[Any] = list(statuses)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            return list(self._conn.execute(sql, params))

    def mark_failed(self, pk: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE videos SET status='failed', error=?, processed_at=? WHERE pk=?",
                (error[:2000], datetime.now().isoformat(), pk),
            )
            self._conn.commit()

    def save_result(
        self, pk: int, fetched: FetchedVideo, transcript: str, analysis: Analysis
    ) -> None:
        with self._tx() as conn:
            # A short/photo ref may have resolved to a canonical id that already
            # exists in another row — same video. Merge onto that row instead of
            # hitting the UNIQUE(platform, video_id) constraint.
            existing = conn.execute(
                "SELECT pk FROM videos WHERE platform=? AND video_id=? AND pk != ?",
                (fetched.ref.platform, fetched.ref.video_id, pk),
            ).fetchone()
            if existing is not None:
                conn.execute("DELETE FROM videos_fts WHERE rowid=?", (pk,))
                conn.execute("DELETE FROM videos WHERE pk=?", (pk,))
                pk = int(existing["pk"])
            conn.execute(
                """UPDATE videos SET video_id=?, url=?, author=?, title=?, description=?,
                   upload_date=?, duration=?, transcript=?, category=?, summary=?,
                   analysis_json=?, status='done', error=NULL, processed_at=? WHERE pk=?""",
                (
                    fetched.ref.video_id,
                    fetched.ref.url,
                    fetched.author,
                    analysis.title or fetched.title,
                    fetched.description,
                    fetched.upload_date,
                    fetched.duration,
                    transcript,
                    analysis.category,
                    analysis.summary,
                    analysis.model_dump_json(),
                    datetime.now().isoformat(),
                    pk,
                ),
            )
            self._rebuild_flat(conn, pk, analysis)
            self._sync_fts(conn, pk)

    def _rebuild_flat(self, conn: sqlite3.Connection, pk: int, analysis: Analysis) -> None:
        conn.execute("DELETE FROM places WHERE video_pk=?", (pk,))
        conn.execute("DELETE FROM events WHERE video_pk=?", (pk,))
        for p in analysis.places:
            conn.execute(
                "INSERT INTO places (video_pk,name,kind,address,city,country,price_range)"
                " VALUES (?,?,?,?,?,?,?)",
                (pk, p.name, p.kind, p.address, p.city, p.country, p.price_range),
            )
        for e in analysis.events:
            conn.execute(
                "INSERT INTO events (video_pk,name,venue,city,start_date,end_date,time,price)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (pk, e.name, e.venue, e.city, e.start_date, e.end_date, e.time, e.price),
            )

    def _sync_fts(self, conn: sqlite3.Connection, pk: int) -> None:
        row = conn.execute("SELECT * FROM videos WHERE pk=?", (pk,)).fetchone()
        if row is None:
            return
        conn.execute("DELETE FROM videos_fts WHERE rowid=?", (pk,))
        names = " ".join(
            r[0]
            for r in conn.execute(
                "SELECT name FROM places WHERE video_pk=?"
                " UNION SELECT name FROM events WHERE video_pk=?",
                (pk, pk),
            )
            if r[0]
        )
        tags = ""
        if row["analysis_json"]:
            try:
                tags = " ".join(json.loads(row["analysis_json"]).get("tags") or [])
            except json.JSONDecodeError:
                tags = ""
        conn.execute(
            "INSERT INTO videos_fts (rowid, title, summary, description, transcript, tags, names)"
            " VALUES (?,?,?,?,?,?,?)",
            (pk, row["title"], row["summary"], row["description"], row["transcript"], tags, names),
        )

    def record_usage(self, model: str, purpose: str, usage: Usage) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage (ts, model, purpose, prompt_tokens, completion_tokens)"
                " VALUES (?,?,?,?,?)",
                (
                    datetime.now().isoformat(),
                    model,
                    purpose,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                ),
            )
            self._conn.commit()

    # --- reads ----------------------------------------------------------------

    def get(self, pk: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM videos WHERE pk=?", (pk,)).fetchone()
            return self._row_to_dict(row) if row else None

    def counts(self) -> dict[str, Any]:
        with self._lock:
            by_status = {
                r[0]: r[1]
                for r in self._conn.execute("SELECT status, COUNT(*) FROM videos GROUP BY status")
            }
            by_category = {
                r[0] or "(none)": r[1]
                for r in self._conn.execute(
                    "SELECT category, COUNT(*) FROM videos GROUP BY category ORDER BY 2 DESC"
                )
            }
            tokens = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT model, purpose, SUM(prompt_tokens) AS prompt_tokens,"
                    " SUM(completion_tokens) AS completion_tokens FROM usage"
                    " GROUP BY model, purpose"
                )
            ]
        return {"by_status": by_status, "by_category": by_category, "usage": tokens}

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["id"] = d.pop("pk")
        d["places"] = [
            dict(r)
            for r in self._conn.execute(
                "SELECT name,kind,address,city,country,price_range FROM places WHERE video_pk=?",
                (d["id"],),
            )
        ]
        d["events"] = [
            dict(r)
            for r in self._conn.execute(
                "SELECT name,venue,city,start_date,end_date,time,price FROM events"
                " WHERE video_pk=?",
                (d["id"],),
            )
        ]
        d["tags"] = []
        d["key_points"] = []
        if d.get("analysis_json"):
            try:
                parsed = json.loads(d["analysis_json"])
                d["tags"] = parsed.get("tags") or []
                d["key_points"] = parsed.get("key_points") or []
            except json.JSONDecodeError:
                pass
        d.pop("analysis_json", None)
        return d

    def search(
        self,
        categories: list[str] | None = None,
        city: str | None = None,
        upcoming_only: bool = False,
        today: date | str | None = None,
        keywords: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        match_any: bool = False,
        limit: int = 40,
        done_only: bool = True,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if done_only:
            where.append("v.status='done'")
        if categories:
            where.append(f"v.category IN ({','.join('?' * len(categories))})")
            params.extend(categories)
        if city:
            like = f"%{city.lower()}%"
            where.append(
                "(EXISTS(SELECT 1 FROM places p WHERE p.video_pk=v.pk AND ("
                "lower(p.city) LIKE ? OR lower(p.address) LIKE ? OR lower(p.name) LIKE ?))"
                " OR EXISTS(SELECT 1 FROM events e WHERE e.video_pk=v.pk AND ("
                "lower(e.city) LIKE ? OR lower(e.venue) LIKE ? OR lower(e.name) LIKE ?)))"
            )
            params.extend([like] * 6)
        if upcoming_only:
            if isinstance(today, date):
                today_s = today.isoformat()
            else:
                today_s = today or date.today().isoformat()
            where.append(
                "EXISTS(SELECT 1 FROM events e WHERE e.video_pk=v.pk AND ("
                "COALESCE(e.end_date, e.start_date) >= ?"
                " OR (e.start_date IS NULL AND e.end_date IS NULL)))"
            )
            params.append(today_s)
        if date_from or date_to:
            clauses = []
            if date_from:
                clauses.append("COALESCE(e.end_date, e.start_date) >= ?")
                params.append(date_from)
            if date_to:
                clauses.append("e.start_date <= ?")
                params.append(date_to)
            where.append(
                "EXISTS(SELECT 1 FROM events e WHERE e.video_pk=v.pk AND "
                + " AND ".join(clauses)
                + ")"
            )
        join = ""
        if keywords:
            tokens = [re.sub(r"[^\w'-]+", " ", k).split() for k in keywords]
            flat = [t for sub in tokens for t in sub if t]
            if flat:
                op = " OR " if match_any else " "
                match = op.join(_quote_fts(t) for t in flat)
                join = " JOIN videos_fts f ON f.rowid = v.pk"
                where.append("videos_fts MATCH ?")
                params.append(match)
        sql = "SELECT DISTINCT v.* FROM videos v" + join
        if where:
            sql += " WHERE " + " AND ".join(where)
        if upcoming_only:
            # soonest relevant event first; undated events last
            soonest = (
                "(SELECT MIN(COALESCE(e2.start_date, e2.end_date)) FROM events e2"
                " WHERE e2.video_pk=v.pk AND COALESCE(e2.end_date, e2.start_date) >= ?)"
            )
            sql += f" ORDER BY {soonest} IS NULL, {soonest} ASC"
            params.extend([today_s, today_s])
        else:
            sql += " ORDER BY v.pk DESC"
        sql += " LIMIT ?"
        params.append(limit)
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # FTS syntax edge cases must never crash the search — retry without FTS.
                if not keywords:
                    raise
                return self.search(
                    categories=categories,
                    city=city,
                    upcoming_only=upcoming_only,
                    today=today,
                    keywords=None,
                    date_from=date_from,
                    date_to=date_to,
                    match_any=match_any,
                    limit=limit,
                    done_only=done_only,
                )
        results = [self._row_to_dict(r) for r in rows]
        for d in results:
            d["has_undated_event"] = any(
                e["start_date"] is None and e["end_date"] is None for e in d["events"]
            )
        return results

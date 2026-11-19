"""Cache local em SQLite para as páginas já consultadas no Wikcionário.

Guarda o wikitexto bruto (e não o resultado já interpretado), assim melhorias
no parser valem também para as palavras que já estão no cache.
"""

import os
import sqlite3
import threading
import time
from pathlib import Path

# Depois desse prazo a entrada é considerada "velha": o app tenta atualizar,
# mas ainda a usa se estiver sem internet.
DEFAULT_TTL = 30 * 24 * 3600  # 30 dias


def default_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "br-dict" / "cache.db"


class Cache:
    def __init__(self, path=None, ttl: int = DEFAULT_TTL):
        self.path = Path(path) if path else default_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self._lock = threading.Lock()
        # As buscas rodam em threads; o lock serializa o acesso à conexão.
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                   query      TEXT PRIMARY KEY,
                   title      TEXT NOT NULL,
                   wikitext   TEXT NOT NULL,
                   fetched_at INTEGER NOT NULL
               )"""
        )
        self._db.commit()

    def get(self, query: str):
        """Retorna (título, wikitexto, está_fresco) ou None."""
        with self._lock:
            row = self._db.execute(
                "SELECT title, wikitext, fetched_at FROM entries WHERE query = ?",
                (query,),
            ).fetchone()
        if row is None:
            return None
        title, wikitext, fetched_at = row
        return title, wikitext, (time.time() - fetched_at) < self.ttl

    def put(self, query: str, title: str, wikitext: str) -> None:
        now = int(time.time())
        keys = {query, title}  # "Casa" e "casa" apontam para a mesma página
        with self._lock:
            self._db.executemany(
                "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?)",
                [(k, title, wikitext, now) for k in keys],
            )
            self._db.commit()

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entries")
            self._db.commit()
            self._db.execute("VACUUM")

    def close(self) -> None:
        with self._lock:
            self._db.close()

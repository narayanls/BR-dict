"""Banco offline: gerado localmente a partir do dump oficial do Wikcionário.

O dump (XML compactado em bz2) é baixado e descompactado em fluxo, sem
gravar o arquivo bruto em disco. De cada página fica só a seção de
português, sem traduções e pronúncia, comprimida com zlib. Como é
wikitexto, as melhorias no parser também valem para o banco já gerado.

O banco fica em ~/.local/share/br-dict/offline.db. O modo offline está
ativo sempre que esse arquivo existe.
"""

import bz2
import os
import sqlite3
import threading
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from email.utils import parsedate_to_datetime
from pathlib import Path

from .parser import portuguese_wikitext
from .wiktionary import USER_AGENT, candidates

DUMP_URL = (
    "https://dumps.wikimedia.org/ptwiktionary/latest/"
    "ptwiktionary-latest-pages-articles.xml.bz2"
)
SCHEMA_VERSION = "1"


def default_db_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return Path(base) / "br-dict" / "offline.db"


def fold(s: str) -> str:
    """Minúsculas e sem acentos: 'Açúcar' -> 'acucar'."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").casefold()


# --------------------------------------------------------------------------
# Leitura


class OfflineDB:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_db_path()
        self._lock = threading.Lock()
        self._db = None
        self.reload()

    def reload(self) -> None:
        """(Re)abre o banco, por exemplo depois de gerado ou atualizado."""
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
            if not self.path.exists():
                return
            try:
                db = sqlite3.connect(
                    self.path.as_uri() + "?mode=ro", uri=True, check_same_thread=False
                )
                version = db.execute(
                    "SELECT v FROM meta WHERE k = 'schema'"
                ).fetchone()
                if version and version[0] == SCHEMA_VERSION:
                    self._db = db
                else:
                    db.close()
            except sqlite3.Error:
                self._db = None

    @property
    def available(self) -> bool:
        return self._db is not None

    def info(self):
        if not self.available:
            return None
        with self._lock:
            meta = dict(self._db.execute("SELECT k, v FROM meta").fetchall())
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        return {
            "count": int(meta.get("count", 0)),
            "dump_date": meta.get("dump_date", ""),
            "built_at": meta.get("built_at", ""),
            "size": size,
        }

    def _page(self, title):
        row = self._db.execute(
            "SELECT title, wikitext FROM pages WHERE title = ?", (title,)
        ).fetchone()
        if row is None:
            target = self._db.execute(
                "SELECT target FROM redirects WHERE title = ?", (title,)
            ).fetchone()
            if target:
                row = self._db.execute(
                    "SELECT title, wikitext FROM pages WHERE title = ?", (target[0],)
                ).fetchone()
        if row is None:
            return None
        return row[0], zlib.decompress(row[1]).decode("utf-8")

    def lookup(self, word: str):
        """Retorna (título, wikitexto) ou None."""
        if not self.available:
            return None
        with self._lock:
            for title in candidates(word):
                page = self._page(title)
                if page:
                    return page
        return None

    def suggest(self, word: str, limit: int = 8) -> list:
        """Primeiro as grafias com acento ('acucar' -> 'açúcar'), depois prefixos."""
        if not self.available or not word.strip():
            return []
        key = fold(word.strip())
        with self._lock:
            rows = self._db.execute(
                "SELECT title FROM pages WHERE fold = ? LIMIT ?", (key, limit)
            ).fetchall()
            rows += self._db.execute(
                "SELECT title FROM pages WHERE fold > ? AND fold < ? "
                "ORDER BY length(title), title LIMIT ?",
                (key, key + "￿", limit),
            ).fetchall()
        out = []
        for (title,) in rows:
            if title not in out and title != word:
                out.append(title)
        return out[:limit]

    def remove(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
        for p in (self.path, self.path.with_name(self.path.name + ".part")):
            try:
                p.unlink()
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------
# Geração


class Cancelled(Exception):
    pass


def probe_size(url: str = DUMP_URL):
    """Tamanho do download em bytes (requisição HEAD), ou None."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(resp.headers.get("Content-Length") or 0) or None
    except (OSError, ValueError):
        return None


class _CountingReader:
    """Conta os bytes baixados (progresso) e permite cancelar no meio."""

    def __init__(self, fp, builder):
        self.fp, self.builder = fp, builder

    def read(self, n=-1):
        if self.builder.cancel_event.is_set():
            raise Cancelled()
        data = self.fp.read(n)
        self.builder.downloaded += len(data)
        return data


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_pages(stream):
    """Gera (título, namespace, destino_do_redirect, texto) de cada página."""
    events = ET.iterparse(stream, events=("start", "end"))
    _, root = next(events)
    for event, elem in events:
        if event != "end" or _local(elem.tag) != "page":
            continue
        title = ns = redirect = text = None
        for child in elem:
            name = _local(child.tag)
            if name == "title":
                title = child.text
            elif name == "ns":
                ns = child.text
            elif name == "redirect":
                redirect = child.get("title")
            elif name == "revision":
                for sub in child:
                    if _local(sub.tag) == "text":
                        text = sub.text
        yield title, ns, redirect, text
        root.clear()  # libera a memória das páginas já processadas


class Builder:
    """Baixa o dump e gera o banco numa thread. A interface lê o progresso."""

    def __init__(self, db_path: Path, url: str = DUMP_URL):
        self.db_path = Path(db_path)
        self.url = url
        self.state = "idle"  # idle | running | done | error | cancelled
        self.stage = ""
        self.downloaded = 0
        self.total = 0
        self.pages = 0
        self.error = None
        self.cancel_event = threading.Event()
        self._thread = None

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def fraction(self) -> float:
        return min(self.downloaded / self.total, 1.0) if self.total else 0.0

    def start(self, on_finish=None) -> None:
        self.state = "running"
        self._thread = threading.Thread(target=self._run, args=(on_finish,), daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def _run(self, on_finish):
        tmp = self.db_path.with_name(self.db_path.name + ".part")
        try:
            self._build(tmp)
            self.state = "done"
        except Cancelled:
            self.state = "cancelled"
        except Exception as exc:  # rede, disco cheio, XML corrompido...
            self.error = str(exc) or exc.__class__.__name__
            self.state = "error"
        finally:
            if self.state != "done":
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
            if on_finish:
                on_finish(self)

    def _build(self, tmp: Path):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if tmp.exists():
            tmp.unlink()

        self.stage = "Conectando…"
        req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.total = int(resp.headers.get("Content-Length") or 0)
            dump_date = ""
            try:
                dump_date = parsedate_to_datetime(resp.headers["Last-Modified"]).date().isoformat()
            except (KeyError, TypeError, ValueError):
                pass

            db = sqlite3.connect(tmp)
            try:
                db.executescript(
                    """PRAGMA journal_mode = OFF;
                       PRAGMA synchronous = OFF;
                       CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
                       CREATE TABLE pages (title TEXT PRIMARY KEY, fold TEXT NOT NULL,
                                           wikitext BLOB NOT NULL);
                       CREATE TABLE redirects (title TEXT PRIMARY KEY, target TEXT NOT NULL);"""
                )
                self.stage = "Baixando e processando o Wikcionário…"
                pages, redirects = [], []
                with bz2.BZ2File(_CountingReader(resp, self)) as xml:
                    for title, ns, redirect, text in _iter_pages(xml):
                        if ns != "0" or not title:
                            continue
                        if redirect:
                            redirects.append((title, redirect))
                        elif text:
                            section = portuguese_wikitext(text)
                            if section:
                                pages.append(
                                    (title, fold(title), zlib.compress(section.encode("utf-8"), 6))
                                )
                                self.pages += 1
                        if len(pages) >= 2000 or len(redirects) >= 2000:
                            self._flush(db, pages, redirects)

                self._flush(db, pages, redirects)
                self.stage = "Criando índices…"
                db.executescript(
                    """DELETE FROM redirects WHERE target NOT IN (SELECT title FROM pages);
                       CREATE INDEX pages_fold ON pages(fold);"""
                )
                db.executemany(
                    "INSERT INTO meta VALUES (?, ?)",
                    [
                        ("schema", SCHEMA_VERSION),
                        ("count", str(self.pages)),
                        ("dump_date", dump_date),
                        ("built_at", time.strftime("%Y-%m-%d")),
                        ("source", self.url),
                    ],
                )
                db.commit()
                self.stage = "Compactando…"
                db.execute("VACUUM")
            finally:
                db.close()

        if self.cancel_event.is_set():
            raise Cancelled()
        os.replace(tmp, self.db_path)  # troca atômica: o banco antigo vale até aqui

    @staticmethod
    def _flush(db, pages, redirects):
        db.executemany("INSERT OR REPLACE INTO pages VALUES (?, ?, ?)", pages)
        db.executemany("INSERT OR REPLACE INTO redirects VALUES (?, ?)", redirects)
        db.commit()
        pages.clear()
        redirects.clear()

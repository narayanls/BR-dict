"""Junta banco offline, cache, API e parser numa única operação de consulta.

Ordem de busca:
  1. banco offline (se instalado): instantâneo e sem rede;
  2. cache de consultas recentes;
  3. Wikcionário online, para palavras ausentes do banco ou do cache.
"""

from dataclasses import dataclass, field
from datetime import date

from . import wiktionary
from .cache import Cache
from .offline import OfflineDB
from .parser import Entry, parse_entry
from .wiktionary import NetworkError


@dataclass
class LookupResult:
    query: str
    entry: Entry = None
    suggestions: list = field(default_factory=list)
    source: str = "online"  # online | cache | offline-db
    stale: bool = False  # veio do cache vencido porque a rede falhou
    error: str = None  # falha de rede sem nada local
    searched_online: bool = True

    @property
    def found(self) -> bool:
        return self.entry is not None


def format_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


class Dictionary:
    def __init__(self, cache: Cache = None, offline: OfflineDB = None):
        self.cache = cache or Cache()
        self.offline = offline or OfflineDB()

    def lookup(self, word: str) -> LookupResult:
        query = " ".join(word.split())

        local = self.offline.lookup(query)
        if local:
            entry = parse_entry(local[1], local[0])
            if entry:
                return LookupResult(query, entry, source="offline-db")

        cached = self.cache.get(query)
        if cached and cached[2]:
            entry = parse_entry(cached[1], cached[0])
            if entry:
                return LookupResult(query, entry, source="cache")

        try:
            for title, text in wiktionary.fetch_candidates(query):
                entry = parse_entry(text, title)
                if entry:
                    self.cache.put(query, title, text)
                    return LookupResult(query, entry)
        except NetworkError as exc:
            if cached:
                entry = parse_entry(cached[1], cached[0])
                if entry:
                    return LookupResult(query, entry, source="cache", stale=True)
            if self.offline.available:
                return LookupResult(
                    query, suggestions=self.offline.suggest(query), searched_online=False
                )
            return LookupResult(query, error=str(exc))

        suggestions = self.offline.suggest(query)
        try:
            for s in wiktionary.suggest(query):
                if s != query and s not in suggestions:
                    suggestions.append(s)
        except NetworkError:
            pass
        return LookupResult(query, suggestions=suggestions[:8])

    def source_note(self, result: LookupResult) -> str:
        if result.source == "offline-db":
            info = self.offline.info() or {}
            when = format_date(info.get("dump_date") or info.get("built_at"))
            return f"banco offline de {when}" if when else "banco offline"
        return ""

    def clear_cache(self) -> None:
        self.cache.clear()

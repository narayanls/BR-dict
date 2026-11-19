"""Acesso à API do MediaWiki do Wikcionário em português (pt.wiktionary.org).

Só usa a biblioteca padrão. A política da Wikimedia exige um User-Agent
identificando o app e um contato.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from . import VERSION, WEBSITE

API_URL = "https://pt.wiktionary.org/w/api.php"
PAGE_URL = "https://pt.wiktionary.org/wiki/"
USER_AGENT = f"BR-dict/{VERSION} ({WEBSITE})"
TIMEOUT = 10


class NetworkError(Exception):
    """Falha de rede ou resposta inválida da API."""


def page_url(title: str) -> str:
    return PAGE_URL + urllib.parse.quote(title.replace(" ", "_"))


def _get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise NetworkError(str(exc)) from exc


def candidates(word: str) -> list:
    """Variações de caixa a tentar: o Wikcionário diferencia 'Brasil' de 'brasil'."""
    w = word.strip()
    out = []
    for c in (w, w.lower(), w[:1].upper() + w[1:].lower()):
        if c and c not in out:
            out.append(c)
    return out


def fetch_candidates(word: str) -> list:
    """Busca todas as variações numa só requisição.

    Retorna [(título_resolvido, wikitexto), ...] na ordem de preferência,
    seguindo redirecionamentos e omitindo páginas inexistentes.
    """
    titles = candidates(word)
    if not titles:
        return []
    data = _get(
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(titles),
            "redirects": "1",
        }
    )
    query = data.get("query", {})

    # título pedido -> título final (após normalização e redirecionamentos)
    resolved = {t: t for t in titles}
    for key in ("normalized", "redirects"):
        for step in query.get(key, []):
            for t, current in resolved.items():
                if current == step.get("from"):
                    resolved[t] = step.get("to")

    contents = {}
    for page in query.get("pages", []):
        if page.get("missing") or page.get("invalid"):
            continue
        revs = page.get("revisions") or []
        if not revs:
            continue
        text = revs[0].get("slots", {}).get("main", {}).get("content")
        if text is not None:
            contents[page["title"]] = text

    out, seen = [], set()
    for t in titles:
        final = resolved.get(t)
        if final in contents and final not in seen:
            seen.add(final)
            out.append((final, contents[final]))
    return out


def suggest(word: str, limit: int = 8) -> list:
    """Sugestões de títulos parecidos (prefixo e erros de digitação)."""
    data = _get(
        {
            "action": "opensearch",
            "search": word,
            "limit": str(limit),
            "namespace": "0",
            "profile": "fuzzy",
        }
    )
    # formatversion não se aplica ao opensearch: [busca, [títulos], [descr], [urls]]
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return [t for t in data[1] if isinstance(t, str)]
    return []

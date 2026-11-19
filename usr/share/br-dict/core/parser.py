"""Interpreta o wikitexto de uma página do Wikcionário em português.

Extrai apenas a seção de português (={{-pt-}}=) e, dentro dela, as classes
gramaticais com suas acepções, exemplos, etimologia, sinônimos e antônimos.

O texto sai em Pango markup: negrito/itálico viram <b>/<i> e os links
internos ([[palavra]]) viram <a href="palavra">, que a interface usa para
navegar entre verbetes. Não depende de GTK, então dá para testar isolado.
"""

import html
import re
from dataclasses import dataclass, field

from .wiktionary import page_url

# --------------------------------------------------------------------------
# Estruturas de dados


@dataclass
class Sense:
    text: str
    level: int = 1  # 1 = "#", 2 = "##" (subacepção)
    examples: list = field(default_factory=list)


@dataclass
class Group:
    pos: str  # classe gramatical: "Substantivo", "Verbo"...
    headword: str = ""  # linha de cabeçalho, ex.: "ca.sa, feminino"
    senses: list = field(default_factory=list)


@dataclass
class Entry:
    title: str
    url: str
    groups: list = field(default_factory=list)
    etymology: list = field(default_factory=list)
    synonyms: list = field(default_factory=list)
    antonyms: list = field(default_factory=list)


# --------------------------------------------------------------------------
# Predefinições (templates)

SECTION_TEMPLATES = {
    "-pt-": "Português",
    "-subst-": "Substantivo",
    "-verb-": "Verbo",
    "-adj-": "Adjetivo",
    "-adv-": "Advérbio",
    "-pron-": "Pronúncia",
    "-pronome-": "Pronome",
    "-prep-": "Preposição",
    "-conj-": "Conjunção",
    "-interj-": "Interjeição",
    "-num-": "Numeral",
    "-art-": "Artigo",
    "-etimo-": "Etimologia",
    "-trad-": "Tradução",
    "-sin-": "Sinônimos",
    "-ant-": "Antônimos",
    "-ver-": "Ver também",
    "-ref-": "Referências",
}

GRAMMAR = {
    "m": "masculino",
    "f": "feminino",
    "mf": "masculino e feminino",
    "m2g": "comum de dois gêneros",
    "c2g": "comum de dois gêneros",
    "2g": "comum de dois gêneros",
    "n": "neutro",
    "s": "singular",
    "sg": "singular",
    "p": "plural",
    "pl": "plural",
    "i": "invariável",
    "inv": "invariável",
    "t": "transitivo",
    "td": "transitivo direto",
    "ti": "transitivo indireto",
    "tdi": "transitivo direto e indireto",
    "int": "intransitivo",
    "pr": "pronominal",
    "lig": "de ligação",
}

SCOPE_TEMPLATES = {"escopo", "escopo1", "escopo2", "escopop", "escopoeq", "escopou", "escopo-"}
GRAMMAR_TEMPLATES = {"gramática", "gramatica", "gram"}
LINK_TEMPLATES = {"l", "ll", "link", "lnk", "link preto", "m", "mention"}
LANG_CODES = {"pt", "pt-br", "pt-pt", "br"}
MEDIA_NAMESPACES = {"imagem", "image", "ficheiro", "arquivo", "file", "categoria", "category"}


def _render_template(inner: str) -> str:
    # protege os "|" de [[alvo|rótulo]] antes de separar os argumentos
    inner = re.sub(r"\[\[[^\]]*\]\]", lambda m: m.group(0).replace("|", "\x03"), inner)
    parts = [p.replace("\x03", "|").strip() for p in inner.split("|")]
    name, low = parts[0], parts[0].lower()
    args = [p for p in parts[1:] if not re.match(r"^[\w-]+\s*=", p)]  # só posicionais

    if low in SECTION_TEMPLATES:
        return SECTION_TEMPLATES[low]
    if len(low) > 2 and low.startswith("-") and low.endswith("-"):
        return name.strip("-").capitalize()
    if low in SCOPE_TEMPLATES:
        vals = [a for a in args if a and a.lower() not in LANG_CODES]
        return f"({', '.join(vals)})" if vals else ""
    if low in GRAMMAR_TEMPLATES:
        return ", ".join(GRAMMAR.get(a.lower(), a) for a in args if a)
    if low in LINK_TEMPLATES:
        if low in {"link preto", "lnk"} or len(args) == 1:
            target, label = args[0] if args else "", ""
        else:  # {{l|pt|alvo|rótulo}}
            target = args[1] if len(args) > 1 else ""
            label = args[2] if len(args) > 2 else ""
        if not target:
            return label
        return f"[[{target}|{label}]]" if label else f"[[{target}]]"
    if low in {"w", "wp", "wikipédia"}:
        return args[-1] if args else ""
    # Predefinições desconhecidas (pronúncia, categorias, caixas...) somem.
    return ""


def _expand_templates(s: str) -> str:
    pattern = re.compile(r"\{\{([^{}]*)\}\}")
    for _ in range(25):  # expande de dentro para fora
        new = pattern.sub(lambda m: _render_template(m.group(1)), s)
        if new == s:
            break
        s = new
    return s.replace("{{", "").replace("}}", "")


# --------------------------------------------------------------------------
# Limpeza e conversão para Pango markup

COMMENT = re.compile(r"<!--.*?-->", re.S)
REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
EXT_LINK = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")


def _strip_media(s: str) -> str:
    """Remove [[Imagem:...]], [[Categoria:...]] etc., inclusive com links aninhados."""
    out, i = [], 0
    while i < len(s):
        if s.startswith("[[", i):
            m = re.match(r"\[\[\s*([^:|\]]+)\s*:", s[i:])
            if m and m.group(1).strip().lower() in MEDIA_NAMESPACES:
                depth, j = 0, i
                while j < len(s):
                    if s.startswith("[[", j):
                        depth, j = depth + 1, j + 2
                    elif s.startswith("]]", j):
                        depth, j = depth - 1, j + 2
                        if depth == 0:
                            break
                    else:
                        j += 1
                i = j
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _apply_toggles(s: str) -> str:
    """Converte os marcadores de ''' e '' em tags bem aninhadas."""
    tags = {"\x01": "b", "\x02": "i"}
    out, stack = [], []
    for ch in s:
        tag = tags.get(ch)
        if tag is None:
            out.append(ch)
        elif tag in stack:
            reopen = []
            while stack:
                top = stack.pop()
                out.append(f"</{top}>")
                if top == tag:
                    break
                reopen.append(top)
            for t in reversed(reopen):
                out.append(f"<{t}>")
                stack.append(t)
        else:
            out.append(f"<{tag}>")
            stack.append(tag)
    while stack:
        out.append(f"</{stack.pop()}>")
    return re.sub(r"<(b|i)></\1>", "", "".join(out))


def render(s: str, markup: bool = True) -> str:
    """Wikitexto -> Pango markup (ou texto puro, com markup=False)."""
    s = COMMENT.sub("", s)
    s = REF.sub("", s)
    s = _strip_media(s)
    s = _expand_templates(s)
    s = HTML_TAG.sub("", s)
    s = html.unescape(s)

    links = []

    def link_repl(m):
        target = (m.group(1) or "").strip()
        label = m.group(2)
        label = (target if label is None else label).strip()
        label = label.replace("'''", "").replace("''", "")
        if ":" in target:  # interwiki ([[en:casa]]) ou outros espaços
            return "" if re.match(r"^:?[a-z-]{2,12}:", target) and not m.group(2) else label
        target = target.split("#")[0].strip()
        if not markup or not target:
            return label
        links.append((target, label))
        return f"\x00{len(links) - 1}\x00"

    s = LINK.sub(link_repl, s)
    s = EXT_LINK.sub(lambda m: m.group(1) or "", s)
    s = s.replace("'''", "\x01").replace("''", "\x02")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s+([,.;:!?)])", r"\1", s).strip()

    if not markup:
        return s.replace("\x01", "").replace("\x02", "")

    s = _apply_toggles(escape(s))

    def restore(m):
        target, label = links[int(m.group(1))]
        return f'<a href="{escape(target)}">{escape(label)}</a>'

    return re.sub(r"\x00(\d+)\x00", restore, s)


def plain(s: str) -> str:
    return render(s, markup=False)


# --------------------------------------------------------------------------
# Estrutura da página

LEVEL1 = re.compile(r"^=([^=].*[^=]|[^=])=$")
HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1$")

IGNORED_SECTIONS = {
    "pronúncia", "tradução", "traduções", "ver também", "referências",
    "anagramas", "conjugação", "ligações externas", "notas", "descendentes",
    "formas alternativas", "verbetes derivados", "termos derivados",
    "expressões", "fraseologia", "cognatos", "homófonos", "parônimos",
    "hiperônimos", "hipônimos", "divisão silábica", "fontes", "galeria",
    "no wikcionário", "outras grafias",
}
ETYMOLOGY = {"etimologia"}
SYNONYMS = {"sinônimos", "sinónimos", "sinonímia"}
ANTONYMS = {"antônimos", "antónimos", "antonímia"}


def _is_portuguese(heading: str) -> bool:
    h = heading.replace(" ", "").lower()
    return h in {"{{-pt-}}", "português", "portugues"} or h.startswith("{{-pt-|")


def portuguese_section(wikitext: str):
    """Linhas da seção de português, ou None se a página não tiver uma."""
    lines = wikitext.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = LEVEL1.match(line.strip())
        if not m:
            continue
        if start is None:
            if _is_portuguese(m.group(1).strip()):
                start = i + 1
        else:
            return lines[start:i]
    return lines[start:] if start is not None else None


def _split_sections(lines):
    sections, name, body = [], None, []
    for line in lines:
        m = HEADING.match(line.strip())
        if m:
            if name is not None:
                sections.append((name, body))
            name, body = plain(m.group(2)), []
        elif name is not None:
            body.append(line)
    if name is not None:
        sections.append((name, body))
    return sections


def _base_name(name: str) -> str:
    """'Substantivo¹' / 'Substantivo 2' -> 'substantivo'."""
    return re.sub(r"[\s\d¹²³⁴⁵⁶⁷⁸⁹⁰]+$", "", name).strip().lower()


CATEGORY_LINE = re.compile(r"^\[\[[^\]]*:[^\]]*\]\]\s*$")


def portuguese_wikitext(wikitext: str):
    """Versão enxuta da página para o banco offline.

    Mantém só a seção de português, sem as seções que o app não exibe
    (traduções, pronúncia...) nem categorias. O resultado continua sendo
    wikitexto válido para parse_entry(). Retorna None se não houver acepções.
    """
    lines = portuguese_section(wikitext)
    if not lines or not any(line.startswith("#") for line in lines):
        return None
    out, skip_level = [], None
    for line in lines:
        m = HEADING.match(line.strip())
        if m:
            level = len(m.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and _base_name(plain(m.group(2))) in IGNORED_SECTIONS:
                skip_level = level
                continue
        if skip_level is None and not CATEGORY_LINE.match(line.strip()):
            out.append(line)
    return "={{-pt-}}=\n" + "\n".join(out).strip()


def _parse_group(name, lines):
    group = Group(pos=re.sub(r"[\s\d¹²³⁴⁵⁶⁷⁸⁹⁰]+$", "", name).strip() or name)
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"^(#+)([:*]*)\s*(.*)$", line)
            hashes, marker, body = m.groups()
            if marker.startswith("*"):  # citações longas: ignoradas
                continue
            text = render(body)
            if not text:
                continue
            if marker.startswith(":"):
                if group.senses:
                    group.senses[-1].examples.append(text)
            else:
                group.senses.append(Sense(text=text, level=min(len(hashes), 3)))
        elif not group.headword and line.startswith("'''"):
            group.headword = render(line)
    return group if group.senses else None


def _collect_words(lines, limit=40):
    words = []
    for raw in lines:
        line = raw.strip()
        if not line or line[0] not in "*#:":
            continue
        expanded = _expand_templates(COMMENT.sub("", line))
        targets = [t.split("#")[0].strip() for t, _ in LINK.findall(expanded)]
        if not targets:  # lista sem links: separa por vírgula
            body = plain(line.lstrip("*#: "))
            body = re.sub(r"^(De|Da acepção|Acepção)\s*[\d,\s e]+:\s*", "", body)
            targets = [w.strip() for w in re.split(r"[,;]", body)]
        for t in targets:
            if t and ":" not in t and t not in words:
                words.append(t)
    return words[:limit]


def _collect_text(lines, limit=4):
    out = []
    for raw in lines:
        line = raw.strip().lstrip("*#: ")
        if not line:
            continue
        text = render(line)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def parse_entry(wikitext: str, title: str):
    """Retorna um Entry, ou None se não houver acepções em português."""
    lines = portuguese_section(wikitext)
    if lines is None:
        return None
    entry = Entry(title=title, url=page_url(title))
    for name, body in _split_sections(lines):
        base = _base_name(name)
        if base in ETYMOLOGY:
            entry.etymology.extend(_collect_text(body))
        elif base in SYNONYMS:
            entry.synonyms.extend(w for w in _collect_words(body) if w not in entry.synonyms)
        elif base in ANTONYMS:
            entry.antonyms.extend(w for w in _collect_words(body) if w not in entry.antonyms)
        elif base not in IGNORED_SECTIONS:
            group = _parse_group(name, body)
            if group:
                entry.groups.append(group)
    return entry if entry.groups else None

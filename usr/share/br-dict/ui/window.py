"""Janela principal: campo de busca, resultados e navegação entre verbetes."""

import html
import re
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402


def _markup_label(markup: str, css=()) -> Gtk.Label:
    label = Gtk.Label(
        xalign=0,
        wrap=True,
        wrap_mode=Pango.WrapMode.WORD_CHAR,
        selectable=True,
        css_classes=list(css),
    )
    try:
        Pango.parse_markup(markup, -1, "\0")  # valida antes de aplicar
        label.set_markup(markup)
    except GLib.Error:
        label.set_text(html.unescape(re.sub(r"<[^>]+>", "", markup)))
    return label


def _heading(text: str) -> Gtk.Label:
    return Gtk.Label(label=text, xalign=0, css_classes=["heading", "accent"])


class BrDictWindow(Adw.ApplicationWindow):
    def __init__(self, app, dictionary):
        super().__init__(application=app, title="BR-dict")
        self.set_default_size(720, 680)
        self.dictionary = dictionary
        self.history = []
        self.current_word = None
        self.current_entry = None
        self._request = 0

        self._build_ui()
        self._setup_actions()
        self.stack.set_visible_child_name("welcome")
        self.search.grab_focus()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        header = Adw.HeaderBar()

        self.back_button = Gtk.Button(
            icon_name="go-previous-symbolic", tooltip_text="Voltar (Alt+←)",
            action_name="win.back",
        )
        header.pack_start(self.back_button)

        self.search = Gtk.SearchEntry(placeholder_text="Buscar palavra…", hexpand=True)
        self.search.connect("activate", lambda e: self.lookup(e.get_text()))
        header.set_title_widget(Adw.Clamp(maximum_size=440, child=self.search))

        menu = Gio.Menu()
        menu.append("Abrir no Wikcionário", "win.open-browser")
        section = Gio.Menu()
        section.append("Modo offline…", "app.offline")
        section.append("Limpar cache", "app.clear-cache")
        section.append("Sobre o BR-dict", "app.about")
        menu.append_section(None, section)
        header.pack_end(
            Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                           primary=True, tooltip_text="Menu principal")
        )

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)

        self.stack.add_named(
            Adw.StatusPage(
                icon_name="system-search-symbolic",
                title="BR-dict",
                description="Digite uma palavra e tecle Enter para ver o significado.",
            ),
            "welcome",
        )

        spinner = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
        spinner.set_size_request(48, 48)
        spinner.set_halign(Gtk.Align.CENTER)
        spinner.set_valign(Gtk.Align.CENTER)
        self.stack.add_named(spinner, "loading")

        self.notfound_page = Adw.StatusPage(icon_name="edit-find-symbolic")
        self.stack.add_named(self.notfound_page, "notfound")

        self.error_page = Adw.StatusPage(
            icon_name="network-offline-symbolic",
            title="Sem conexão",
            description="Não foi possível acessar o Wikcionário e esta palavra não está no cache.",
        )
        self.stack.add_named(self.error_page, "error")

        self.results_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.stack.add_named(self.results_scroll, "results")

        self.toasts = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)

    def _setup_actions(self):
        self.back_action = Gio.SimpleAction.new("back", None)
        self.back_action.connect("activate", lambda *a: self.go_back())
        self.back_action.set_enabled(False)
        self.add_action(self.back_action)

        focus = Gio.SimpleAction.new("focus-search", None)
        focus.connect("activate", lambda *a: self._focus_search())
        self.add_action(focus)

        self.browser_action = Gio.SimpleAction.new("open-browser", None)
        self.browser_action.connect("activate", lambda *a: self._open_browser())
        self.browser_action.set_enabled(False)
        self.add_action(self.browser_action)

    def _focus_search(self):
        self.search.grab_focus()
        self.search.select_region(0, -1)

    def toast(self, text: str):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    # ------------------------------------------------------------ consulta

    def lookup(self, word: str, push_history: bool = True):
        word = " ".join(word.split())
        if not word:
            return
        if push_history and self.current_word and self.current_word != word:
            self.history.append(self.current_word)
        self.current_word = word
        self.back_action.set_enabled(bool(self.history))

        if self.search.get_text() != word:
            self.search.set_text(word)
            self.search.set_position(-1)

        self._request += 1
        request_id = self._request
        self.stack.set_visible_child_name("loading")
        threading.Thread(target=self._worker, args=(word, request_id), daemon=True).start()

    def _worker(self, word, request_id):
        try:
            result = self.dictionary.lookup(word)
        except Exception as exc:  # nunca deixar a thread morrer em silêncio
            result = exc
        GLib.idle_add(self._on_result, request_id, result)

    def _on_result(self, request_id, result):
        if request_id != self._request:  # resposta de uma busca já substituída
            return GLib.SOURCE_REMOVE

        self.current_entry = None
        self.browser_action.set_enabled(False)

        if isinstance(result, Exception):
            self.error_page.set_title("Erro inesperado")
            self.error_page.set_description(GLib.markup_escape_text(str(result)))
            self.stack.set_visible_child_name("error")
        elif result.found:
            self.current_entry = result.entry
            self.browser_action.set_enabled(True)
            self._show_entry(result.entry, self.dictionary.source_note(result))
            if result.stale:
                self.toast("Sem conexão: mostrando a versão do cache")
        elif result.error:
            self.error_page.set_title("Sem conexão")
            self.error_page.set_description(
                "Não foi possível acessar o Wikcionário e esta palavra não está no cache."
            )
            self.stack.set_visible_child_name("error")
        else:
            self._show_not_found(result.query, result.suggestions, result.searched_online)
        return GLib.SOURCE_REMOVE

    def go_back(self):
        if self.history:
            self.lookup(self.history.pop(), push_history=False)

    def _open_browser(self):
        if self.current_entry:
            Gtk.UriLauncher(uri=self.current_entry.url).launch(self, None, None, None)

    def _on_link(self, _label, uri):
        if uri.startswith(("http://", "https://")):
            return False  # deixa o GTK abrir no navegador
        self.lookup(uri)
        return True

    # ---------------------------------------------------------- renderização

    def _show_not_found(self, query, suggestions, searched_online=True):
        page = self.notfound_page
        page.set_title("Palavra não encontrada")
        q = GLib.markup_escape_text(query)
        if searched_online:
            text = f"“{q}” não tem verbete em português no Wikcionário."
        else:
            text = f"“{q}” não está no banco offline, e não há conexão para buscar online."
        page.set_description(text + ("\nVocê quis dizer:" if suggestions else ""))
        flow = None
        if suggestions:
            flow = Gtk.FlowBox(
                selection_mode=Gtk.SelectionMode.NONE, halign=Gtk.Align.CENTER,
                max_children_per_line=4, column_spacing=6, row_spacing=6,
            )
            for s in suggestions:
                btn = Gtk.Button(label=s, css_classes=["pill"])
                btn.connect("clicked", lambda _b, w=s: self.lookup(w))
                flow.append(btn)
        page.set_child(flow)
        self.stack.set_visible_child_name("notfound")

    def _link_label(self, markup, css=(), margin_start=0):
        label = _markup_label(markup, css)
        label.set_margin_start(margin_start)
        label.connect("activate-link", self._on_link)
        return label

    def _word_list(self, words):
        links = ", ".join(
            f'<a href="{GLib.markup_escape_text(w)}">{GLib.markup_escape_text(w)}</a>'
            for w in words
        )
        return self._link_label(links)

    def _show_entry(self, entry, note=""):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22,
                      margin_top=24, margin_bottom=32, margin_start=18, margin_end=18)

        box.append(Gtk.Label(label=entry.title, xalign=0, selectable=True,
                             wrap=True, css_classes=["title-1"]))

        for group in entry.groups:
            gbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            gbox.append(_heading(group.pos))
            if group.headword:
                gbox.append(self._link_label(group.headword, css=["dim-label"]))
            number = 0
            for sense in group.senses:
                if sense.level == 1:
                    number += 1
                    prefix = f"<b>{number}.</b> "
                else:
                    prefix = "• "
                indent = 18 * (sense.level - 1)
                gbox.append(self._link_label(prefix + sense.text, margin_start=indent))
                for example in sense.examples:
                    gbox.append(self._link_label(
                        f"<i>{example}</i>", css=["dim-label"], margin_start=indent + 22,
                    ))
            box.append(gbox)

        for title, words in (("Sinônimos", entry.synonyms), ("Antônimos", entry.antonyms)):
            if words:
                sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                sbox.append(_heading(title))
                sbox.append(self._word_list(words))
                box.append(sbox)

        if entry.etymology:
            ebox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            ebox.append(_heading("Etimologia"))
            for line in entry.etymology:
                ebox.append(self._link_label(line))
            box.append(ebox)

        box.append(self._link_label(
            f'Fonte: <a href="{GLib.markup_escape_text(entry.url)}">Wikcionário</a>'
            + (f", {GLib.markup_escape_text(note)}" if note else "")
            + " · CC BY-SA 4.0",
            css=["caption", "dim-label"],
        ))

        self.results_scroll.set_child(Adw.Clamp(maximum_size=760, child=box))
        self.results_scroll.get_vadjustment().set_value(0)
        self.stack.set_visible_child_name("results")

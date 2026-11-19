#!/usr/bin/env python3
"""BR-dict: dicionário de português do Brasil baseado no Wikcionário.

Uso: br-dict [palavra]
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from core import APP_ID, APP_NAME, VERSION, WEBSITE  # noqa: E402
from core.dictionary import Dictionary  # noqa: E402
from core.offline import Builder  # noqa: E402
from ui.offline_dialog import OfflineDialog  # noqa: E402
from ui.window import BrDictWindow  # noqa: E402


class BrDictApp(Adw.Application):
    def __init__(self, initial_word=None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)
        self.initial_word = initial_word
        self.dictionary = None
        self.builder = None  # geração do banco offline em andamento

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.dictionary = Dictionary()

        for name, callback in (
            ("about", self._on_about),
            ("clear-cache", self._on_clear_cache),
            ("offline", self._on_offline),
            ("quit", lambda *a: self.quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.focus-search", ["<Control>f", "<Control>l"])
        self.set_accels_for_action("win.back", ["<Alt>Left"])

    def do_activate(self):
        window = self.props.active_window or BrDictWindow(self, self.dictionary)
        window.present()
        if self.initial_word:
            window.lookup(self.initial_word)
            self.initial_word = None

    def _on_clear_cache(self, *_):
        self.dictionary.clear_cache()
        if self.props.active_window:
            self.props.active_window.toast("Cache limpo")

    def _on_offline(self, *_):
        OfflineDialog(self).present(self.props.active_window)

    def start_offline_build(self):
        if self.builder and self.builder.running:
            return
        self.builder = Builder(self.dictionary.offline.path)
        self.builder.start(
            on_finish=lambda b: GLib.idle_add(self._on_build_finished, b)
        )

    def _on_build_finished(self, builder):
        window = self.props.active_window
        if builder.state == "done":
            self.dictionary.offline.reload()
            message = "Modo offline ativado"
        elif builder.state == "error":
            message = "Falha ao gerar o banco offline"
        else:
            message = "Download do banco offline cancelado"
        if window and hasattr(window, "toast"):
            window.toast(message)
        return GLib.SOURCE_REMOVE

    def _on_about(self, *_):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="narayanls",
            website=WEBSITE,
            issue_url=WEBSITE + "/issues",
            license_type=Gtk.License.GPL_3_0,
            comments="Dicionário de português do Brasil.\n"
                     "Definições do Wikcionário, licenciadas sob CC BY-SA 4.0.",
        )
        about.present(self.props.active_window)


def main() -> int:
    word = " ".join(a for a in sys.argv[1:] if not a.startswith("-")) or None
    app = BrDictApp(initial_word=word)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())

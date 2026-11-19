"""Diálogo do modo offline: baixar, atualizar ou remover o banco local.

O download roda no Builder, que pertence ao app. Fechar o diálogo não
interrompe nada; ao reabrir, o progresso continua aparecendo.
"""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from core.dictionary import format_date  # noqa: E402
from core.offline import probe_size  # noqa: E402


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.0f} MB" if n >= 10_000_000 else f"{n / 1_000_000:.1f} MB"


def _thousands(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class OfflineDialog(Adw.PreferencesDialog):
    def __init__(self, app):
        super().__init__(title="Modo offline", search_enabled=False)
        self.set_content_height(460)
        self.app = app
        self.offline = app.dictionary.offline
        self._download_size = None

        page = Adw.PreferencesPage()
        self.add(page)

        group = Adw.PreferencesGroup(
            description=(
                "Baixa o conteúdo do Wikcionário e gera um banco local. Com ele, as "
                "consultas funcionam sem internet. Palavras que não estiverem no "
                "banco continuam sendo buscadas online."
            )
        )
        page.add(group)

        self.status_row = Adw.ActionRow(title="Banco offline")
        self.status_row.set_subtitle_selectable(True)
        self.main_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.main_button.connect("clicked", self._on_main)
        self.remove_button = Gtk.Button(
            icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
            tooltip_text="Remover banco offline", css_classes=["flat"],
        )
        self.remove_button.connect("clicked", self._on_remove)
        self.status_row.add_suffix(self.remove_button)
        self.status_row.add_suffix(self.main_button)
        group.add(self.status_row)

        # Progresso
        self.progress_group = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                      margin_top=6, margin_bottom=6)
        self.stage_label = Gtk.Label(xalign=0, css_classes=["heading"])
        self.progress_bar = Gtk.ProgressBar(show_text=True)
        self.detail_label = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"])
        cancel = Gtk.Button(label="Cancelar", halign=Gtk.Align.END, css_classes=["pill"])
        cancel.connect("clicked", lambda *_: self.app.builder and self.app.builder.cancel())
        for w in (self.stage_label, self.progress_bar, self.detail_label, cancel):
            box.append(w)
        self.progress_group.add(box)
        page.add(self.progress_group)

        page.add(Adw.PreferencesGroup(
            description=(
                "O processamento leva alguns minutos e usa a CPU durante esse tempo. "
                "Você pode fechar esta janela e continuar usando o app enquanto isso. "
                "Conteúdo do Wikcionário sob licença CC BY-SA 4.0."
            )
        ))

        self._timer = GLib.timeout_add(300, self._tick)
        self.connect("closed", self._on_closed)
        self.refresh()

        if not self.offline.available:
            threading.Thread(target=self._probe, daemon=True).start()

    # ------------------------------------------------------------------

    def _probe(self):
        size = probe_size()
        GLib.idle_add(self._set_size, size)

    def _set_size(self, size):
        self._download_size = size
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _tick(self):
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def _on_closed(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def refresh(self):
        builder = self.app.builder
        running = bool(builder and builder.running)
        info = self.offline.info()

        self.progress_group.set_visible(running)
        self.main_button.set_sensitive(not running)
        self.remove_button.set_visible(bool(info) and not running)

        if info:
            when = format_date(info["dump_date"]) or format_date(info["built_at"])
            self.status_row.set_subtitle(
                f"Ativo · {_thousands(info['count'])} verbetes · {_mb(info['size'])}"
                + (f" · dados de {when}" if when else "")
            )
            self.main_button.set_label("Atualizar")
            self.main_button.set_css_classes([])
        else:
            if builder and builder.state == "error":
                sub = f"A última tentativa falhou: {builder.error}"
            elif self._download_size:
                sub = f"Não instalado · download de {_mb(self._download_size)}"
            else:
                sub = "Não instalado"
            self.status_row.set_subtitle(GLib.markup_escape_text(sub))
            self.main_button.set_label("Baixar")
            self.main_button.set_css_classes(["suggested-action"])

        if running:
            self.stage_label.set_text(builder.stage)
            if builder.total:
                self.progress_bar.set_fraction(builder.fraction)
                self.progress_bar.set_text(f"{builder.fraction * 100:.0f}%")
                done = f"{_mb(builder.downloaded)} de {_mb(builder.total)}"
            else:
                self.progress_bar.pulse()
                self.progress_bar.set_text("")
                done = _mb(builder.downloaded)
            self.detail_label.set_text(f"{done} · {_thousands(builder.pages)} verbetes")

    def _on_main(self, *_):
        self.app.start_offline_build()
        self.refresh()

    def _on_remove(self, *_):
        dialog = Adw.AlertDialog(
            heading="Remover banco offline?",
            body="As consultas voltarão a depender da internet. "
                 "Você pode baixar o banco de novo quando quiser.",
        )
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("remove", "Remover")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_remove_response)
        dialog.present(self)

    def _on_remove_response(self, _dialog, response):
        if response == "remove":
            self.offline.remove()
            self.refresh()
            threading.Thread(target=self._probe, daemon=True).start()

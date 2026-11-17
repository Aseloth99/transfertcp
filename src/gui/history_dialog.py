"""Transfer geçmişi penceresi: aranabilir, sıralanabilir tablo; geçmiş boşken başlık + ne yapılacağı (rehberli boş durum)."""

import os
import subprocess
import sys
from datetime import datetime

from PyQt6.QtCore import Qt, QSize, QTimer, QUrl
from PyQt6.QtGui import QAction, QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from ..utils.config import get_config
from ..utils.error_text import localize_error
from ..utils.helpers import format_bytes
from ..utils.locales import t, get_active_language
from .chrome_dialog import ChromeDialog
from .palette import is_dark
from .trust_dialog import ask_confirm
from .icons import trash_icon
from .widgets.glyph_icons import glyph_icon

_LIMIT = 100
_SORT_ROLE = Qt.ItemDataRole.UserRole + 1
_PATH_ROLE = Qt.ItemDataRole.UserRole + 2
COL_ICON, COL_FILE, COL_DEVICE, COL_SIZE, COL_DATE = range(5)

# QLabel[tone=...] ile aynı renkler (dark.qss / light.qss)
_TONES = {
    True: {"ok": "#4CAF50", "err": "#FF6B6B", "warn": "#FF9800", "muted": "#9e9e9e"},
    False: {"ok": "#2E7D32", "err": "#C62828", "warn": "#C2410C", "muted": "#616161"},
}
_STATUS_TONE = {"completed": "ok", "failed": "err", "cancelled": "muted"}


def _format_time(value, lang: str) -> str:
    """Kayıttaki ISO zamanı okunur yaz ("2026-11-17T15:24:31.705133" yerine "17.11.2026 15:24")."""
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value or "")
    return moment.strftime("%d.%m.%Y %H:%M" if lang == "tr" else "%Y-%m-%d %H:%M")


def open_path(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def reveal_path(path: str) -> None:
    """Dosyayı klasöründe seçili göster (Windows/macOS); diğerlerinde klasörü aç."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


class _SortItem(QTableWidgetItem):
    """Görünen metinden bağımsız sıralama (boyut sayıyla, tarih ISO zamanla)."""

    def __lt__(self, other):
        mine, theirs = self.data(_SORT_ROLE), other.data(_SORT_ROLE)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class HistoryDialog(ChromeDialog):
    """Son 100 transferin tablosu; arama veritabanında yapılır, temizleme düğmesi onay ister."""

    def __init__(self, parent=None, lang: str | None = None) -> None:
        if lang is None:
            lang = get_active_language(get_config())
        super().__init__(parent, t("history_dialog_title", lang))
        self.lang = lang
        self.body.setObjectName("settingsDialog")  # alt düğmeler ayarlardakiyle aynı stili alır

        from ..models.database import get_database
        self._db = get_database()

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("settingsLineEdit")
        self.search_edit.setFixedHeight(34)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(t("history_search_placeholder", lang))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._reload)
        self.search_edit.textChanged.connect(lambda _text: self._search_timer.start())
        self.count_label = QLabel("")
        self.count_label.setObjectName("deviceInfo")
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.count_label)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("historyTable")
        self.table.setMinimumSize(760, 380)
        self.table.setHorizontalHeaderLabels([
            "", t("history_col_file", lang), t("history_col_device", lang),
            t("history_col_size", lang), t("history_col_date", lang),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setIconSize(QSize(16, 16))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # uzun dosya adlarında uzantı görünür kalsın
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(COL_ICON, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_ICON, 36)
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_DEVICE, 150), (COL_SIZE, 110), (COL_DATE, 130)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(col, width)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_DATE, Qt.SortOrder.DescendingOrder)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._open_row(row))
        layout.addWidget(self.table, 1)

        # Boş durum: başlık + ne yapılacağı (cihaz/transfer listeleriyle aynı biçim); aramada eşleşme yoksa da
        self.empty_box = QWidget()
        self.empty_box.setMinimumSize(760, 380)
        empty_lay = QVBoxLayout(self.empty_box)
        empty_lay.setContentsMargins(24, 24, 24, 24)
        empty_lay.setSpacing(6)
        empty_lay.addStretch(1)
        self.empty_title = QLabel("")
        self.empty_title.setObjectName("deviceName")  # cihaz listesinin boş durumuyla aynı başlık/ipucu biçimi
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setWordWrap(True)
        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("deviceInfo")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty_lay.addWidget(self.empty_title)
        empty_lay.addWidget(self.empty_hint)
        empty_lay.addStretch(1)
        layout.addWidget(self.empty_box, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(trash_icon("#ef4444"))
        self.clear_btn.setIconSize(QSize(18, 18))
        self.clear_btn.setObjectName("settingsFooterBtn")
        self.clear_btn.setFixedSize(34, 34)
        self.clear_btn.setToolTip(t("clear_history", lang))
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._do_clear)

        self.close_btn = QPushButton(t("close", lang))
        self.close_btn.setObjectName("settingsFooterBtn")
        self.close_btn.setFixedHeight(34)
        self.close_btn.clicked.connect(self.close)

        footer.addWidget(self.clear_btn)
        footer.addStretch()
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)

        self._reload()

    # -- veri ------------------------------------------------------------------------------------------------
    def _reload(self) -> None:
        query = self.search_edit.text().strip()
        if query:
            rows = self._db.search_transfers(query, limit=_LIMIT)
        else:
            rows = self._db.get_transfer_history(limit=_LIMIT)
        self._show_history(rows, query)

    def _show_history(self, history, query: str = "") -> None:
        lang = self.lang
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)  # doldururken satırlar yer değiştirmesin
        self.table.setRowCount(0)
        for item in history:
            self._add_row(item)
        self.table.setSortingEnabled(sorting)

        has_items = bool(history)
        any_history = has_items or bool(query)
        self.table.setVisible(has_items)
        self.empty_box.setVisible(not has_items)
        if query:
            self.empty_title.setText(t("history_no_match_title", lang))
            self.empty_hint.setText(t("history_no_match_hint", lang))
        else:
            self.empty_title.setText(t("history_empty_title", lang))
            self.empty_hint.setText(t("history_empty_hint", lang))
        self.search_edit.setEnabled(any_history)
        self.clear_btn.setEnabled(any_history)
        self.count_label.setText(t("history_count", lang).format(count=len(history)) if has_items else "")

    def _add_row(self, item: dict) -> None:
        lang = self.lang
        tones = _TONES[is_dark()]
        status = str(item.get("status") or "")
        is_send = item.get("direction") in ("send", "outgoing")
        status_text = t(f"transfer_status_{status}", lang) if status else t("transfer_status_unknown", lang)
        tone = _STATUS_TONE.get(status, "warn")
        dir_text = t("history_outgoing" if is_send else "history_incoming", lang)

        row = self.table.rowCount()
        self.table.insertRow(row)

        icon_cell = _SortItem()
        icon_cell.setIcon(glyph_icon("arrow_up" if is_send else "arrow_down", tones[tone], 16))
        icon_cell.setData(_SORT_ROLE, f"{int(is_send)}{status}")
        icon_cell.setToolTip(f"{dir_text} · {status_text}")
        self.table.setItem(row, COL_ICON, icon_cell)

        path = str(item.get("filepath") or "")
        file_cell = _SortItem(str(item.get("filename") or ""))
        file_cell.setData(_SORT_ROLE, file_cell.text().lower())
        file_cell.setData(_PATH_ROLE, path)
        file_cell.setToolTip(path or file_cell.text())
        self.table.setItem(row, COL_FILE, file_cell)

        device_cell = _SortItem(str(item.get("device_name") or ""))
        device_cell.setData(_SORT_ROLE, device_cell.text().lower())
        device_cell.setToolTip(str(item.get("device_ip") or ""))
        self.table.setItem(row, COL_DEVICE, device_cell)

        size = int(item.get("filesize") or 0)
        if status == "completed":
            size_cell = _SortItem(format_bytes(size))
        else:
            # Başarısız/iptal satırı "0 B" yerine durumunu söyler; boyut ve hata ipucunda
            size_cell = _SortItem(status_text)
            size_cell.setForeground(QColor(tones[tone]))
            detail = format_bytes(size)
            error = str(item.get("error_message") or "")
            if error:
                detail = f"{detail} · {localize_error(error, lang)}"
            size_cell.setToolTip(detail)
        size_cell.setData(_SORT_ROLE, size)
        self.table.setItem(row, COL_SIZE, size_cell)

        stamp = item.get("start_time") or ""
        date_cell = _SortItem(_format_time(stamp, lang) or "—")  # henüz başlamamış (bekleyen) kayıt
        date_cell.setData(_SORT_ROLE, str(stamp))
        self.table.setItem(row, COL_DATE, date_cell)

    # -- eylemler --------------------------------------------------------------------------------------------
    def _row_path(self, row: int) -> str:
        cell = self.table.item(row, COL_FILE)
        return str(cell.data(_PATH_ROLE) or "") if cell is not None else ""

    def _existing_path(self, row: int) -> str:
        path = self._row_path(row)
        return path if path and os.path.isfile(path) else ""

    def _open_row(self, row: int) -> None:
        path = self._existing_path(row)
        if path:
            open_path(path)

    def _reveal_row(self, row: int) -> None:
        path = self._existing_path(row)
        if path:
            reveal_path(path)

    def context_actions(self, row: int) -> list[QAction]:
        """Sağ tık menüsü: dosya yerinde değilse eylemler devre dışı (nedeni ipucunda)."""
        exists = bool(self._existing_path(row))
        open_act = QAction(t("open_file", self.lang), self)
        open_act.triggered.connect(lambda: self._open_row(row))
        reveal_act = QAction(t("show_in_folder", self.lang), self)
        reveal_act.triggered.connect(lambda: self._reveal_row(row))
        for act in (open_act, reveal_act):
            act.setEnabled(exists)
            if not exists:
                act.setToolTip(t("history_file_missing", self.lang))
        return [open_act, reveal_act]

    def _show_context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for act in self.context_actions(row):
            menu.addAction(act)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _do_clear(self) -> None:
        if not ask_confirm(
            self,
            t("clear_history", self.lang),
            t("clear_history_confirm", self.lang),
            t("yes", self.lang),
            t("no", self.lang),
        ):
            return
        self._db.clear_history()
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._show_history([])  # sonuç satır içi görünür (boş durum): ayrıca bilgi kutusu açılmaz

    def prepare_content(self) -> None:
        self.fit_content(extra_w=8, extra_h=8)


def show_history_dialog(parent=None, lang: str = None) -> None:
    """Transfer geçmişini gösteren pencereyi açar."""
    HistoryDialog(parent, lang).exec()

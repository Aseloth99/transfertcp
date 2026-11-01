"""Transfer item widget"""

from PyQt6.QtWidgets import (QApplication, QWidget, QListWidget, QListWidgetItem, QLabel, 
                            QHBoxLayout, QVBoxLayout, QPushButton, QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QFont, QCursor, QPainter, QColor

from ..models.transfer import Transfer, TransferStatus, TransferDirection
from ..utils.error_text import localize_error
from ..utils.helpers import format_bytes, format_duration, format_speed, format_time
from ..utils.locales import configured_language, get_active_language, t
from ..utils.transfer_labels import wait_labels
from .widgets.elided_label import ElidedLabel
from .widgets.glyph_icons import glyph_color, glyph_icon
from .widgets.tone import set_tone


class TransferItemWidget(QWidget):
    """Custom widget for transfer list item"""
    
    pause_clicked = pyqtSignal(str)  # transfer_id
    resume_clicked = pyqtSignal(str)
    cancel_clicked = pyqtSignal(str)
    
    def __init__(self, transfer: Transfer, parent=None):
        super().__init__(parent)
        self.transfer = transfer
        self.lang = configured_language()
        self.setObjectName("TransferItemWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        # Update timer - faster updates for smoother progress
        # Create timer BEFORE calling _update_ui() to avoid AttributeError
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_ui)
        
        self._setup_ui()
        self._update_ui()
        
        # Start timer after UI is set up
        self.update_timer.start(100)  # Update every 100ms for smoother progress
        
        # Connect to transfer status changes to update count
        # Note: Transfer object doesn't have signals, so we'll update count in _update_ui
    
    def _setup_ui(self):
        """Kart düzeni: solda durum rozeti, sağda üç satır (ad + düğmeler / ilerleme çubuğu / bilgi + hız)."""
        relative_path = getattr(self.transfer, "relative_path", None)
        is_folder_transfer = relative_path is not None
        self.is_folder_transfer = is_folder_transfer

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(12)

        # Rozet: yön oku (↑ gönderim, ↓ alma); transfer bitince ✓, hata olunca ! olur (bkz. _update_badge)
        self.direction_label = QLabel()
        self.direction_label.setObjectName("transferBadge")
        self.direction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.direction_label.setFixedSize(38, 38)
        root.addWidget(self.direction_label, 0, Qt.AlignmentFlag.AlignVCenter)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(5)

        # Üst satır: ad (klasör aktarımında "klasör / dosya") ve düğmeler
        if is_folder_transfer:
            folder_name = relative_path.split("/")[0] if "/" in relative_path else t("folder_default", self.lang)
            display_text = f"{folder_name} / {self.transfer.filename}"
        else:
            display_text = self.transfer.filename
        self.filename_label = ElidedLabel(display_text)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.filename_label.setFont(font)

        self.pause_btn = QPushButton()
        self.pause_btn.setObjectName("transferActionBtn")
        self.pause_btn.setFixedSize(28, 28)
        self.pause_btn.setIconSize(QSize(14, 14))
        self.pause_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.pause_btn.clicked.connect(lambda: self._on_pause_clicked())
        self.pause_btn.setToolTip(t("pause_local_tooltip", self.lang))

        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("transferCancelBtn")
        self.cancel_btn.setFixedSize(28, 28)
        self.cancel_btn.setIconSize(QSize(14, 14))
        self.cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cancel_btn.clicked.connect(lambda: self._on_cancel_clicked())
        self.cancel_btn.setToolTip(t("cancel_tooltip", self.lang))
        self._set_icon(self.pause_btn, "pause")
        self._set_icon(self.cancel_btn, "close")

        top_layout = QHBoxLayout()
        top_layout.setSpacing(6)
        top_layout.addWidget(self.filename_label, 1)
        top_layout.addWidget(self.pause_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Orta satır: ince ilerleme çubuğu ve yüzde
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("transferBar")
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setProperty("state", "running")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("transferPercent")
        self.percent_label.setFixedWidth(44)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar_layout = QHBoxLayout()
        bar_layout.setSpacing(10)
        bar_layout.addWidget(self.progress_bar, 1, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.addWidget(self.percent_label)

        # Alt satır: bilgi (sol) ve hız / kalan süre (sağ)
        self.info_label = QLabel()
        info_font = QFont()
        info_font.setPointSize(8)
        self.info_label.setFont(info_font)
        set_tone(self.info_label, "body")
        self.speed_label = QLabel()
        self.speed_label.setFont(info_font)
        set_tone(self.speed_label, "muted")
        info_layout = QHBoxLayout()
        info_layout.setSpacing(8)
        info_layout.addWidget(self.info_label)
        info_layout.addStretch()
        info_layout.addWidget(self.speed_label)

        column.addLayout(top_layout)
        column.addLayout(bar_layout)
        column.addLayout(info_layout)
        root.addLayout(column, 1)

        self.setFixedHeight(86)
        self._update_badge()
        if is_folder_transfer:
            self.setProperty("isFolderTransfer", True)

    def _dark(self) -> bool:
        """Tema koyu mu (MainWindow.apply_theme uygulama özelliğine yazar)?"""
        app = QApplication.instance()
        value = app.property("tt_dark") if app is not None else None
        return True if value is None else bool(value)

    def _set_icon(self, button: QPushButton, kind: str, tone: str = "normal") -> None:
        button.setIcon(glyph_icon(kind, glyph_color(self._dark(), tone), 16))

    def _update_badge(self) -> None:
        """Rozet: çalışırken yön oku; bitince ✓, hata ! ve iptalde ✕ (renk tonu QSS'te `badge` özelliğinden)."""
        status = self.transfer.status
        send = self.transfer.direction == TransferDirection.SEND
        if status == TransferStatus.COMPLETED:
            glyph, tone = "✓", "ok"
        elif status == TransferStatus.FAILED:
            glyph, tone = "!", "err"
        elif status == TransferStatus.CANCELLED:
            glyph, tone = "✕", "muted"
        elif status == TransferStatus.PAUSED:
            glyph, tone = "II", "warn"
        else:
            glyph, tone = ("↑" if send else "↓"), ("info" if send else "ok")
        if self.direction_label.text() != glyph:
            self.direction_label.setText(glyph)
        if self.direction_label.property("badge") != tone:
            self.direction_label.setProperty("badge", tone)
            style = self.direction_label.style()
            style.unpolish(self.direction_label)
            style.polish(self.direction_label)

    def _set_bar_state(self, state: str) -> None:
        if self.progress_bar.property("state") != state:
            self.progress_bar.setProperty("state", state)
            style = self.progress_bar.style()
            style.unpolish(self.progress_bar)
            style.polish(self.progress_bar)

    def _update_ui(self):
        """Update UI based on transfer state"""
        transfer = self.transfer
        
        # Update progress bar
        if transfer.status == TransferStatus.COMPLETED or transfer.is_complete:
            progress = 100
        else:
            progress = int(transfer.progress)
        self.progress_bar.setValue(progress)
        self.progress_bar.setFormat(f"{progress}%")
        self.percent_label.setText(f"{progress}%")
        
        # Update status
        status_text = self._get_status_text()
        
        # Update info label
        size_text = f"{format_bytes(transfer.bytes_transferred)} / {format_bytes(transfer.filesize)}"
        device_text = f"{transfer.device_name}"
        
        # Track previous status to detect changes
        previous_status = getattr(self, '_previous_status', None)
        status_changed = previous_status != transfer.status
        self._previous_status = transfer.status
        
        lang = self.lang
        if transfer.status == TransferStatus.COMPLETED:
            self.info_label.setText(t("transfer_info_completed", lang).format(device=device_text))
            set_tone(self.info_label, "ok")
            elapsed = transfer.elapsed_time
            size_str = format_bytes(transfer.filesize)
            if elapsed > 0:
                self.speed_label.setText(f"{size_str} · {format_duration(elapsed, lang)}")
            else:
                self.speed_label.setText(size_str)
            set_tone(self.speed_label, "muted")
            self.update_timer.stop()
            # Update count when transfer completes
            if status_changed:
                self._notify_count_update()
        elif transfer.status == TransferStatus.FAILED:
            self.info_label.setText(t("transfer_info_failed", lang).format(error=localize_error(transfer.error_message or t("unknown_error", lang), lang)))
            set_tone(self.info_label, "err")
            self.speed_label.setText(format_bytes(transfer.filesize))
            set_tone(self.speed_label, "muted")
            self.update_timer.stop()
            # Update count when transfer fails
            if status_changed:
                self._notify_count_update()
        elif transfer.status == TransferStatus.CANCELLED:
            self.info_label.setText(t("transfer_info_cancelled", lang).format(device=device_text))
            set_tone(self.info_label, "warn")
            self.speed_label.setText(format_bytes(transfer.filesize))
            set_tone(self.speed_label, "muted")
            self.update_timer.stop()
            # Update count when transfer is cancelled
            if status_changed:
                self._notify_count_update()
        else:
            # Bekleme türü: sırada / yeniden deneniyor / onay bekliyor / bekliyor
            wait = wait_labels(transfer, lang)
            if wait is not None and wait[0] is not None:
                self.info_label.setText(wait[0])
                set_tone(self.info_label, "warn")
                self.speed_label.setText("")
            else:
                self.info_label.setText(f"{size_text} - {device_text}")
                set_tone(self.info_label, "body")

            # Update speed and ETA
            if transfer.status == TransferStatus.TRANSFERRING and transfer.speed > 0:
                speed_text = format_speed(transfer.speed)
                eta = transfer.estimated_time_remaining
                if eta:
                    eta_text = format_time(eta, lang)
                    self.speed_label.setText(f"{speed_text} · {eta_text} {t('eta_left', lang)}")
                else:
                    self.speed_label.setText(speed_text)
            elif transfer.status == TransferStatus.PAUSED:
                self.speed_label.setText(t("transfer_status_paused", lang))
            elif wait is not None:
                self.speed_label.setText(wait[1])
            else:
                self.speed_label.setText("")

        
        # Düğmeler: duraklat/devam simgesi duruma göre; bitmiş transferde ikisi de gizli
        if transfer.status == TransferStatus.TRANSFERRING:
            self._set_icon(self.pause_btn, "pause")
            self.pause_btn.setToolTip(t("pause_tooltip", lang))
            self.pause_btn.setVisible(True)
            self.pause_btn.setEnabled(True)
            self.cancel_btn.setVisible(True)
            self.cancel_btn.setEnabled(True)
        elif transfer.status == TransferStatus.PAUSED:
            self._set_icon(self.pause_btn, "play")
            self.pause_btn.setToolTip(t("resume_tooltip", lang))
            self.pause_btn.setVisible(True)
            self.pause_btn.setEnabled(True)
            self.cancel_btn.setVisible(True)
            self.cancel_btn.setEnabled(True)
        elif transfer.is_complete or transfer.is_failed or transfer.status == TransferStatus.CANCELLED:
            self.pause_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        else:
            # PENDING, CONNECTING, etc. - show cancel button, hide pause button
            self.pause_btn.setVisible(False)
            self.cancel_btn.setVisible(True)
            self.cancel_btn.setEnabled(True)
        self._set_icon(self.cancel_btn, "close")

        # Çubuk ve rozet rengi temadan gelir (QProgressBar#transferBar[state=...]); vurgu rengini de izler
        if transfer.status == TransferStatus.COMPLETED:
            self._set_bar_state("completed")
        elif transfer.status == TransferStatus.FAILED:
            self._set_bar_state("failed")
        elif transfer.status == TransferStatus.PAUSED:
            self._set_bar_state("paused")
        else:
            self._set_bar_state("running")
        self._update_badge()

    def _get_status_text(self) -> str:
        """Get status text"""
        lang = self.lang
        status_map = {
            TransferStatus.PENDING: t("transfer_status_pending", lang),
            TransferStatus.CONNECTING: t("transfer_status_connecting", lang),
            TransferStatus.TRANSFERRING: t("transfer_status_transferring", lang),
            TransferStatus.PAUSED: t("transfer_status_paused", lang),
            TransferStatus.COMPLETED: t("transfer_status_completed", lang),
            TransferStatus.FAILED: t("transfer_status_failed", lang),
            TransferStatus.CANCELLED: t("transfer_status_cancelled", lang),
        }
        return status_map.get(self.transfer.status, t("transfer_status_unknown", lang))

    def retranslate(self, lang: str | None = None):
        if lang is not None:
            self.lang = lang
        self.pause_btn.setToolTip(t("pause_local_tooltip", self.lang))
        self.cancel_btn.setToolTip(t("cancel_tooltip", self.lang))
        self._update_ui()
    
    def _on_pause_clicked(self):
        """Handle pause/resume button click"""
        if self.transfer.status == TransferStatus.PAUSED:
            self.resume_clicked.emit(self.transfer.transfer_id)
        else:
            self.pause_clicked.emit(self.transfer.transfer_id)
    
    def _notify_count_update(self):
        """Notify parent to update transfer count"""
        parent = self.parent()
        while parent:
            if isinstance(parent, TransferListWidget):
                parent._update_count()
                break
            parent = parent.parent()
    
    def _on_cancel_clicked(self):
        """Handle cancel button click"""
        self.cancel_clicked.emit(self.transfer.transfer_id)


class _EmptyHintList(QListWidget):
    """Liste bosken ortada kisa bir aciklama cizer; ilk transfer eklenince kendiliginden kaybolur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._hint = ""

    def set_hint(self, title: str, hint: str) -> None:
        self._title, self._hint = title, hint
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() > 0 or not self._title:
            return
        app = QApplication.instance()
        dark = True if app is None or app.property("tt_dark") is None else bool(app.property("tt_dark"))
        painter = QPainter(self.viewport())
        rect = self.viewport().rect()
        painter.setPen(QColor("#9a9a9a" if dark else "#6b7280"))
        title_font = QFont(self.font())
        title_font.setPointSizeF(self.font().pointSizeF() + 2 if self.font().pointSizeF() > 0 else 12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            rect.adjusted(24, rect.height() // 2 - 40, -24, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self._title,
        )
        painter.setFont(self.font())
        painter.drawText(
            rect.adjusted(48, rect.height() // 2 - 8, -48, 0),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
            self._hint,
        )
        painter.end()


class TransferListWidget(QWidget):
    """Transfer list widget"""
    
    pause_transfer = pyqtSignal(str)
    resume_transfer = pyqtSignal(str)
    cancel_transfer = pyqtSignal(str)
    cancel_all_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.transfers = {}  # key: transfer_id, value: (item, widget)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 4)
        header_layout.setSpacing(8)
        
        self.lang = configured_language()
        self._sent_text = format_bytes(0)
        self._received_text = format_bytes(0)
        self.title_label = QLabel(t("transfers", self.lang))
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.title_label.setFont(font)
        
        self.clear_btn = QPushButton(t("clear_list", self.lang))
        self.clear_btn.setObjectName("clearListBtn")
        self.clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        self.clear_btn.hide()

        self.cancel_all_btn = QPushButton(t("cancel_all_transfers", self.lang))
        self.cancel_all_btn.setObjectName("cancelAllBtn")
        self.cancel_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cancel_all_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancel_all_btn.clicked.connect(self._on_cancel_all_clicked)
        self.cancel_all_btn.hide()
        
        self.stats_label = QLabel(
            t("stats_sent_received", self.lang).format(sent=self._sent_text, received=self._received_text)
        )
        self.stats_label.setObjectName("transferStats")
        stats_font = QFont()
        stats_font.setPointSize(9)
        stats_font.setWeight(QFont.Weight.DemiBold)
        self.stats_label.setFont(stats_font)
        
        self.count_label = QLabel(t("active_count", self.lang).format(count=0))
        set_tone(self.count_label, "muted")
        
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.clear_btn)
        header_layout.addWidget(self.cancel_all_btn)
        header_layout.addStretch()
        header_layout.addWidget(self.stats_label)
        header_layout.addWidget(self.count_label)
        
        # Transfer list
        self.list_widget = _EmptyHintList()
        self.list_widget.set_hint(t("transfers_empty_title", self.lang), t("transfers_empty_hint", self.lang))
        self.list_widget.setObjectName("transfer_list_view")
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(6)
        
        layout.addWidget(header)
        layout.addWidget(self.list_widget)
    
    def add_transfer(self, transfer: Transfer):
        """Add transfer to list"""
        transfer_id = transfer.transfer_id
        
        # Check if already exists (e.g. sender retrying)
        if transfer_id in self.transfers:
            item, widget = self.transfers[transfer_id]
            widget.transfer = transfer
            widget._previous_status = None
            if hasattr(widget, 'update_timer') and not widget.update_timer.isActive():
                widget.update_timer.start(100)
            widget._update_ui()
            self._update_count()
            return
        
        viewport = self.list_widget.viewport() if hasattr(self.list_widget, 'viewport') else self.list_widget
        widget = TransferItemWidget(transfer, parent=viewport)
        widget.pause_clicked.connect(self.pause_transfer.emit)
        widget.resume_clicked.connect(self.resume_transfer.emit)
        widget.cancel_clicked.connect(self.cancel_transfer.emit)
        
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 86))
        self.list_widget.insertItem(0, item)
        self.list_widget.setItemWidget(item, widget)
        
        # Store reference
        self.transfers[transfer_id] = (item, widget)
        
        # Update count
        self._update_count()
    
    def update_transfer(self, transfer: Transfer):
        """Force immediate UI update for a transfer without waiting for timer"""
        if transfer.transfer_id in self.transfers:
            _, widget = self.transfers[transfer.transfer_id]
            widget.transfer = transfer
            widget._update_ui()
            self._update_count()
    
    def remove_transfer(self, transfer_id: str):
        """Remove transfer from list"""
        if transfer_id in self.transfers:
            item, widget = self.transfers[transfer_id]
            
            # Stop update timer
            if hasattr(widget, 'update_timer'):
                widget.update_timer.stop()
            
            # Remove from list
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)
            
            # Remove from dict
            del self.transfers[transfer_id]
            
            # Update count
            self._update_count()
    
    def clear_completed(self):
        """Clear completed transfers"""
        to_remove = []
        for transfer_id, (_, widget) in self.transfers.items():
            if widget.transfer.is_complete:
                to_remove.append(transfer_id)
        
        for transfer_id in to_remove:
            self.remove_transfer(transfer_id)
    
    def _on_cancel_all_clicked(self):
        """Cancel all active transfers"""
        for transfer_id, (_, widget) in list(self.transfers.items()):
            if widget.transfer.is_active:
                self.cancel_transfer.emit(transfer_id)
        self.cancel_all_requested.emit()
        self._update_count()

    def _update_count(self):
        """Update transfer count label and button visibilities"""
        active_count = sum(1 for _, widget in self.transfers.values() 
                          if widget.transfer.is_active)
        self.count_label.setText(t("active_count", self.lang).format(count=active_count))
        
        # Show 'Listeyi Temizle' only when there is at least one transfer
        if len(self.transfers) > 0:
            self.clear_btn.show()
        else:
            self.clear_btn.hide()

        # Show 'Gönderimleri İptal Et' only when there are more than 3 active transfers (> 3)
        # Hide when active count drops below 4 (<= 3)
        if active_count > 3:
            self.cancel_all_btn.show()
        else:
            self.cancel_all_btn.hide()

    def retranslate(self, lang: str | None = None):
        if lang is not None:
            self.lang = lang
        self.title_label.setText(t("transfers", self.lang))
        self.list_widget.set_hint(t("transfers_empty_title", self.lang), t("transfers_empty_hint", self.lang))
        self.clear_btn.setText(t("clear_list", self.lang))
        self.cancel_all_btn.setText(t("cancel_all_transfers", self.lang))
        self.stats_label.setText(
            t("stats_sent_received", self.lang).format(sent=self._sent_text, received=self._received_text)
        )
        self._update_count()
        for _, widget in self.transfers.values():
            widget.retranslate(self.lang)

    def set_statistics(self, sent: str, received: str):
        if hasattr(self, "stats_label"):
            self._sent_text = sent
            self._received_text = received
            self.stats_label.setText(
                t("stats_sent_received", self.lang).format(sent=sent, received=received)
            )


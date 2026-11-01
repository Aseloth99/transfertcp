"""Güncelleme penceresi: sürüm, boyut, sürüm notları; "Şimdi Güncelle" ile sessiz indirme + kurulum.

Durumlar: boşta -> indiriliyor -> kuruluyor; hata olursa pencere AÇIK kalır (satır içi hata + "Tekrar dene"), hiçbir
durumda QMessageBox açılmaz. İndirme sürerken Esc/X = indirmeyi iptal et ve kapat (indirme arka planda sürüp pencere
kapanınca uygulamayı habersiz yeniden başlatmasın). Pencere yalnızca görünümdür: indirmeyi/kurulumu `Application` yürütür.
"""

from typing import Optional

from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QWidget,
                            QPushButton, QProgressBar, QTextEdit)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from ..utils.helpers import format_bytes
from .widgets.tone import set_tone
from .chrome_dialog import ChromeDialog
from ..utils.locales import configured_language, get_active_language, t

_ZWSP = "\u200b"


def _set_notes(box, notes: str, default: str) -> None:
    """Sürüm notları HTML ise HTML olarak, düz metinse satır sonları korunarak gösterilir (setHtml satırları birleştirirdi)."""
    from PyQt6.QtCore import Qt as _Qt
    text = notes or ""
    if not text.strip():
        box.setHtml(default)
    elif _Qt.mightBeRichText(text):
        box.setHtml(text)
    else:
        box.setPlainText(text)


def _wrappable(text: str) -> str:
    """Boşluksuz uzun yollar (C:\\...\\TransferTCP.exe) QLabel'da satır kıramaz ve yana taşıp kesilirdi:
    ters/düz eğik çizgiden sonra görünmez bir kırılma noktası konur."""
    return text.replace("\\", "\\" + _ZWSP).replace("/", "/" + _ZWSP)


class UpdateDialog(ChromeDialog):
    """Dialog for showing update information and progress"""

    # Signals
    update_accepted = pyqtSignal()  # "Şimdi Güncelle" / "Tekrar dene"
    update_deferred = pyqtSignal()  # "Daha Sonra" (ya da kapatıldı)
    update_cancelled = pyqtSignal()  # indirme sürerken iptal (düğme, Esc ya da X)

    IDLE, DOWNLOADING, INSTALLING, ERROR = "idle", "downloading", "installing", "error"

    def __init__(self, version: str, release_notes: str, is_mandatory: bool = False, parent=None,
                 lang: str | None = None, file_size: Optional[int] = None):
        if lang is None and parent is not None and hasattr(parent, 'lang'):
            lang = parent.lang
        elif lang is None and parent is not None:
            from ..utils.config import get_config
            lang = get_active_language(get_config())
        lang = lang or configured_language()
        super().__init__(parent, t("update_available_title", lang))  # özel üst çubuklu pencere
        self.version = version
        self.release_notes = release_notes
        self.is_mandatory = is_mandatory
        self.file_size = file_size if isinstance(file_size, (int, float)) and not isinstance(file_size, bool) and file_size > 0 else None
        self.state = self.IDLE
        self.is_downloading = False
        self.is_installing = False
        self._retry_allowed = True
        self.lang = lang

        self.setModal(True)

        self._setup_ui()
        self._apply_state()

    def _setup_ui(self):
        """Setup UI components"""
        layout = QVBoxLayout(self.body)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 14, 20, 20)

        # Title
        title_label = QLabel(t("update_version_heading", self.lang).format(version=self.version))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # Current version info
        from ..utils.updater import UpdateChecker
        current_version = UpdateChecker.CURRENT_VERSION
        version_label = QLabel(
            t("update_version_line", self.lang).format(current=current_version, new=self.version)
        )
        version_label.setWordWrap(True)
        set_tone(version_label, "muted")
        layout.addWidget(version_label)

        # İndirme boyutu (sunucu fileSize verdiyse)
        self.size_label = QLabel()
        self.size_label.setWordWrap(True)
        set_tone(self.size_label, "muted")
        if self.file_size:
            self.size_label.setText(t("update_size_line", self.lang).format(size=format_bytes(self.file_size)))
        self.size_label.setVisible(bool(self.file_size))
        layout.addWidget(self.size_label)

        # Release notes
        notes_label = QLabel(t("update_notes", self.lang))
        notes_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(notes_label)

        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setMinimumHeight(110)
        default_notes = f"<p>{t('update_available_plain', self.lang)}</p>"
        _set_notes(self.notes_text, self.release_notes, default_notes)
        layout.addWidget(self.notes_text, 1)

        # Progress bar (initially hidden)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(18)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Progress label (initially hidden)
        self.progress_label = QLabel()
        self.progress_label.setVisible(False)
        self.progress_label.setWordWrap(True)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_tone(self.progress_label, "info")
        layout.addWidget(self.progress_label)

        # Status label (for installation)
        self.status_label = QLabel()
        self.status_label.setVisible(False)
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_tone(self.status_label, "ok")
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_label)

        # Bilgi satırı (ör. aktarım sürüyor): hata değil, normal duruma dönülür
        self.notice_label = QLabel()
        self.notice_label.setVisible(False)
        self.notice_label.setWordWrap(True)
        set_tone(self.notice_label, "warn")
        layout.addWidget(self.notice_label)

        # Satır içi hata (QMessageBox yerine)
        self.error_label = QLabel()
        self.error_label.setObjectName("updateError")
        self.error_label.setVisible(False)
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_tone(self.error_label, "err")
        layout.addWidget(self.error_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.addStretch()

        # İndirme sırasında tek düğme: İptal
        self.cancel_btn = QPushButton(t("cancel", self.lang))
        self.cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_btn)

        # Later button (only for non-mandatory updates)
        self.later_btn = QPushButton(t("update_later", self.lang))
        self.later_btn.clicked.connect(self._on_later)
        button_layout.addWidget(self.later_btn)

        # Update button ("Tekrar dene" olarak da kullanılır)
        self.update_btn = QPushButton(t("update_now", self.lang))
        self.update_btn.setProperty("class", "primary")
        self.update_btn.clicked.connect(self._on_update)
        self.update_btn.setDefault(True)
        button_layout.addWidget(self.update_btn)

        layout.addLayout(button_layout)

    # ------------------------------------------------------------------ durum
    def _apply_state(self) -> None:
        """Düğme/etiket görünürlüğü tek yerden: durum -> arayüz."""
        s = self.state
        self.is_downloading = s == self.DOWNLOADING
        self.is_installing = s == self.INSTALLING
        idle_like = s in (self.IDLE, self.ERROR)
        close_only = s == self.ERROR and not self._retry_allowed  # yeniden denemenin anlamı yok: yalnızca "Kapat"
        self.update_btn.setVisible(idle_like and not close_only)
        self.update_btn.setEnabled(idle_like)
        self.update_btn.setText(t("update_retry" if s == self.ERROR else "update_now", self.lang))
        self.later_btn.setVisible(idle_like and (close_only or not self.is_mandatory))
        self.later_btn.setText(t("close" if close_only else "update_later", self.lang))
        self.cancel_btn.setVisible(s == self.DOWNLOADING)
        self.progress_bar.setVisible(s in (self.DOWNLOADING, self.INSTALLING))
        self.progress_label.setVisible(s == self.DOWNLOADING)
        self.status_label.setVisible(s == self.INSTALLING)
        self.error_label.setVisible(s == self.ERROR and bool(self.error_label.text()))
        if s != self.IDLE:
            self.notice_label.setVisible(False)
        QTimer.singleShot(0, self._fit)

    def prepare_content(self) -> None:
        """En az 520 x 420 (çerçeve payı dahil); içerik daha büyükse ona göre. Pencere yeniden boyutlanabilir kalır."""
        self.ensurePolished()
        for widget in self.findChildren(QWidget):
            widget.ensurePolished()
        chrome = self.chrome_size()
        hint = self.layout().sizeHint()
        width = max(520 + chrome.width(), hint.width())
        height = max(420 + chrome.height(), hint.height())
        self.setMinimumSize(width, height)
        self.resize(width, height)

    def _fit(self) -> None:
        """Satır içi ileti belirince pencere içeriğe sığacak kadar büyüsün (metin kesilmesin)."""
        if not self.isVisible():
            return
        hint = self.sizeHint()
        if hint.height() > self.height() or hint.width() > self.width():
            self.resize(max(self.width(), hint.width()), max(self.height(), hint.height()))

    def _on_update(self):
        """Handle update button click (idle: "Şimdi Güncelle", error: "Tekrar dene")"""
        self.update_btn.setEnabled(False)  # çift tıklama ikinci indirme başlatmasın; uygulama durumu belirler
        self.error_label.setVisible(False)
        self.notice_label.setVisible(False)
        self.update_accepted.emit()

    def _on_later(self):
        """Handle later button click"""
        self.reject()

    def _on_cancel(self):
        """Handle cancel button click (yalnızca indirme sırasında görünür)"""
        self.reject()

    def reject(self):
        if self.is_installing:
            return  # kurulum birkaç saniye sürer ve yarıda kesilemez; uygulama yeniden başlayınca pencere kapanır
        if self.is_downloading:
            # Esc / X / İptal: indirmeyi durdur ve kapat (onay sorusu yok)
            self.state = self.IDLE
            self.is_downloading = False
            self.update_cancelled.emit()
            super().reject()
            return
        if not self.is_mandatory:
            self.update_deferred.emit()
        super().reject()

    def show_downloading_state(self):
        """İndirme başladı: ilerleme çubuğu + hız + İptal."""
        self.state = self.DOWNLOADING
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText(t("update_downloading", self.lang))
        self._apply_state()

    # eski ad (testler/çağıranlar)
    _show_downloading_state = show_downloading_state

    def update_download_progress(self, downloaded: int, total: int, speed_mbps: float):
        """
        Update download progress

        Args:
            downloaded: Bytes downloaded
            total: Total bytes to download
            speed_mbps: Download speed in MB/s
        """
        if self.state != self.DOWNLOADING:
            return
        downloaded_str = format_bytes(downloaded)
        speed_str = f"{speed_mbps:.2f} MB/s" if speed_mbps > 0 else ""

        if total > 0:
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)

            percent = min(int((downloaded / total) * 100), 100)
            self.progress_bar.setValue(percent)

            total_str = format_bytes(total)
            progress_text = f"{downloaded_str} / {total_str} ({percent}%)"
        else:
            self.progress_bar.setRange(0, 0)
            progress_text = t("update_downloaded_bytes", self.lang).format(bytes=downloaded_str)

        if speed_str:
            progress_text += f" - {speed_str}"

        self.progress_label.setText(progress_text)

    def show_download_complete(self):
        """İndirme bitti (kurulum hemen başlar)."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText(t("update_download_done", self.lang))

    def show_installing_state(self):
        """Kuruluyor…: düğme yok, belirsiz ilerleme çubuğu."""
        self.state = self.INSTALLING
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(t("update_installing", self.lang))
        self._apply_state()

    def show_install_complete(self):
        """Kurulum tamam: uygulama yeniden başlatılıyor."""
        self.status_label.setText(t("update_restarting", self.lang))

    def show_error(self, message: str, retry: bool = True):
        """Satır içi hata (QMessageBox yok): pencere açık kalır, "Tekrar dene" ile yeniden denenir.
        `retry=False` (ör. kaynaktan çalışma): yeniden denemenin anlamı yok, yalnızca kapatılır."""
        self.state = self.ERROR
        self._retry_allowed = bool(retry)
        text = t("update_failed_inline", self.lang).format(error=message)
        self.error_label.setText(_wrappable(text))
        self._apply_state()

    def show_notice(self, message: str):
        """Hata olmayan bilgi satırı (ör. aktarım sürüyor) ve normal duruma (boşta) dönüş."""
        self.state = self.IDLE
        self.notice_label.setText(_wrappable(message))
        self._apply_state()
        self.notice_label.setVisible(True)

"""Device list widget"""

from PyQt6.QtWidgets import (QWidget, QListWidget, QListWidgetItem, QLabel,
                            QHBoxLayout, QVBoxLayout, QPushButton, QMenu,
                            QSizePolicy, QFrame, QDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QCursor

from ..models.device import Device
from ..models.database import get_database
from ..utils.locales import configured_language, get_active_language, t
from ..utils.logger import get_logger
from datetime import datetime

from .widgets.elided_label import ElidedLabel
from .widgets.tone import set_tone


class DeviceItemWidget(QWidget):
    """Custom widget for device list item"""
    
    def __init__(self, device: Device, parent=None):
        super().__init__(parent)
        self.device = device
        self.setObjectName("DeviceItemWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(60)
        self._setup_ui()
        self._update_status()
        
    
    def _setup_ui(self):
        """Setup UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 11, 12, 11)  # yan çubuk kartın kenarına yapışmasın, yukarı/aşağıdan pay kalsın
        layout.setSpacing(10)

        self.accent_bar = QFrame()
        self.accent_bar.setObjectName("deviceAccent")
        self.accent_bar.setFixedWidth(4)
        layout.addWidget(self.accent_bar)
        
        # Status indicator
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(12, 12)
        self.status_indicator.setStyleSheet("""
            QLabel {
                border-radius: 6px;
                background-color: #4CAF50;
            }
        """)
        
        # Device info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setContentsMargins(0, 0, 0, 0)
        
        # Device name
        self.name_label = ElidedLabel(self.device.display_name)
        self.name_label.setObjectName("deviceName")
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        # Baglanti durumu (Cevrimici/Cevrimdisi): adin sagina, kisa; IP satiri tasmasin diye ayri tutulur
        self.state_label = QLabel(self._state_text())
        self.state_label.setObjectName("deviceState")
        state_font = QFont()
        state_font.setPointSize(8)
        state_font.setBold(True)
        self.state_label.setFont(state_font)
        self.state_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        set_tone(self.state_label, "ok" if self.device.is_online else "muted")

        # IP and hostname
        self.info_label = QLabel(self._info_text())
        self.info_label.setObjectName("deviceInfo")
        font = QFont()
        font.setPointSize(8)
        self.info_label.setFont(font)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.status_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(8)
        name_row.addWidget(self.name_label, 1)
        name_row.addWidget(self.state_label, 0)
        info_layout.addLayout(name_row)
        info_layout.addWidget(self.info_label)
        
        # Favorite star
        self.favorite_btn = QPushButton("★" if self.device.is_favorite else "☆")
        self.favorite_btn.setObjectName("favoriteBtn")
        self.favorite_btn.setFixedSize(24, 24)
        self.favorite_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        layout.addWidget(self.status_indicator)
        layout.addLayout(info_layout, 1)
        layout.addWidget(self.favorite_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            parent = self.parent()
            while parent is not None:
                if isinstance(parent, QListWidget):
                    for i in range(parent.count()):
                        item = parent.item(i)
                        if parent.itemWidget(item) is self:
                            parent.setCurrentItem(item)
                            parent.itemClicked.emit(item)
                            break
                    break
                parent = parent.parent()
        super().mousePressEvent(event)
    
    def _update_status(self):
        """Update status indicator"""
        if self.device.is_online:
            self.status_indicator.setStyleSheet("""
                QLabel {
                    border-radius: 6px;
                    background-color: #4CAF50;
                }
            """)
        else:
            self.status_indicator.setStyleSheet("""
                QLabel {
                    border-radius: 6px;
                    background-color: #9E9E9E;
                }
            """)
    
    def _info_text(self) -> str:
        return f"{self.device.ip}"

    def _state_text(self) -> str:
        """Baglanti durumu renk noktasina ek olarak yaziyla da soylenir (renk korlugu / ekran okuyucu)."""
        return t("device_online" if self.device.is_online else "device_offline", configured_language())

    def refresh_texts(self) -> None:
        self.info_label.setText(self._info_text())
        self.state_label.setText(self._state_text())
        set_tone(self.state_label, "ok" if self.device.is_online else "muted")

    def update_device(self, device: Device):
        """Update device information"""
        self.device = device
        self.name_label.set_full_text(device.display_name)
        self.refresh_texts()
        self.favorite_btn.setText("★" if device.is_favorite else "☆")
        self._update_status()


class DeviceListWidget(QWidget):
    """Device list widget with search and filtering"""
    
    device_selected = pyqtSignal(Device)
    device_double_clicked = pyqtSignal(Device)
    selection_changed = pyqtSignal()  # secili cihaz / cevrimici durumu / liste degisti (birakma alani hedefi icin)
    refresh_requested = pyqtSignal()  # New signal for refresh
    manual_device_requested = pyqtSignal(str, str, int)  # ip, görünen ad, port — yayınsız ağlar için
    device_remove_requested = pyqtSignal(object)  # Device — listeden kaldırma
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices = {}  # key: device_key, value: (item, widget)
        self.lang = configured_language()
        self._suppress_empty = False
        self._setup_ui()
        
    
    def _setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 12, 12, 12)
        
        self.title_label = QLabel(t("devices", self.lang))
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.title_label.setFont(font)
        
        self.device_count_label = QLabel("0")
        set_tone(self.device_count_label, "muted")
        
        # Refresh button
        self.refresh_btn = QPushButton(t("refresh", self.lang))
        self.refresh_btn.setFixedHeight(32)
        self.refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.refresh_btn.setToolTip(t("refresh_devices_tooltip", self.lang))
        self.refresh_btn.setProperty("class", "primary")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 16px;
                font-size: 9pt;
            }
        """)

        # IP ile cihaz ekleme (eduroam / farklı alt-ağ gibi yayınsız ağlar için)
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(32, 32)
        self.add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.add_btn.setToolTip(t("add_device_tooltip", self.lang))
        self.add_btn.setProperty("class", "primary")
        self.add_btn.setStyleSheet("""
            QPushButton {
                font-size: 14pt;
                font-weight: bold;
                padding: 0px;
            }
        """)
        self.add_btn.clicked.connect(self._show_manual_add_dialog)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.device_count_label)
        header_layout.addWidget(self.add_btn)
        header_layout.addWidget(self.refresh_btn)
        
        # Device list
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("device_list_view")
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(4)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        
        # Connect refresh button
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)

        layout.addWidget(header)
        layout.addWidget(self.list_widget)

        # Boş durum: liste boşken IP ile eklemeyi öner
        self.empty_box = QWidget()
        empty_layout = QVBoxLayout(self.empty_box)
        empty_layout.setContentsMargins(16, 20, 16, 20)
        empty_layout.setSpacing(6)
        # NOT: layout.setAlignment(...) kullanma — sarmalı açıklamanın heightForWidth'ini bozar, son satır kırpılır.
        # Dikey ortalama için esnek boşluklar kullanılır.
        self.empty_box.setObjectName("deviceEmptyBox")
        self.empty_title = QLabel(t("empty_devices_title", self.lang))
        self.empty_title.setObjectName("deviceName")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint = QLabel(t("empty_devices_hint", self.lang))
        self.empty_hint.setObjectName("deviceInfo")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_add_btn = QPushButton(t("add_device", self.lang))
        self.empty_add_btn.setProperty("class", "primary")
        self.empty_add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.empty_add_btn.clicked.connect(self._show_manual_add_dialog)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addWidget(self.empty_add_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)
        self.empty_box.setVisible(False)
        layout.addWidget(self.empty_box, 1)
        self._update_count()  # baslangicta da bos durum gorunsun (cihaz gelene kadar bos liste yerine aciklama)
    
    def add_device(self, device: Device):
        """Add device to list"""
        device_key = f"{device.ip}:{device.port}"
        
        # Check if already exists
        if device_key in self.devices:
            self.update_device(device)
            return
        
        # Create list item
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(0, 62))
        
        # Create custom widget
        widget = DeviceItemWidget(device, parent=self.list_widget)
        
        # Connect favorite button
        widget.favorite_btn.clicked.connect(lambda: self._toggle_favorite(device))
        
        # Add to list
        self.list_widget.setItemWidget(item, widget)
        
        # Store reference
        self.devices[device_key] = (item, widget)
        
        # Update count
        self._update_count()
        self.selection_changed.emit()

        # If there's only one device, automatically select it
        if len(self.devices) == 1:
            self.list_widget.setCurrentItem(item)
            self.device_selected.emit(device)
        
        # Update styles to ensure proper selection state
        self._update_all_widget_styles()
        
        # Force repaint
        self.list_widget.viewport().update()
        self.list_widget.repaint()
        self.repaint()
    
    def update_device(self, device: Device):
        """Update device in list"""
        device_key = f"{device.ip}:{device.port}"
        
        if device_key in self.devices:
            _, widget = self.devices[device_key]
            widget.update_device(device)
            self._update_count()
            self.list_widget.viewport().update()
            self.selection_changed.emit()
    
    def remove_device(self, device: Device):
        """Remove device from list"""
        device_key = f"{device.ip}:{device.port}"
        
        if device_key in self.devices:
            item, widget = self.devices[device_key]
            
            # Remove from list
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)
            
            # Remove from dict
            del self.devices[device_key]

            # Update count
            self._update_count()
            self.selection_changed.emit()
    
    def get_selected_device(self) -> Device:
        """Get currently selected device"""
        current_item = self.list_widget.currentItem()
        if current_item:
            widget = self.list_widget.itemWidget(current_item)
            if widget:
                return widget.device
        return None
    
    def clear_devices(self):
        """Clear all devices"""
        self.list_widget.clear()
        self.devices.clear()
        self._update_count()
        self.selection_changed.emit()

    def begin_refresh(self):
        """Yenileme sırasında boş durum panelini gizle (flicker önleme)."""
        self._suppress_empty = True
        if hasattr(self, "empty_box"):
            self.empty_box.setVisible(False)

    def end_refresh(self):
        """Yenileme bitti; boş durumu gerçek cihaz sayısına göre göster."""
        self._suppress_empty = False
        self._update_count()

    def retranslate(self, lang: str | None = None):
        if lang is not None:
            self.lang = lang
        self.title_label.setText(t("devices", self.lang))
        self.refresh_btn.setText(t("refresh", self.lang))
        self.refresh_btn.setToolTip(t("refresh_devices_tooltip", self.lang))
        self.add_btn.setToolTip(t("add_device_tooltip", self.lang))
        self.empty_title.setText(t("empty_devices_title", self.lang))
        self.empty_hint.setText(t("empty_devices_hint", self.lang))
        self.empty_add_btn.setText(t("add_device", self.lang))
        for _item, widget in self.devices.values():  # "Çevrimiçi/Çevrimdışı" yazısı da dile uysun
            widget.refresh_texts()

    def _show_manual_add_dialog(self):
        """IP ile cihaz ekleme penceresi (yayınsız ağlar için)."""
        from ..utils.config import get_config
        from ..utils.ports import DEFAULT_TRANSFER_PORT
        from .manual_device_dialog import ManualDeviceDialog

        try:
            default_port = get_config().get("transfer", "port", DEFAULT_TRANSFER_PORT)
        except Exception:
            default_port = DEFAULT_TRANSFER_PORT
        dlg = ManualDeviceDialog(self, self.lang, default_port)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ip_text, display_name, port = dlg.result_values()
        self.manual_device_requested.emit(ip_text, display_name, port)

    def _update_count(self):
        """Update device count label"""
        online_count = sum(1 for _, widget in self.devices.values()
                          if widget.device.is_online)
        total_count = len(self.devices)
        self.device_count_label.setText(f"{online_count}/{total_count}")
        if hasattr(self, "empty_box"):
            show_empty = total_count == 0 and not self._suppress_empty
            self.empty_box.setVisible(show_empty)
            self.list_widget.setVisible(not show_empty)  # bosken liste yerine aciklama alanin tamamini kaplar
    
    def _on_item_clicked(self, item):
        """Handle item click"""
        # Set as current item to trigger selection visual
        self.list_widget.setCurrentItem(item)
        
        widget = self.list_widget.itemWidget(item)
        if widget:
            # Update all widgets to clear previous selection
            self._update_all_widget_styles()
            self.device_selected.emit(widget.device)
    
    def _on_item_double_clicked(self, item):
        """Handle item double click"""
        widget = self.list_widget.itemWidget(item)
        if widget:
            self.device_double_clicked.emit(widget.device)
    
    def _on_selection_changed(self, current, previous):
        """Handle selection change - update widget styles"""
        self._update_all_widget_styles()
        self.selection_changed.emit()
    
    def _update_all_widget_styles(self):
        """Mark selected device cards so the theme QSS can style them."""
        current_item = self.list_widget.currentItem()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if not widget:
                continue
            is_selected = item == current_item
            widget.setProperty("selected", is_selected)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            if hasattr(widget, "accent_bar"):
                widget.accent_bar.setProperty("selected", is_selected)
                widget.accent_bar.style().unpolish(widget.accent_bar)
                widget.accent_bar.style().polish(widget.accent_bar)
            widget.update()
        self.list_widget.viewport().update()
    
    def _toggle_favorite(self, device: Device):
        """Toggle device favorite status"""
        device.is_favorite = not device.is_favorite
        self.update_device(device)
        
        # Save to database for persistence
        try:
            db = get_database()
            device_data = {
                'ip': device.ip,
                'port': device.port,
                'name': device.name,
                'hostname': device.hostname,
                'is_favorite': 1 if device.is_favorite else 0,
                'custom_name': device.custom_name,
                'last_seen': datetime.now().isoformat()
            }
            db.save_device(device_data)
        except Exception as e:
            get_logger().warning(f"Failed to save favorite status: {e}")
    
    def _copy_ip_to_clipboard(self, ip: str):
        """Copy IP address to clipboard"""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(ip)
    
    def _on_refresh_clicked(self):
        """Handle refresh button click"""
        self.begin_refresh()
        self.list_widget.clear()
        self.devices.clear()
        self._update_count()
        self.refresh_requested.emit()
    
    def _show_context_menu(self, position):
        """Show context menu"""
        item = self.list_widget.itemAt(position)
        if not item:
            return
        
        widget = self.list_widget.itemWidget(item)
        if not widget:
            return
        
        device = widget.device
        
        menu = QMenu(self)
        
        # Send file action
        send_action = menu.addAction(t("context_send_file", self.lang))
        send_action.triggered.connect(lambda: self.device_double_clicked.emit(device))
        
        menu.addSeparator()
        
        # Favorite action
        if device.is_favorite:
            fav_action = menu.addAction(t("context_remove_favorite", self.lang))
        else:
            fav_action = menu.addAction(t("context_add_favorite", self.lang))
        fav_action.triggered.connect(lambda: self._toggle_favorite(device))
        
        menu.addSeparator()
        
        # Copy IP action
        copy_action = menu.addAction(t("copy_ip", self.lang))
        copy_action.triggered.connect(lambda: self._copy_ip_to_clipboard(device.ip))

        menu.addSeparator()

        # Remove from list action
        remove_action = menu.addAction(t("remove_from_list", self.lang))
        remove_action.triggered.connect(lambda: self._request_remove(device))

        # Show menu
        menu.exec(self.list_widget.mapToGlobal(position))

    def _request_remove(self, device: Device):
        """Cihazı arayüzden çıkar, çekirdeğe de bildirilmesini iste."""
        self.remove_device(device)
        self.device_remove_requested.emit(device)


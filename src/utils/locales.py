"""TransferTCP çoklu dil (TR / EN) yerelleştirme modülü."""

from __future__ import annotations

import locale
import os
import sys
from typing import Any

LOCALES: dict[str, dict[str, str]] = {
    "tr": {
        "app_title": "TransferTCP",
        "file": "Dosya",
        "view": "Görünüm",
        "help": "Yardım",
        "send_file": "Dosya Gönder",
        "send_folder": "Klasör Gönder",
        "settings": "Ayarlar",
        "exit": "Çıkış",
        "history": "Transfer Geçmişi",
        "theme": "Tema",
        "theme_system": "Sistem",
        "theme_dark": "Koyu",
        "theme_light": "Açık",
        "minimize": "Simge Durumuna Küçült",
        "about": "Hakkında",
        "quick_connect": "Hızlı Bağlantı",
        "drag_drop_text": "Dosyaları veya klasörleri buraya sürükleyin",
        "select_file": "Dosya Seç",
        "select_folder": "Klasör Seç",
        "clear_list": "Listeyi Temizle",
        "list_cleared": "{n} transfer temizlendi",
        "list_already_clean": "Liste zaten temiz",
        "cancel_all_transfers": "Gönderimleri İptal Et",
        "clear_history": "Transfer Geçmişini Temizle",
        "history_cleared": "Transfer geçmişi temizlendi",
        "devices": "Cihazlar",
        "search_devices": "Cihaz Ara…",
        "transfers": "Transferler",
        "filter_all": "Tümü",
        "filter_active": "Devam Eden",
        "filter_completed": "Tamamlanan",
        "filter_failed": "Başarısız",
        "status_waiting": "Bağlantı bekleniyor…",
        "status_scanning": "Cihazlar taranıyor…",
        "refresh_network": "Ağı Yenile",
        "status_saved": "✓ Ayarlar kaydedildi",
        "tray_show": "Göster",
        "tray_hide": "Gizle",
        "tray_quit": "Çıkış",
        "tray_update_now": "Güncelle · v{version}",
        "open_file": "Dosyayı Aç",
        "show_in_folder": "Klasörde Göster",
        "retry": "Tekrar Dene",
        "cancel": "İptal",
        "remove_from_list": "Listeden Kaldır",
        "settings_title": "Ayarlar",
        "tab_general": "Genel",
        "tab_transfer": "Transfer",
        "tab_appearance": "Görünüm",
        "tab_advanced": "Ağ ve Gelişmiş",
        "device_name": "Cihaz Adı",
        "computer_name": "Bilgisayar Adı",
        "local_ip": "Yerel IP",
        "device_visible_hint": "Bu ad, aynı ağdaki diğer cihazlarda görünür.",
        "add_device": "Cihaz Ekle",
        "add_device_tooltip": "IP adresiyle cihaz ekle (farklı ağlar için)",
        "manual_device_title": "IP ile Cihaz Ekle",
        "manual_device_hint": "Yayın (broadcast) kapalı ağlarda karşı cihazın IP adresini girin. İki cihazda da program açık olmalı.",
        "device_alias": "Görünen Ad",
        "device_alias_placeholder": "Örn. Ofis Bilgisayarı",
        "port_hint": "1024–65535 arasında bir port",
        "invalid_ip": "Geçerli bir IP adresi girin (örn: 192.168.1.42).",
        "device_unreachable": "{ip} adresine ulaşılamadı. IP ve portu kontrol edip tekrar deneyin.",
        "probing_device": "{ip} aranıyor…",
        "local_device_info": "Bu cihaz: {name} · {ip}:{port}",
        "device_online": "Çevrimiçi",
        "device_offline": "Çevrimdışı",
        "drop_target_none": "Önce soldan bir cihaz seçin",
        "drop_target_offline": "{name} çevrimdışı",
        "drop_target_ready": "Hedef: {name} · {ip}",
        "transfers_empty_title": "Henüz transfer yok",
        "transfers_empty_hint": "Soldan bir cihaz seçin, sonra dosya veya klasörleri yukarıdaki alana bırakın.",
        "empty_devices_title": "Henüz cihaz yok",
        "empty_devices_hint": "Aynı ağdaki cihazlar otomatik görünür. Farklı ağdaysanız IP ile ekleyin.",
        "auto_start": "Açılışta Başlat",
        "start_minimized": "Başlangıçta Sistem Tepsisine Küçült",
        "show_notifications": "Masaüstü Bildirimlerini Göster",
        "play_sounds": "Transfer Seslerini Çal",
        "download_folder": "İndirme Klasörü",
        "browse": "Gözat…",
        "port": "Transfer Portu",
        "auto_open": "Transfer Bitince Dosyayı Otomatik Aç",
        "overwrite_existing": "Aynı Adlı Dosyanın Üzerine Yaz",
        "language": "Dil",
        "enable_logging": "Günlük Tutmayı Etkinleştir",
        "log_level": "Log Seviyesi",
        "auto_update": "Güncellemeleri Otomatik Kontrol Et",
        "check_now": "Kontrol Et",
        "update_pill": "Güncelle · v{version}",
        "update_pill_tip": "Yeni sürüm v{version} hazır; ayrıntılar ve kurulum için tıklayın",
        "update_new_version": "Yeni sürüm: v{version}",
        "update_status_current": "Güncel · v{version}",
        "update_status_failed": "Denetlenemedi",
        "auto_update_install": "Güncellemeleri Otomatik Kur",
        "update_auto_failed": "Otomatik güncelleme tamamlanamadı; başlık çubuğundaki Güncelle düğmesinden yeniden deneyebilirsiniz.",
        "save": "Kaydet",
        "reset_defaults": "Varsayılanlara Sıfırla",
        "online": "Çevrimiçi",
        "offline": "Çevrimdışı",
        "ip_address": "IP Adresi",
        "status_transfer_complete": "Transfer Tamamlandı",
        "status_transfer_failed": "Transfer Hatası",
        "about_title": "TransferTCP Hakkında",
        "about_tagline": "Modern ve hızlı dosya transfer programı",
        "about_features": "Özellikler",
        "about_feature_discovery": "Otomatik cihaz keşfi",
        "about_feature_bidirectional": "Çift yönlü transfer",
        "about_feature_controls": "Duraklat / Devam et / İptal",
        "about_feature_fast": "Basit ve hızlı aktarım",
        "about_feature_e2ee": "Uçtan uca şifreli güvenli transfer",
        "port_changed": "Port {old} kullanılamadı, {new} ile devam ediliyor",
        "ok": "Tamam",
        "yes": "Evet",
        "no": "Hayır",
        "security": "Güvenlik",
        "encryption_enabled": "Uçtan Uca Şifreleme (TLS 1.3)",
        "accept_from_anyone": "Herkesten Soru Sormadan Dosya Kabul Et",
        "accept_from_anyone_hint": "Kapalıysa yeni cihazlar ilk kez dosya gönderirken onay ister.",
        "your_fingerprint": "Bu cihazın donanım kimliği:",
        "clear_trusted": "Güvenilen Cihazları Temizle",
        "trusted_count": "{count} güvenilen cihaz",
        "trusted_cleared": "Güvenilen cihaz listesi temizlendi.",
        "trusted_clear_confirm": "Tüm güvenilen cihazlar unutulsun mu? Sonraki transferlerde yeniden onay istenecektir.",
        "trust_device_title": "Gelen Transfer",
        "trust_device_text": "{name} ({ip}) size dosya göndermek istiyor.\n\nBu cihazı güvenilir olarak kaydetmek ister misiniz?",
        "trust_device_fingerprint": "Kimlik: {fingerprint}",
        "trust_accept": "Kabul Et",
        "trust_reject": "Reddet",
        "trust_toast_title": "Dosya göndermek isteyen cihaz",
        "trust_timeout": "Cihaz onayı zaman aşımına uğradı.",
        "eta_seconds": "{n} sn",
        "eta_minutes": "{m} dk {s} sn",
        "eta_hours": "{h} sa {m} dk",
        "eta_left": "kaldı",
        "group_device_settings": "Cihaz Ayarları",
        "group_startup": "Başlangıç",
        "group_notifications": "Bildirimler",
        "group_file_location": "Dosya Konumu",
        "group_network_settings": "Ağ Ayarları",
        "group_transfer_settings": "Transfer Ayarları",
        "chunk_size": "Chunk Boyutu",
        "speed_limit": "Hız Sınırı",
        "speed_limit_suffix": " MB/s (0 = sınırsız)",
        "concurrent_transfers": "Eşzamanlı Transfer",
        "group_logging": "Günlük",
        "group_updates": "Güncellemeler",
        "checking_updates": "Kontrol ediliyor…",
        "select_download_folder": "İndirme Klasörünü Seç",
        "warning": "Uyarı",
        "autostart_failed": "Otomatik başlatma ayarı yapılamadı.\nProgramı yönetici olarak çalıştırmayı deneyin.",
        "drop_zone_text": "Dosyaları buraya\nsürükleyin veya",
        "window_minimize": "Küçült",
        "window_maximize": "Büyüt",
        "window_close": "Kapat",
        "refresh": "Yenile",
        "refresh_devices_tooltip": "Cihazları Yenile",
        "context_send_file": "Dosya Gönder",
        "context_remove_favorite": "Favorilerden Çıkar",
        "context_add_favorite": "Favorilere Ekle",
        "copy_ip": "IP'yi Kopyala",
        "transfer_status_pending": "Bekliyor",
        "transfer_status_connecting": "Onay bekliyor",
        "transfer_status_transferring": "Aktarılıyor",
        "transfer_status_paused": "Duraklatıldı",
        "transfer_status_completed": "Tamamlandı",
        "transfer_status_failed": "Başarısız",
        "transfer_status_cancelled": "İptal Edildi",
        "transfer_status_unknown": "Bilinmiyor",
        "transfer_info_completed": "✓ Tamamlandı - {device}",
        "transfer_info_failed": "✕ Başarısız - {error}",
        "transfer_info_cancelled": "İptal Edildi - {device}",
        "status_pending_short": "Bekliyor…",
        "status_retrying": "Yeniden deneniyor…",
        "transfer_retrying": "Yeniden deneniyor ({n})…",
        "transfer_queued": "Sırada (aynı anda en fazla {n})",
        "status_waiting_approval": "Onay bekliyor…",
        "pause_tooltip": "Duraklat",
        "pause_local_tooltip": "Duraklat (sadece bu tarafta)",
        "cancel_tooltip": "İptal Et",
        "resume_tooltip": "Devam Et",
        "folder_default": "Klasör",
        "active_count": "{count} aktif",
        "stats_sent_received": "Gönderilen: {sent}  ·  Alınan: {received}",
        "update_available_title": "Güncelleme Mevcut",
        "update_version_heading": "TransferTCP Sürüm {version} Mevcut!",
        "update_version_line": "Mevcut sürüm: {current} → Yeni sürüm: {new}",
        "update_notes": "Sürüm Notları",
        "update_available_plain": "Güncelleme mevcut.",
        "update_later": "Daha Sonra",
        "update_now": "Şimdi Güncelle",
        "update_downloading": "İndiriliyor…",
        "update_downloaded_bytes": "{bytes} indirildi",
        "update_download_done": "İndirme tamamlandı!",
        "update_installing": "Kuruluyor, lütfen bekleyin…",
        "update_restarting": "Kurulum tamamlandı! Uygulama yeniden başlatılıyor…",
        "update_check_title": "Güncelleme Kontrolü",
        "update_current": "TransferTCP güncel!\n\nMevcut sürüm: {version}",
        "update_check_failed_msg": "Güncelleme kontrolü yapılamadı.\nLütfen internet bağlantınızı kontrol edin.",
        "update_check_error": "Güncelleme kontrolü sırasında bir hata oluştu:\n{error}",
        "tray_update_tooltip": "TransferTCP - Güncelleme mevcut (v{version})",
        "update_size_line": "İndirme boyutu: {size}",
        "update_retry": "Tekrar Dene",
        "update_failed_inline": "Güncelleme tamamlanamadı: {error}",
        "update_installed_toast": "{app} v{version} sürümüne güncellendi.",
        "update_blocked_inline": "Şu anda {count} dosya aktarımı sürüyor. Aktarımlar bitince Şimdi Güncelle'ye yeniden basın.",
        "update_busy_inline": "Önceki indirme kapatılıyor; birkaç saniye sonra yeniden deneyin.",
        "update_no_write": "Uygulamanın bulunduğu klasöre ({folder}) yazılamıyor. Uygulamayı yazılabilir bir klasöre (ör. Masaüstü) taşıyıp yeniden deneyin.",
        "update_unsupported_source": "Uygulama kaynak koddan çalıştığı için kendini güncelleyemez. Paketlenmiş (exe) sürümü macik.com.tr adresinden indirin.",
        "update_unsupported_os": "Otomatik kurulum yalnızca Windows'ta yapılabilir. Yeni sürümü macik.com.tr adresinden indirin.",
        "device_joined": "{name} ağa katıldı",
        "device_left": "{name} ağdan ayrıldı",
        "sending_folder": "{folder} klasörü ({count} dosya) {device}'e gönderiliyor…",
        "sending_files": "{count} dosya {device}'e gönderiliyor…",
        "transfer_paused": "{filename} duraklatıldı",
        "transfer_cannot_resume": "Gönderim devam ettirilemez. Lütfen yeniden gönderin.",
        "transfer_resumed": "{filename} devam ediyor",
        "folder_transfer_complete_title": "Klasör Transferi Tamamlandı",
        "folder_transfer_complete_toast": "{folder} klasörü ({count} dosya) başarıyla {direction}",
        "direction_sent": "gönderildi",
        "direction_received": "alındı",
        "transfer_complete_title": "Transfer Tamamlandı",
        "transfer_complete_toast": "{filename} başarıyla {direction}",
        "file_complete_progress": "✓ {filename} tamamlandı ({completed}/{total})",
        "file_complete": "✓ {filename} tamamlandı",
        "file_failed_folder": "✕ {folder} klasörü transferi başarısız",
        "file_failed": "✕ {filename} - {error}",
        "transfer_failed_generic": "Transfer başarısız",
        "unknown_error": "Bilinmeyen hata",
        "devices_found": "✓ {count} cihaz bulundu",
        "receiving_file": "{filename} alınıyor ({device})…",
        "refreshing_devices": "Cihazlar yenileniyor…",
        "msg_select_device_title": "Cihaz Seçin",
        "msg_select_device_text": "Önce sol panelden dosya göndermek istediğiniz cihazı seçin.",
        "msg_select_folder_device_text": "Önce sol panelden klasör göndermek istediğiniz cihazı seçin.",
        "msg_device_offline_title": "Cihaz Çevrimdışı",
        "msg_device_offline_text": "{name} şu anda çevrimdışı.\nLütfen cihazın açık ve ağa bağlı olduğundan emin olun.",
        "msg_device_offline_send": "{name} şu anda erişilebilir değil.\n\nCihazın açık ve ağa bağlı olduğundan emin olun.",
        "msg_target_required_title": "Hedef Cihaz Gerekli",
        "msg_target_files_text": "Lütfen sol panelden dosya göndermek istediğiniz cihazı seçin.",
        "msg_target_folder_text": "Lütfen sol panelden klasör göndermek istediğiniz cihazı seçin.",
        "msg_device_unavailable_title": "Cihaz Kullanılamıyor",
        "msg_device_unavailable_text": "{name} şu anda çevrimdışı.\n\nCihazın açık ve ağa bağlı olduğundan emin olun.",
        "msg_folder_empty_title": "Klasör Boş",
        "msg_folder_empty_text": "Seçilen klasörde gönderilecek dosya bulunamadı.",
        "msg_many_files_title": "Çok Sayıda Dosya",
        "msg_many_files_confirm": "Seçilen klasör {count} dosya içeriyor.\n\nTüm dosyaları {name}'e göndermek istediğinizden emin misiniz?",
        "dlg_send_files_title": "Dosyaları {name}'e Gönder",
        "dlg_send_folder_title": "Klasörü {name}'e Gönder",
        "history_dialog_title": "Transfer Geçmişi",
        "history_header": "TRANSFER GEÇMİŞİ",
        "all_files": "Tüm Dosyalar (*.*)",
        "lang_auto": "Otomatik (Sistem)",
        "close": "Kapat",
        "accent": "Renk",
        "accent_default": "(varsayılan)",
        "accent_cyan": "Turkuaz",
        "accent_blue": "Mavi",
        "accent_teal": "Zümrüt",
        "accent_indigo": "İndigo",
        "accent_violet": "Mor",
        "accent_rose": "Gül",
        "accent_orange": "Kehribar",
        "accent_red": "Kırmızı",
        "accent_green": "Yeşil",
        "accent_yellow": "Sarı",
        "auto_update_tip": "Yeni sürüm bulunduğunda arka planda indirilir ve uygulama kullanılmıyorken kurulur.",
        "log_debug": "Hata Ayıklama",
        "log_info": "Bilgi",
        "log_warning": "Uyarı",
        "log_error": "Hata",
        "history_empty_title": "Henüz transfer geçmişi yok",
        "history_empty_hint": "Gönderdiğiniz ve aldığınız dosyalar burada listelenir. Başlamak için soldan bir cihaz seçip dosyaları bırakın.",
        "history_outgoing": "Giden ↑",
        "history_incoming": "Gelen ↓",
        "clear_history_confirm": "Transfer geçmişini temizlemek istediğinizden emin misiniz?",
        "welcome_title": "TransferTCP'ye Hoş Geldiniz",
        "welcome_intro": "Başlamadan önce bu cihaza bir ad verin; aynı ağdaki diğer cihazlar sizi bu adla görür. İndirme klasörünü de seçebilirsiniz.",
        "welcome_tip": "Dosya göndermek için soldan bir cihaz seçip dosyaları pencereye bırakın. Pencereyi kapatınca uygulama tepside çalışmaya devam eder. Bu ayarların hepsini sonradan Ayarlar'dan değiştirebilirsiniz.",
        "welcome_start": "Başla",
    },
    "en": {
        "app_title": "TransferTCP",
        "file": "File",
        "view": "View",
        "help": "Help",
        "send_file": "Send File",
        "send_folder": "Send Folder",
        "settings": "Settings",
        "exit": "Exit",
        "history": "Transfer History",
        "theme": "Theme",
        "theme_system": "System",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "minimize": "Minimize to Tray",
        "about": "About",
        "quick_connect": "Quick Connect",
        "drag_drop_text": "Drag and drop files or folders here",
        "select_file": "Select File",
        "select_folder": "Select Folder",
        "clear_list": "Clear List",
        "list_cleared": "{n} transfers cleared",
        "list_already_clean": "The list is already clean",
        "cancel_all_transfers": "Cancel Transfers",
        "clear_history": "Clear Transfer History",
        "history_cleared": "Transfer history cleared",
        "devices": "Devices",
        "search_devices": "Search Devices…",
        "transfers": "Transfers",
        "filter_all": "All",
        "filter_active": "In Progress",
        "filter_completed": "Completed",
        "filter_failed": "Failed",
        "status_waiting": "Waiting for connection…",
        "status_scanning": "Scanning for devices…",
        "refresh_network": "Refresh Network",
        "status_saved": "✓ Settings saved",
        "tray_show": "Show",
        "tray_hide": "Hide",
        "tray_quit": "Exit",
        "tray_update_now": "Update · v{version}",
        "open_file": "Open File",
        "show_in_folder": "Show in Folder",
        "retry": "Retry",
        "cancel": "Cancel",
        "remove_from_list": "Remove from List",
        "settings_title": "Settings",
        "tab_general": "General",
        "tab_transfer": "Transfer",
        "tab_appearance": "Appearance",
        "tab_advanced": "Network & Advanced",
        "device_name": "Device Name",
        "computer_name": "Computer Name",
        "local_ip": "Local IP",
        "device_visible_hint": "This name is visible to other devices on the same network.",
        "add_device": "Add Device",
        "add_device_tooltip": "Add device by IP address (for different networks)",
        "manual_device_title": "Add Device by IP",
        "manual_device_hint": "On networks with broadcast disabled, enter the other device's IP address. The app must be open on both devices.",
        "device_alias": "Display Name",
        "device_alias_placeholder": "e.g. Office Computer",
        "port_hint": "A port between 1024 and 65535",
        "invalid_ip": "Enter a valid IP address (e.g. 192.168.1.42).",
        "device_unreachable": "Could not reach {ip}. Check the IP and port, then try again.",
        "probing_device": "Probing {ip}…",
        "local_device_info": "This device: {name} · {ip}:{port}",
        "device_online": "Online",
        "device_offline": "Offline",
        "drop_target_none": "Select a device on the left first",
        "drop_target_offline": "{name} is offline",
        "drop_target_ready": "Target: {name} · {ip}",
        "transfers_empty_title": "No transfers yet",
        "transfers_empty_hint": "Select a device on the left, then drop files or folders on the area above.",
        "empty_devices_title": "No devices yet",
        "empty_devices_hint": "Devices on the same network appear automatically. If on a different network, add by IP.",
        "auto_start": "Start at Login",
        "start_minimized": "Start Minimized to System Tray",
        "show_notifications": "Show Desktop Notifications",
        "play_sounds": "Play Transfer Sounds",
        "download_folder": "Download Folder",
        "browse": "Browse…",
        "port": "Transfer Port",
        "auto_open": "Automatically Open File After Transfer",
        "overwrite_existing": "Overwrite Files with the Same Name",
        "language": "Language",
        "enable_logging": "Enable Logging",
        "log_level": "Log Level",
        "auto_update": "Check for Updates Automatically",
        "check_now": "Check for Updates",
        "update_pill": "Update · v{version}",
        "update_pill_tip": "Version v{version} is ready; click for details and installation",
        "update_new_version": "New version: v{version}",
        "update_status_current": "Up to date · v{version}",
        "update_status_failed": "Could not check",
        "auto_update_install": "Install Updates Automatically",
        "update_auto_failed": "The automatic update could not be completed; you can retry from the Update button in the title bar.",
        "save": "Save",
        "reset_defaults": "Reset to Defaults",
        "online": "Online",
        "offline": "Offline",
        "ip_address": "IP Address",
        "status_transfer_complete": "Transfer Completed",
        "status_transfer_failed": "Transfer Failed",
        "about_title": "About TransferTCP",
        "about_tagline": "A modern and fast file transfer app",
        "about_features": "Features",
        "about_feature_discovery": "Automatic device discovery",
        "about_feature_bidirectional": "Bidirectional transfers",
        "about_feature_controls": "Pause / Resume / Cancel",
        "about_feature_fast": "Simple, high-speed transfers",
        "about_feature_e2ee": "End-to-end encrypted (TLS 1.3) secure transfer",
        "port_changed": "Port {old} was busy, continuing on {new}",
        "ok": "OK",
        "yes": "Yes",
        "no": "No",
        "security": "Security",
        "encryption_enabled": "End-to-End Encryption (TLS 1.3)",
        "accept_from_anyone": "Accept Files from Anyone Without Asking",
        "accept_from_anyone_hint": "When off, new devices must be approved the first time they send a file.",
        "your_fingerprint": "This device hardware identity:",
        "clear_trusted": "Clear Trusted Devices",
        "trusted_count": "{count} trusted devices",
        "trusted_cleared": "Trusted device list cleared.",
        "trusted_clear_confirm": "Forget all trusted devices? Future transfers will ask for approval again.",
        "trust_device_title": "Incoming Transfer",
        "trust_device_text": "{name} ({ip}) wants to send you a file.\n\nTrust this device for future transfers?",
        "trust_device_fingerprint": "Identity: {fingerprint}",
        "trust_accept": "Accept",
        "trust_reject": "Reject",
        "trust_toast_title": "A device wants to send a file",
        "trust_timeout": "Device approval timed out.",
        "eta_seconds": "{n}s",
        "eta_minutes": "{m}m {s}s",
        "eta_hours": "{h}h {m}m",
        "eta_left": "left",
        "group_device_settings": "Device Settings",
        "group_startup": "Startup",
        "group_notifications": "Notifications",
        "group_file_location": "File Location",
        "group_network_settings": "Network Settings",
        "group_transfer_settings": "Transfer Settings",
        "chunk_size": "Chunk Size",
        "speed_limit": "Speed Limit",
        "speed_limit_suffix": " MB/s (0 = unlimited)",
        "concurrent_transfers": "Concurrent Transfers",
        "group_logging": "Logging",
        "group_updates": "Updates",
        "checking_updates": "Checking…",
        "select_download_folder": "Select Download Folder",
        "warning": "Warning",
        "autostart_failed": "Could not configure auto-start.\nTry running the program as administrator.",
        "drop_zone_text": "Drag files here\nor select below",
        "window_minimize": "Minimize",
        "window_maximize": "Maximize",
        "window_close": "Close",
        "refresh": "Refresh",
        "refresh_devices_tooltip": "Refresh Devices",
        "context_send_file": "Send File",
        "context_remove_favorite": "Remove from Favorites",
        "context_add_favorite": "Add to Favorites",
        "copy_ip": "Copy IP",
        "transfer_status_pending": "Pending",
        "transfer_status_connecting": "Awaiting approval",
        "transfer_status_transferring": "Transferring",
        "transfer_status_paused": "Paused",
        "transfer_status_completed": "Completed",
        "transfer_status_failed": "Failed",
        "transfer_status_cancelled": "Cancelled",
        "transfer_status_unknown": "Unknown",
        "transfer_info_completed": "✓ Completed - {device}",
        "transfer_info_failed": "✕ Failed - {error}",
        "transfer_info_cancelled": "Cancelled - {device}",
        "status_pending_short": "Pending…",
        "status_retrying": "Retrying…",
        "transfer_retrying": "Retrying ({n})…",
        "transfer_queued": "Queued (max {n} at once)",
        "status_waiting_approval": "Awaiting approval…",
        "pause_tooltip": "Pause",
        "pause_local_tooltip": "Pause (local only)",
        "cancel_tooltip": "Cancel",
        "resume_tooltip": "Resume",
        "folder_default": "Folder",
        "active_count": "{count} active",
        "stats_sent_received": "Sent: {sent}  ·  Received: {received}",
        "update_available_title": "Update Available",
        "update_version_heading": "TransferTCP Version {version} Available!",
        "update_version_line": "Current version: {current} → New version: {new}",
        "update_notes": "Release Notes",
        "update_available_plain": "An update is available.",
        "update_later": "Later",
        "update_now": "Update Now",
        "update_downloading": "Downloading…",
        "update_downloaded_bytes": "{bytes} downloaded",
        "update_download_done": "Download complete!",
        "update_installing": "Installing, please wait…",
        "update_restarting": "Installation complete! Restarting the app…",
        "update_check_title": "Update Check",
        "update_current": "TransferTCP is up to date.\n\nCurrent version: {version}",
        "update_check_failed_msg": "Could not check for updates.\nPlease check your internet connection.",
        "update_check_error": "An error occurred while checking for updates:\n{error}",
        "tray_update_tooltip": "TransferTCP - Update available (v{version})",
        "update_size_line": "Download size: {size}",
        "update_retry": "Retry",
        "update_failed_inline": "The update could not be completed: {error}",
        "update_installed_toast": "{app} was updated to v{version}.",
        "update_blocked_inline": "{count} file transfer(s) are in progress. Press Update Now again when they finish.",
        "update_busy_inline": "The previous download is being stopped; try again in a few seconds.",
        "update_no_write": "Cannot write to the folder the app is in ({folder}). Move the app to a writable folder (for example the Desktop) and try again.",
        "update_unsupported_source": "The app is running from source code and cannot update itself. Download the packaged (exe) version from macik.com.tr.",
        "update_unsupported_os": "Automatic installation is only available on Windows. Download the new version from macik.com.tr.",
        "device_joined": "{name} joined the network",
        "device_left": "{name} left the network",
        "sending_folder": "Sending folder {folder} ({count} files) to {device}…",
        "sending_files": "Sending {count} file(s) to {device}…",
        "transfer_paused": "{filename} paused",
        "transfer_cannot_resume": "Cannot resume sending. Please send again.",
        "transfer_resumed": "{filename} resumed",
        "folder_transfer_complete_title": "Folder Transfer Complete",
        "folder_transfer_complete_toast": "{folder} folder ({count} files) {direction} successfully",
        "direction_sent": "sent",
        "direction_received": "received",
        "transfer_complete_title": "Transfer Complete",
        "transfer_complete_toast": "{filename} {direction} successfully",
        "file_complete_progress": "✓ {filename} complete ({completed}/{total})",
        "file_complete": "✓ {filename} complete",
        "file_failed_folder": "✕ {folder} folder transfer failed",
        "file_failed": "✕ {filename} - {error}",
        "transfer_failed_generic": "Transfer failed",
        "unknown_error": "Unknown error",
        "devices_found": "✓ {count} device(s) found",
        "receiving_file": "Receiving {filename} ({device})…",
        "refreshing_devices": "Refreshing devices…",
        "msg_select_device_title": "Select Device",
        "msg_select_device_text": "Please select the device you want to send files to from the left panel first.",
        "msg_select_folder_device_text": "Please select the device you want to send folder to from the left panel first.",
        "msg_device_offline_title": "Device Offline",
        "msg_device_offline_text": "{name} is currently offline.\nPlease make sure the device is on and connected to the network.",
        "msg_device_offline_send": "{name} is currently unreachable.\n\nMake sure the device is on and connected to the network.",
        "msg_target_required_title": "Target Device Required",
        "msg_target_files_text": "Please select the device you want to send files to from the left panel.",
        "msg_target_folder_text": "Please select the device you want to send folder to from the left panel.",
        "msg_device_unavailable_title": "Device Unavailable",
        "msg_device_unavailable_text": "{name} is currently offline.\n\nMake sure the device is on and connected to the network.",
        "msg_folder_empty_title": "Folder Empty",
        "msg_folder_empty_text": "No files found to send in the selected folder.",
        "msg_many_files_title": "Many Files",
        "msg_many_files_confirm": "The selected folder contains {count} files.\n\nAre you sure you want to send all files to {name}?",
        "dlg_send_files_title": "Send Files to {name}",
        "dlg_send_folder_title": "Send Folder to {name}",
        "history_dialog_title": "Transfer History",
        "history_header": "TRANSFER HISTORY",
        "all_files": "All Files (*.*)",
        "lang_auto": "Auto (System)",
        "close": "Close",
        "accent": "Color",
        "accent_default": "(default)",
        "accent_cyan": "Cyan",
        "accent_blue": "Blue",
        "accent_teal": "Teal",
        "accent_indigo": "Indigo",
        "accent_violet": "Violet",
        "accent_rose": "Rose",
        "accent_orange": "Amber",
        "accent_red": "Red",
        "accent_green": "Green",
        "accent_yellow": "Yellow",
        "auto_update_tip": "When a new version is found, it is downloaded in the background and installed while the app is idle.",
        "log_debug": "Debug",
        "log_info": "Info",
        "log_warning": "Warning",
        "log_error": "Error",
        "history_empty_title": "No transfer history yet",
        "history_empty_hint": "Files you send and receive are listed here. To get started, select a device on the left and drop files.",
        "history_outgoing": "Outgoing ↑",
        "history_incoming": "Incoming ↓",
        "clear_history_confirm": "Are you sure you want to clear transfer history?",
        "welcome_title": "Welcome to TransferTCP",
        "welcome_intro": "Before you start, give this device a name; other devices on the same network will see you by it. You can also choose the download folder.",
        "welcome_tip": "To send files, select a device on the left and drop files on the window. Closing the window keeps the app running in the tray. You can change all of these later in Settings.",
        "welcome_start": "Start",
    },
}

SUPPORTED_LANGUAGES: tuple[str, ...] = tuple(LOCALES.keys())
FALLBACK_LANGUAGE = "tr"
AUTO_LANGUAGE = "auto"

LANGUAGE_NAMES: dict[str, str] = {
    "tr": "Türkçe",
    "en": "English",
}

LANGUAGE_FLAGS: dict[str, str] = {
    "auto": "🌐",
    "tr": "🇹🇷",
    "en": "🇺🇸",
    "de": "🇩🇪",
    "fr": "🇫🇷",
    "es": "🇪🇸",
    "it": "🇮🇹",
    "nl": "🇳🇱",
    "ru": "🇷🇺",
    "ar": "🇸🇦",
}


def language_flag(code: str | None) -> str:
    if not code:
        return ""
    return LANGUAGE_FLAGS.get(code, "")


_FLAG_ICONS_CACHE: dict[str, Any] = {}


def create_language_icon(code: str = "auto") -> Any:
    """Windows emoji bayrakları desteklemediği için gerçek vektörel bayrak ikonu döner."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPainterPath, QPolygonF, QPen
    from PyQt6.QtCore import Qt, QPointF, QRectF
    import math

    if QApplication.instance() is None:
        from PyQt6.QtGui import QIcon
        return QIcon()

    raw_key = (code or "auto").lower()
    is_auto = raw_key in ("auto", "", "none")

    if is_auto:
        detected = get_system_language() or "tr"
        code_key = (detected or "tr").lower()
        cache_key = f"auto_{code_key}"
    else:
        code_key = raw_key
        cache_key = code_key

    if cache_key in _FLAG_ICONS_CACHE:
        return _FLAG_ICONS_CACHE[cache_key]

    w, h = 48, 32
    pix = QPixmap(w, h)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    clip = QPainterPath()
    clip.addRoundedRect(QRectF(1.0, 1.0, w - 2, h - 2), 5.0, 5.0)
    p.setClipPath(clip)

    if code_key == "tr":
        p.fillRect(QRectF(0, 0, w, h), QColor("#E30A17"))

        # Hilal
        c_outer = QPainterPath()
        c_outer.addEllipse(QPointF(w * 0.38, h * 0.5), h * 0.32, h * 0.32)
        c_inner = QPainterPath()
        c_inner.addEllipse(QPointF(w * 0.45, h * 0.5), h * 0.25, h * 0.25)
        p.fillPath(c_outer.subtracted(c_inner), QColor("#ffffff"))

        # Yıldız
        star_center = QPointF(w * 0.63, h * 0.5)
        star_r_out = h * 0.14
        star_r_in = star_r_out * 0.382
        pts = []
        angle_offset = -math.pi / 2
        for i in range(10):
            r = star_r_out if i % 2 == 0 else star_r_in
            a = angle_offset + i * math.pi / 5
            pts.append(QPointF(star_center.x() + r * math.cos(a), star_center.y() + r * math.sin(a)))
        star_path = QPainterPath()
        star_path.addPolygon(QPolygonF(pts))
        p.fillPath(star_path, QColor("#ffffff"))

    elif code_key in ("en", "us"):
        stripe_h = h / 7.0
        for i in range(7):
            col = QColor("#B22234") if i % 2 == 0 else QColor("#FFFFFF")
            p.fillRect(QRectF(0, i * stripe_h, w, stripe_h + 0.5), col)
        canton_w = w * 0.45
        canton_h = stripe_h * 4.0
        p.fillRect(QRectF(0, 0, canton_w, canton_h), QColor("#3C3B6E"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        for r in range(2):
            for c in range(3):
                sx = canton_w * 0.2 + c * (canton_w * 0.3)
                sy = canton_h * 0.28 + r * (canton_h * 0.44)
                p.drawEllipse(QPointF(sx, sy), 1.4, 1.4)
    else:
        p.fillRect(QRectF(0, 0, w, h), QColor("#1e293b"))
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0ea5e9"))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(QColor("#ffffff"), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
        p.drawEllipse(QPointF(cx, cy), r * 0.5, r)

    # Otomatik mod rozeti (Sağ üst köşede şık mavi mini küre)
    if is_auto:
        p.setClipping(False)
        badge_cx, badge_cy, badge_r = w - 8.5, 8.5, 5.5
        p.setPen(QPen(QColor("#ffffff"), 1.2))
        p.setBrush(QColor("#0284c7"))
        p.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)
        p.setPen(QPen(QColor("#ffffff"), 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(badge_cx - badge_r + 1.0, badge_cy), QPointF(badge_cx + badge_r - 1.0, badge_cy))
        p.drawLine(QPointF(badge_cx, badge_cy - badge_r + 1.0), QPointF(badge_cx, badge_cy + badge_r - 1.0))
        p.drawEllipse(QPointF(badge_cx, badge_cy), badge_r * 0.5, badge_r * 0.9)

    # Açık ve koyu temalarda sınırları belirginleştiren zarif kontur
    p.setClipping(False)
    p.setPen(QPen(QColor(15, 23, 42, 70), 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(1.0, 1.0, w - 2, h - 2), 5.0, 5.0)

    p.end()
    icon = QIcon(pix)
    _FLAG_ICONS_CACHE[cache_key] = icon
    return icon


def language_display_name(code: str) -> str:
    native = LANGUAGE_NAMES.get(code, code.upper())
    code_label = "US" if code == "en" else code.upper()
    return f"{code_label} · {native}"


_LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    "turkce": "tr",
    "türkçe": "tr",
    "turkish": "tr",
    "turk": "tr",
    "english": "en",
    "ingilizce": "en",
    "german": "de",
    "deutsch": "de",
    "almanca": "de",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    "fransizca": "fr",
    "fransızca": "fr",
    "spanish": "es",
    "espanol": "es",
    "español": "es",
    "ispanyolca": "es",
    "italian": "it",
    "italiano": "it",
    "italyanca": "it",
}

_WIN_PRIMARY_LANG_TO_CODE: dict[int, str] = {
    0x1F: "tr",
    0x09: "en",
    0x07: "de",
    0x0C: "fr",
    0x0A: "es",
    0x10: "it",
    0x13: "nl",
    0x19: "ru",
    0x01: "ar",
}


def _normalize_lang_code(raw: str | None) -> str | None:
    """'tr-TR', 'tr_TR.UTF-8', 'Turkish_Turkiye', 'tr:en_US:en' gibi girdilerden dil kodu çıkarır."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if not s or s in ("c", "c.utf8", "c.utf-8", "posix"):
        return None
    if ":" in s or ";" in s:
        for part in s.replace(";", ":").split(":"):
            code = _normalize_lang_code(part)
            if code:
                return code
        return None
    for sep in (".", "@"):
        if sep in s:
            s = s.split(sep, 1)[0]
    s = s.strip()
    if not s:
        return None
    if s in _LANGUAGE_NAME_TO_CODE:
        cand = _LANGUAGE_NAME_TO_CODE[s]
        if cand in LOCALES:
            return cand
    tokens = s.replace("-", "_").split("_")
    if not tokens:
        return None
    first = tokens[0].strip()
    if first in _LANGUAGE_NAME_TO_CODE:
        first = _LANGUAGE_NAME_TO_CODE[first]
    if first in LOCALES:
        return first
    return None


def _locale_code_from_system() -> str | None:
    """Windows / macOS / Linux'ta gerçek arayüz dilini tespit eder."""
    # Windows'ta Qt'nin bölgesel ayarı, Windows görüntüleme dilinden
    # farklı olabilir. Görüntüleme dilini doğrudan Win32 API'den öncele.
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            for func in ("GetUserDefaultUILanguage", "GetSystemDefaultUILanguage"):
                try:
                    lcid = int(getattr(kernel32, func)())
                    code = _WIN_PRIMARY_LANG_TO_CODE.get(lcid & 0x3FF)
                    if code and code in LOCALES:
                        return code
                except Exception:
                    continue
            buf = ctypes.create_unicode_buffer(85)
            if kernel32.GetUserDefaultLocaleName(buf, 85):
                code = _normalize_lang_code(buf.value)
                if code:
                    return code
        except Exception:
            pass

    for env in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        try:
            val = os.environ.get(env)
            if val:
                for part in val.replace(";", ":").split(":"):
                    code = _normalize_lang_code(part)
                    if code:
                        return code
        except Exception:
            pass
    try:
        from PyQt6.QtCore import QLocale
        ql = QLocale.system()
        try:
            for ui_lang in (ql.uiLanguages() or []):
                code = _normalize_lang_code(ui_lang)
                if code:
                    return code
        except Exception:
            pass
        for candidate in (ql.bcp47Name(), ql.name()):
            try:
                code = _normalize_lang_code(candidate)
            except Exception:
                code = None
            if code:
                return code
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import ctypes
            try:
                kernel32 = ctypes.windll.kernel32
                for func in ("GetUserDefaultUILanguage", "GetSystemDefaultUILanguage"):
                    try:
                        lcid = int(getattr(kernel32, func)())
                        code = _WIN_PRIMARY_LANG_TO_CODE.get(lcid & 0x3FF)
                        if code and code in LOCALES:
                            return code
                    except Exception:
                        continue
                try:
                    buf = ctypes.create_unicode_buffer(85)
                    if kernel32.GetUserDefaultLocaleName(buf, 85):
                        code = _normalize_lang_code(buf.value)
                        if code:
                            return code
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            import subprocess
            try:
                out = subprocess.check_output(
                    ["defaults", "read", "-g", "AppleLanguages"],
                    text=True, timeout=2,
                )
                import re
                for m in re.findall(r'"([^"]+)"', out or ""):
                    code = _normalize_lang_code(m)
                    if code:
                        return code
            except Exception:
                pass
    except Exception:
        pass
    try:
        try:
            loc = locale.getlocale()[0] or ""
            code = _normalize_lang_code(loc)
            if code:
                return code
        except Exception:
            pass
        try:
            loc2 = (locale.getdefaultlocale()[0] or "")
            code = _normalize_lang_code(loc2)
            if code:
                return code
        except Exception:
            pass
    except Exception:
        pass
    return None


def get_system_language() -> str:
    """Sistem dilini desteklenen kodlardan birine çözümler."""
    return _locale_code_from_system() or FALLBACK_LANGUAGE


def _resolve_language_choice(value: str | None) -> str:
    if value and value != AUTO_LANGUAGE and value in LOCALES:
        return value
    return get_system_language()


def get_active_language(config_or_lang: Any = None) -> str:
    """Config nesnesi veya dize üzerinden etkin dili döner."""
    if isinstance(config_or_lang, str):
        return _resolve_language_choice(config_or_lang)
    if config_or_lang is not None and hasattr(config_or_lang, "get"):
        return _resolve_language_choice(config_or_lang.get("ui", "language", AUTO_LANGUAGE))
    return get_system_language()


def configured_language() -> str:
    """Kullanıcının uygulamada seçtiği dil ('auto' ise sistem dili); arayüz parçaları buradan okur."""
    try:
        from .config import get_config

        return get_active_language(get_config())
    except Exception:
        return get_system_language()


def language_choices(
    include_auto: bool = False,
    lang: str | None = None,
) -> list[tuple[str, str]]:
    """Dil seçici için (kod, etiket) çiftleri döner."""
    detected = get_system_language()
    active = lang or detected
    choices: list[tuple[str, str]] = []
    if include_auto:
        base = t("lang_auto", active)
        detected_label = language_display_name(detected)
        if base.endswith(")"):
            auto_label = f"{base[:-1]} - {detected_label})"
        else:
            auto_label = f"{base} - {detected_label}"
        choices.append((AUTO_LANGUAGE, auto_label))
    for code in LOCALES.keys():
        choices.append((code, language_display_name(code)))
    return choices


def t(key: str, lang: str | None = None) -> str:
    """Belirtilen dilde metni döner."""
    if lang is None:
        try:
            from .config import get_config
            cfg = get_config()
            lang = get_active_language(cfg)
        except Exception:
            lang = get_system_language()
    table = LOCALES.get(lang) or LOCALES[FALLBACK_LANGUAGE]
    return table.get(key, LOCALES[FALLBACK_LANGUAGE].get(key, key))


_qt_translators: list = []


def install_qt_translations(lang: str | None = None) -> None:
    """Qt'nin kendi yazılarını (Tamam / İptal / Evet / Hayır, metin kutusu sağ tık menüsü…) uygulama diline çevirir.

    Paketlenmiş uygulamada da çalışır: PyInstaller Qt çevirilerini (`qtbase_*.qm`) pakete koyar. Çeviri
    dosyası bulunamazsa sessizce İngilizce kalır; her çağrı öncekini kaldırıp yenisini kurar.
    """
    try:
        from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
    except ImportError:
        return
    app = QCoreApplication.instance()
    if app is None:
        return
    for old in _qt_translators:
        try:
            app.removeTranslator(old)
        except RuntimeError:  # önceki QApplication yok edilmiş (testler, yeniden başlatma)
            pass
    _qt_translators.clear()
    code = lang or get_system_language()
    folders = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        folders.append(os.path.join(bundle, "PyQt6", "Qt6", "translations"))
    for folder in folders:
        translator = QTranslator(app)
        if translator.load(QLocale(code), "qtbase", "_", folder):
            app.installTranslator(translator)
            _qt_translators.append(translator)
            break
    _install_key_names(app)


def _install_key_names(app) -> None:
    """Kısayol adlarını (menülerdeki "Ctrl+Shift+N") çevirmeden bırakır.

    Qt'nin Türkçe çevirisi bunları "Kontrol+Üst Karakter+N" yapıyordu; klavyedeki tuşlar ise Ctrl/Shift/Alt
    yazar. En son kurulan çevirici önce sorulduğu için bu, qtbase çevirisinin "QShortcut" bölümünü geçersiz
    kılar. macOS'ta Qt zaten ⌘⇧N gibi simgeler kullanır, bunun etkisi olmaz.
    """
    from PyQt6.QtCore import QTranslator

    class _KeyNames(QTranslator):
        def isEmpty(self) -> bool:  # noqa: N802
            return False

        def translate(self, context, source_text, disambiguation=None, n=-1):
            return source_text if context == "QShortcut" else None

    translator = _KeyNames()  # parent'sız: uygulama yok edilince C++ tarafı Python'dan önce silinmesin
    app.installTranslator(translator)
    _qt_translators.append(translator)

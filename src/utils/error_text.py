"""Çekirdeğin (client/server/güncelleme) ürettiği kullanıcıya dönük hata metinlerini arayüz diline çevirir.

Bu metinler Türkçe üretilir ve bir kısmı karşı cihaza da gider (alıcının hatası göndericinin ekranında
görünür). Ağ protokolüne dokunmamak için çeviri yalnızca GÖSTERİMDE yapılır: bir sözlük (tam eşleşme) ve
değişken parçalı metinler için kalıplar. Sözlükte karşılığı olmayan metin (ör. Windows'un kendi hata
metni) olduğu gibi, yani çevrilmeden gösterilir.

Yeni bir hata metni eklerken buraya da karşılığını ekleyin; `tests/test_error_text.py` çekirdekteki
sabit metinlerin hepsinin burada karşılığı olduğunu denetler.
"""

from __future__ import annotations

import re
from typing import Optional

# Tam eşleşmeler: Türkçe metin -> İngilizce
_EXACT_EN: dict[str, str] = {
    # client._user_error
    "Alıcı cihaz dosyayı kaydedemedi": "The receiving device could not save the file",
    "Alıcıdan tamamlanma onayı alınamadı. Dosya karşıya ulaşmış olabilir; lütfen alıcı cihazı kontrol edin.":
        "No completion confirmation from the receiver. The file may have arrived; please check the receiving device.",
    "Alıcı cihaz uyumsuz bir TransferTCP sürümü kullanıyor. İki cihazda da güncel sürüm olmalı.":
        "The receiving device runs an incompatible TransferTCP version. Both devices need the latest version.",
    "Bağlantı kesildi. Alıcı cihaz yanıt vermiyor.": "Connection lost. The receiving device is not responding.",
    "Zaman aşımı. Alıcı cihaz çok yavaş yanıt veriyor veya ağ bağlantısı kesildi.":
        "Timed out. The receiving device is responding too slowly or the network connection dropped.",
    "Alıcı cihaza bağlanılamadı: TransferTCP orada çalışmıyor veya bağlantı noktası kapalı.":
        "Could not connect to the receiving device: TransferTCP is not running there or the port is closed.",
    "Alıcı cihaza ulaşılamıyor. Aynı ağda olduğunuzdan emin olun.":
        "The receiving device is unreachable. Make sure you are on the same network.",
    "Alıcı cihaz bağlantıyı kapattı.": "The receiving device closed the connection.",
    "Dosyaya erişim engellendi (okuma izni yok veya başka bir program kilitledi).":
        "Access to the file was denied (no read permission, or another program has it locked).",
    "Zaman aşımı. Alıcı cihaz çok yavaş yanıt veriyor.": "Timed out. The receiving device is responding too slowly.",
    "Ağ bağlantısı koptu.": "The network connection was lost.",
    "Alıcı cihaz dosya bilgisini onaylamadı.": "The receiving device did not acknowledge the file information.",
    "Seçilen yol bir dosya değil. Lütfen bir dosya seçin.": "The selected path is not a file. Please choose a file.",
    "Dosya bulunamadı. Dosya silinmiş veya taşınmış olabilir.": "File not found. It may have been deleted or moved.",
    "Transfer alıcı cihaz tarafından reddedildi.": "The transfer was rejected by the receiving device.",
    "Alıcı cihazın kimliği değişti. Güvenilen cihazları temizleyip tekrar deneyin.":
        "The receiving device's identity changed. Clear the trusted devices and try again.",
    "Şifreli oturum kurulamadı. Her iki tarafta da TransferTCP güncel olmalı.":
        "Could not establish an encrypted session. TransferTCP must be up to date on both sides.",
    "Bağlantı kurulamadı. Alıcı cihazla iletişim sağlanamadı.":
        "Could not connect. Communication with the receiving device failed.",
    "Transfer alıcı tarafından iptal edildi": "The transfer was cancelled by the receiver",
    "El sıkışma yanıtı alınamadı": "No handshake response received",
    "Geçersiz el sıkışma yanıtı": "Invalid handshake response",
    "Dosya bilgisi yanıtı alınamadı (zaman aşımı veya bağlantı kapandı)":
        "No file information response (timed out or the connection closed)",
    "Geçersiz dosya bilgisi yanıtı": "Invalid file information response",
    "Ağ bağlantısı koptu": "The network connection was lost",
    # server._format_receiver_error / _validate_file_info / _claim_part
    "Dosya bütünlüğü doğrulanamadı (SHA-256 uyuşmuyor); dosya silindi, lütfen tekrar gönderin.":
        "File integrity could not be verified (SHA-256 mismatch); the file was deleted, please send it again.",
    "Diskte yeterli boş alan yok.": "Not enough free disk space.",
    "Dosya başka bir program (veya antivirüs) tarafından kilitlendi.":
        "The file is locked by another program (or antivirus).",
    "Erişim engellendi (Yazma yetkisi yok).": "Access denied (no write permission).",
    "Dosya adı veya yolu bu sistemde geçersiz.": "The file name or path is not valid on this system.",
    "Hedef klasör bulunamadı veya erişilemiyor.": "The destination folder was not found or is inaccessible.",
    "Ağ bağlantısı koptu (Gönderici bağlantıyı kesti).": "The network connection was lost (the sender disconnected).",
    "Zaman aşımı. Gönderici cihazdan yanıt alınamadı.": "Timed out. No response from the sending device.",
    "Hedef dosya kilitli (başka bir program açık tutuyor olabilir).":
        "The target file is locked (another program may be holding it open).",
    "Geçersiz transfer kimliği.": "Invalid transfer ID.",
    "Geçersiz dosya adı.": "Invalid file name.",
    "Geçersiz dosya boyutu.": "Invalid file size.",
    "Geçersiz dosya boyutu (negatif veya izin verilen üst sınırı aşıyor).":
        "Invalid file size (negative or above the allowed limit).",
    "Bu dosya şu anda başka bir transferde alınıyor; biraz sonra tekrar deneyin.":
        "This file is currently being received in another transfer; try again in a moment.",
    "Gönderici tamamlanma bildirimini göndermedi (bağlantı koptu)":
        "The sender did not send the completion notice (connection lost)",
    "Benzersiz dosya adı üretilemedi (hedef kilitli olabilir)":
        "Could not generate a unique file name (the target may be locked)",
    # transfer / netio
    "Bilinmeyen hata": "Unknown error",
    "Bağlantı kapandı": "Connection closed",
    # güncelleme (update_policy / update_installer)
    "Geçersiz güncelleme adresi.": "Invalid update address.",
    "Güncelleme adresinde kimlik bilgisi olamaz.": "The update address must not contain credentials.",
    "Güncelleme yalnızca HTTPS ile indirilebilir.": "Updates can only be downloaded over HTTPS.",
    "Güncelleme adresi beklenmeyen bir port kullanıyor.": "The update address uses an unexpected port.",
    "Sunucunun verdiği sağlama toplamı geçersiz biçimde.": "The checksum given by the server is malformed.",
    "Güncelleme boyutu izin verilen sınırı aşıyor.": "The update size exceeds the allowed limit.",
    "İndirme eksik kaldı (boyut uyuşmuyor).": "The download is incomplete (size mismatch).",
    "İndirilen dosyanın boyutu beklenenle uyuşmuyor.": "The downloaded file's size does not match the expected size.",
    "İndirilen dosya boş.": "The downloaded file is empty.",
    "Dosya bütünlüğü doğrulanamadı (checksum).": "File integrity could not be verified (checksum).",
    # güncelleme kurulumu (self_update / update_installer.install_update)
    "Güncelleme dosyası bulunamadı.": "The update file was not found.",
    "Otomatik kurulum yalnızca Windows'ta var. İndirilen dosyayı uygulama klasörüyle değiştirin.":
        "Automatic installation is only available on Windows. Replace the app folder with the downloaded file.",
    "İndirilen dosya bir exe ya da zip değil": "The downloaded file is neither an exe nor a zip",
    "Paket izin verilen boyuttan büyük": "The package exceeds the allowed size",
    "Pakette uygulamanın exe dosyası yok": "The package does not contain the application's exe",
    "Paketteki dosya geçerli bir Windows uygulaması değil": "The file in the package is not a valid Windows application",
}

# Değişken parçalı metinler: (kalıp, İngilizce şablon, içinde yine çevrilecek grup adı ya da None)
_PATTERNS_EN: list[tuple[str, str, Optional[str]]] = [
    (r"^Alıcı cihaz hatası: (?P<x>.+)$", "Receiver error: {x}", "x"),
    (r"^Alıcı cihaz dosyayı kaydedemedi: (?P<x>.+)$", "The receiving device could not save the file: {x}", "x"),
    (r"^Diskte yeterli boş alan yok \(gerekli: (?P<need>.+?), boş: (?P<free>.+?)\)\.$",
     "Not enough free disk space (needed: {need}, free: {free}).", None),
    (r"^Geçersiz alan: (?P<x>.+?)\.$", "Invalid field: {x}.", None),
    (r"^Diske yazma hatası: (?P<x>.+)$", "Disk write error: {x}", None),
    (r"^Dosya alınamadı: (?P<x>.+)$", "Could not receive the file: {x}", "x"),
    (r"^Transfer başarısız: (?P<x>.+)$", "Transfer failed: {x}", "x"),
    (r"^Eksik transfer: (?P<a>\d+)/(?P<b>\d+) byte alındı$", "Incomplete transfer: {a}/{b} bytes received", None),
    (r"^Gönderici bildirilen boyuttan fazla veri gönderdi \((?P<a>\d+) > (?P<b>\d+)\)$",
     "The sender sent more data than declared ({a} > {b})", None),
    (r"^Dosya klasörü oluşturulamadı: (?P<x>.+)$", "Could not create the file folder: {x}", None),
    (r"^Dosya bulunamadı: (?P<x>.+)$", "File not found: {x}", None),
    (r"^Yol bir dosya değil: (?P<x>.+)$", "Path is not a file: {x}", None),
    (r"^Parça onayı alınamadı \(parça (?P<a>\d+)/(?P<b>\d+)\)$",
     "No chunk acknowledgement received (chunk {a}/{b})", None),
    (r"^Parça onayı için zaman aşımı \(parça (?P<a>\d+)/(?P<b>\d+)\)$",
     "Timed out waiting for the chunk acknowledgement (chunk {a}/{b})", None),
    (r"^Geçersiz yanıt türü: (?P<x>.+)$", "Invalid response type: {x}", None),
    (r"^Dosya beklenenden kısa: (?P<p>.+) \((?P<a>\d+)/(?P<b>\d+) bayt\)$",
     "File shorter than expected: {p} ({a}/{b} bytes)", None),
    (r"^Güncelleme adresi güvenilen bir sunucuya ait değil \((?P<x>.+)\)\.$",
     "The update address does not belong to a trusted server ({x}).", None),
    (r"^Yönlendirme reddedildi: (?P<x>.+)$", "Redirect refused: {x}", None),
    (r"^Paket okunamadı: (?P<x>.+)$", "The package could not be read: {x}", None),
    (r"^Zip dosyası bozuk: (?P<x>.+)$", "The zip file is corrupt: {x}", None),
    (r"^Yeni sürüm uygulamanın klasörüne yazılamadı: (?P<x>.+)$",
     "The new version could not be written to the app's folder: {x}", None),
    (r"^Paket başka bir işlemci mimarisi için hazırlanmış \((?P<a>.+?), bu bilgisayar (?P<b>[^,()]+?)\)$",
     "The package was built for a different processor architecture ({a}, this computer {b})", None),
    (r"^Uygulamanın bulunduğu klasöre yazılamıyor \((?P<folder>.+)\): (?P<x>.+)$",
     "Cannot write to the folder the app is in ({folder}): {x}", None),
    (r"^Çalışan uygulama dosyası değiştirilemedi: (?P<x>.+)$", "The running application file could not be replaced: {x}", None),
    (r"^Yeni sürüm yerine konamadı: (?P<x>.+)$", "The new version could not be put in place: {x}", None),
    (r"^Yeni sürüm başlatılamadı: (?P<x>.+)$", "The new version could not be started: {x}", None),
]

_COMPILED = [(re.compile(pattern, re.DOTALL), template, nested) for pattern, template, nested in _PATTERNS_EN]


def _to_english(text: str, depth: int = 0) -> str:
    stripped = text.strip()
    exact = _EXACT_EN.get(stripped)
    if exact is not None:
        return exact
    if depth < 3:
        for pattern, template, nested in _COMPILED:
            match = pattern.match(stripped)
            if match is None:
                continue
            parts = match.groupdict()
            if nested:
                parts[nested] = _to_english(parts[nested], depth + 1)
            return template.format(**parts)
    return text


def localize_error(text: Optional[str], lang: Optional[str] = None) -> str:
    """`text` Türkçe çekirdek metniyse `lang` diline çevirir; karşılığı yoksa metni olduğu gibi döndürür.

    `lang` verilmezse uygulamada seçili dil kullanılır.
    """
    if not text:
        return text or ""
    if lang is None:
        from .locales import configured_language

        lang = configured_language()
    if lang == "tr":
        return text
    return _to_english(text)

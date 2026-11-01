"""Renk tonlu etiketler (durum satirlari, ipuclari): renk koda degil temaya (QLabel[tone=...]) aittir.

Eskiden etiketlere sabit ``color: #888`` / ``#666`` / ``#FF9800`` yaziliyordu: koyu temada soluk (2,5:1),
acik temada turuncu/yesil/mavi okunmaz (2-3:1) kaliyordu ve tema degisince guncellenmiyordu.
"""

from PyQt6.QtWidgets import QLabel

TONES = ("body", "muted", "ok", "err", "warn", "info")


def set_tone(label: QLabel, tone: str) -> None:
    if tone not in TONES:
        raise ValueError(f"unknown tone: {tone}")
    if label.property("tone") == tone:
        return
    label.setProperty("tone", tone)
    style = label.style()
    style.unpolish(label)
    style.polish(label)

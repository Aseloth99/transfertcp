"""Kart (setItemWidget) listesi: liste daralıp genişleyince kartlar da yeni genişliğe oturur."""

from PyQt6.QtWidgets import QListWidget


class CardListWidget(QListWidget):
    """Qt'nin Adjust kipi yukarıdan aşağı akan listeyi yalnızca yükseklik değişince yeniden yerleştirir;
    pencere yalnızca daraltılınca kartlar eski genişlikte kalıp sağdan kesiliyordu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.doItemsLayout()

"""Image editor data and geometry rules, independent of widgets."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainterPath, QTransform


class Interpolation(StrEnum):
    NEAREST = "nearest"
    BILINEAR = "bilinear"
    BICUBIC = "bicubic"
    LANCZOS = "lanczos"
    BOX = "box"
    HAMMING = "hamming"
    MKS2021 = "mks2021"
    AREA = "area"


def default_font() -> QFont:
    font = QFont()
    font.setPixelSize(48)
    return font


@dataclass
class ThumbnailLayerData:
    image: QImage
    text: str | None = None
    font: QFont = field(default_factory=default_font)
    color: QColor = field(default_factory=lambda: QColor("white"))
    outline: QColor = field(default_factory=lambda: QColor("black"))
    outline_width: float = 2.0
    interpolation: Interpolation = Interpolation.LANCZOS
    raster_key: tuple[int, int, int, Interpolation] | None = field(default=None, repr=False)
    raster: QImage = field(default_factory=QImage, repr=False)
    transform: QTransform = field(default_factory=QTransform)
    opacity: float = 1.0

    def text_path(self) -> QPainterPath:
        path = QPainterPath()
        if self.text is not None:
            path.addText(0, 0, self.font, self.text)
            bounds = path.boundingRect()
            path.translate(-bounds.left(), -bounds.top())
        return path

    def content_rect(self) -> QRectF:
        if self.text is None:
            return QRectF(self.image.rect())
        return self.text_path().boundingRect().adjusted(
            -self.outline_width, -self.outline_width, self.outline_width, self.outline_width)


def canvas_size(width: int, height: int) -> tuple[int, int]:
    return max(1, min(4096, width)), max(1, min(4096, height))


def resize_factors(dimension: float, value: float, axis: str, locked: bool) -> tuple[float, float]:
    if dimension <= 0:
        return 1.0, 1.0
    factor = value / dimension
    return (factor if axis == "width" or locked else 1.0,
            factor if axis == "height" or locked else 1.0)


def alignment_offset(frame: QRectF, bounds: QRectF, axis: str, fraction: float) -> float:
    if axis == "x":
        return frame.left() + (frame.width() - bounds.width()) * fraction - bounds.left()
    return frame.top() + (frame.height() - bounds.height()) * fraction - bounds.top()


def linked_dimensions(width: int, height: int, axis: str, value: int) -> tuple[int, int]:
    ratio = width / height
    linked = max(1, round(value / ratio if axis == "width" else value * ratio))
    if linked > 4096:
        linked = 4096
        value = max(1, round(linked * ratio if axis == "width" else linked / ratio))
    return (value, linked) if axis == "width" else (linked, value)


def normalized_rotation(angle: float) -> float:
    return angle % 360 if not -360 <= angle <= 360 else angle


def corner_resize_factors(delta: QPointF, start: QPointF, locked: bool) -> tuple[float, float]:
    sx = max(.01, abs(delta.x()) / max(.01, abs(start.x())))
    sy = max(.01, abs(delta.y()) / max(.01, abs(start.y())))
    return (max(sx, sy), max(sx, sy)) if locked else (sx, sy)


def canvas_resize_preview(rect: QRectF, handle: tuple[int, int], point: QPointF,
                          offset: QPointF, locked: bool) -> QRectF:
    hx, hy = handle
    width = rect.right() - point.x() if hx < 0 else point.x() - rect.left() if hx > 0 else rect.width()
    height = rect.bottom() - point.y() if hy < 0 else point.y() - rect.top() if hy > 0 else rect.height()
    width, height = max(1., min(4096., width)), max(1., min(4096., height))
    if locked:
        factor = height / rect.height() if hx == 0 else width / rect.width() if hy == 0 else max(
            width / rect.width(), height / rect.height())
        factor = min(factor, 4096 / rect.width(), 4096 / rect.height())
        width, height = rect.width() * factor, rect.height() * factor
    left = rect.right() - width if hx < 0 else rect.left() if hx > 0 else rect.center().x() - width / 2
    top = rect.bottom() - height if hy < 0 else rect.top() if hy > 0 else rect.center().y() - height / 2
    origin = offset + rect.topLeft() - QPointF(left, top)
    return QRectF(origin.x(), origin.y(), round(width), round(height))

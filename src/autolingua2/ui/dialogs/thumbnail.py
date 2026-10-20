from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFontComboBox, QGraphicsItem,
    QGraphicsObject, QGraphicsScene, QGraphicsView,
    QGroupBox, QHBoxLayout, QLayout, QLineEdit, QListWidget, QMessageBox, QPushButton, QSplitter, QStackedWidget,
    QSpinBox, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from autolingua2.ui.ui_loader import load_ui, require_child
from autolingua2.ui.main.page_scrubber import RangeScrubberWidget
from autolingua2.core.thumbnail import (
    Interpolation, ThumbnailLayerData, alignment_offset, canvas_resize_preview, canvas_size,
    corner_resize_factors, linked_dimensions, normalized_rotation, resize_factors,
)
from autolingua2.services.projects.thumbnail_editor import (
    compose_thumbnail, load_layer_image, paint_layer, readable_image_extensions, thumbnail_result,
)


class TwoStageTooltips(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.target = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.show_details)
        for widget in parent.findChildren(QWidget):
            if widget.toolTip():
                widget.installEventFilter(self)

    def dismiss(self):
        self.timer.stop()
        self.target = None
        QToolTip.hideText()

    def show_details(self):
        if self.target is not None and self.target.isVisible():
            QToolTip.showText(self.position, self.target.toolTip(), self.target, msecShowTime=15000)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            description = watched.toolTip()
            short = description.split("\n", 1)[0].split("：", 1)[0]
            self.timer.stop()
            self.target = watched
            self.position = event.globalPos()
            QToolTip.showText(self.position, short, watched, msecShowTime=15000)
            if short != description:
                self.timer.start()
            return True
        if watched is self.target and event.type() in (
                QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.MouseButtonPress,
                QEvent.Type.FocusOut, QEvent.Type.Close):
            self.dismiss()
        return super().eventFilter(watched, event)


class FlowLayout(QLayout):
    """Place buttons left to right, wrapping when the available width is filled."""

    def __init__(self):
        super().__init__()
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < self.count() else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < self.count() else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self):
        if not self._items:
            return QSize(0, 0)
        return QSize(sum(item.sizeHint().width() for item in self._items)
                     + self.spacing() * (len(self._items) - 1),
                     max(item.sizeHint().height() for item in self._items))

    def minimumSize(self):
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def _arrange(self, rect, *, apply):
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            size = item.sizeHint()
            if x > rect.x() and x + size.width() > rect.x() + rect.width():
                x = rect.x()
                y += row_height + self.spacing()
                row_height = 0
            if apply:
                item.setGeometry(QRect(x, y, size.width(), size.height()))
            x += size.width() + self.spacing()
            row_height = max(row_height, size.height())
        return y + row_height - rect.y()


class ThumbnailLayer(QGraphicsObject):
    """A movable layer with proportional resizing from any corner."""

    def __init__(self, pixmap: QPixmap, changed, text: str | None = None):
        super().__init__()
        self.model = ThumbnailLayerData(pixmap.toImage(), text)
        self.name = ""
        self.changed = changed
        self.resizing = False
        self.resize_mode = False
        self.lock_ratio = True
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.refresh_text()

    def refresh_text(self):
        self.prepareGeometryChange()
        self.update()

    def content_rect(self):
        return self.model.content_rect()

    def boundingRect(self):
        return self.content_rect().adjusted(-6, -6, 6, 6)

    def paint(self, painter, option, widget=None):
        paint_layer(painter, self.model)
        if self.isSelected():
            pen = QPen(QColor("#308cff"), 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rect = self.content_rect()
            painter.drawRect(rect)
            if self.resize_mode:
                painter.setBrush(QColor("white"))
                for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                    painter.drawRect(QRectF(corner.x() - 4, corner.y() - 4, 8, 8))

    def mousePressEvent(self, event):
        rect = self.content_rect()
        corners = (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())
        corner = min(corners, key=lambda p: (event.pos() - p).manhattanLength())
        self.resizing = (self.resize_mode and self.isSelected()
                         and (event.pos() - corner).manhattanLength() < 18)
        if self.resizing:
            self.resize_center = rect.center()
            self.resize_origin = self.mapToScene(rect.center())
            self.resize_start = self.mapFromScene(event.scenePos()) - rect.center()
            self.resize_transform = QTransform(self.transform())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.resizing:
            inverse, _ = self.resize_transform.inverted()
            # Use the press-time transform so repeated move events do not compound scaling.
            rotation = QTransform().rotate(-self.rotation())
            delta = inverse.map(rotation.map(event.scenePos() - self.resize_origin))
            sx, sy = corner_resize_factors(delta, self.resize_start, self.lock_ratio)
            self.setTransform(QTransform(self.resize_transform).scale(sx, sy))
            self.setPos(self.pos() + self.resize_origin - self.mapToScene(self.resize_center))
            self.changed()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.resizing = False
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.changed()
        return result


class ThumbnailView(QGraphicsView):
    zoomChanged = Signal(float)
    textRequested = Signal(QPointF)
    textEditRequested = Signal(object)
    cropChanged = Signal(bool)
    imageSizePreview = Signal(int, int)
    imageResizeCancelled = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.crop_start = None
        self.crop_item = None
        self.crop_mode = False
        self.tool = "move"
        self.fit_mode = True
        self.space_pressed = False
        self.pan_start = None
        self.image_resize_handle = None
        self.image_move_start = None
        self.image_resize_preview = None
        self.image_ratio_locked = True
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setBackgroundBrush(QColor("#353535"))
        self.checker = QPixmap(16, 16)
        self.checker.fill(QColor("#eeeeee"))
        painter = QPainter(self.checker)
        painter.fillRect(0, 0, 8, 8, QColor("#cccccc"))
        painter.fillRect(8, 8, 8, 8, QColor("#cccccc"))
        painter.end()
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        canvas = self.scene().sceneRect()
        if self.tool == "image_size" and self.image_resize_preview is not None:
            canvas = canvas.translated(self.image_resize_preview.topLeft())
        painter.drawTiledPixmap(rect.intersected(canvas), self.checker)

    def canvas_preview_frame(self):
        frame = QRectF(self.image_resize_preview or self.scene().sceneRect())
        frame.moveTopLeft(self.scene().sceneRect().topLeft())
        return frame

    @staticmethod
    def image_handles(rect):
        return [((x, y), QPointF(rect.center().x() + x * rect.width() / 2,
                                 rect.center().y() + y * rect.height() / 2))
                for x, y in ((-1, -1), (0, -1), (1, -1), (1, 0),
                             (1, 1), (0, 1), (-1, 1), (-1, 0))]

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.tool != "image_size":
            return
        frame = self.canvas_preview_frame()
        pen = QPen(QColor("#ffad33"), 1)
        pen.setCosmetic(True)
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        original_pen = QPen(QColor("#39c5ff"), 2, Qt.PenStyle.DashLine)
        original_pen.setCosmetic(True)
        painter.setPen(original_pen)
        original = self.scene().sceneRect()
        if self.image_resize_preview is not None:
            original = original.translated(self.image_resize_preview.topLeft())
        painter.drawRect(original)
        painter.setPen(pen)
        painter.drawRect(frame)
        painter.resetTransform()
        painter.setBrush(QColor("#ffad33"))
        for _, point in self.image_handles(frame):
            screen = self.mapFromScene(point)
            painter.drawEllipse(QRectF(screen.x() - 4, screen.y() - 4, 8, 8))
        painter.restore()

    def cancel_image_resize(self):
        self.image_resize_handle = None
        self.image_move_start = None
        self.image_resize_preview = None
        self.imageResizeCancelled.emit()
        self.viewport().update()

    def preview_image_resize(self, point):
        if self.image_resize_handle is None:
            return
        self.image_resize_preview = canvas_resize_preview(
            self.image_resize_source, self.image_resize_handle, point,
            self.image_resize_offset, self.image_ratio_locked)
        self.imageSizePreview.emit(round(self.image_resize_preview.width()),
                                   round(self.image_resize_preview.height()))
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_canvas()

    def fit_canvas(self):
        self.fit_mode = True
        rect = self.scene().sceneRect()
        self.setSceneRect(rect.adjusted(-rect.width(), -rect.height(), rect.width(), rect.height()))
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit(self.transform().m11() * 100)

    def set_zoom(self, percent, anchor=None):
        self.fit_mode = False
        percent = max(5., min(1600., percent))
        point = anchor if anchor is not None else self.viewport().rect().center()
        before = self.mapToScene(point)
        self.setTransform(QTransform.fromScale(percent / 100, percent / 100))
        after = self.mapToScene(point)
        self.centerOn(self.mapToScene(self.viewport().rect().center()) + before - after)
        self.zoomChanged.emit(percent)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.transform().m11() * 100 * 1.2 ** (event.angleDelta().y() / 120),
                          event.position().toPoint())
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape and (
                self.image_resize_handle is not None or self.image_move_start is not None):
            self.cancel_image_resize()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape and self.crop_mode:
            self.cancel_crop()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_pressed = False
            self.pan_start = None
            self.update_cursor()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space_pressed = False
        self.pan_start = None
        self.update_cursor()
        super().focusOutEvent(event)

    @staticmethod
    def resize_cursor(hx, hy):
        if hx == 0:
            return Qt.CursorShape.SizeVerCursor
        if hy == 0:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeFDiagCursor if hx == hy else Qt.CursorShape.SizeBDiagCursor

    def update_cursor(self, position=None):
        position = position if position is not None else self.viewport().mapFromGlobal(QCursor.pos())
        cursor = Qt.CursorShape.ArrowCursor
        if self.pan_start is not None or self.image_move_start is not None:
            cursor = Qt.CursorShape.ClosedHandCursor
        elif self.space_pressed:
            cursor = Qt.CursorShape.OpenHandCursor
        elif self.image_resize_handle is not None:
            cursor = self.resize_cursor(*self.image_resize_handle)
        elif self.tool == "image_size":
            frame = self.canvas_preview_frame()
            for handle, point in self.image_handles(frame):
                if (self.mapFromScene(point) - position).manhattanLength() <= 10:
                    cursor = self.resize_cursor(*handle)
                    break
            else:
                if frame.contains(self.mapToScene(position)):
                    cursor = Qt.CursorShape.OpenHandCursor
        elif self.tool == "crop":
            cursor = Qt.CursorShape.CrossCursor
        elif self.tool == "text":
            cursor = Qt.CursorShape.IBeamCursor
        else:
            item = self.itemAt(position)
            if self.tool == "move" and isinstance(item, ThumbnailLayer):
                cursor = (Qt.CursorShape.ClosedHandCursor if self.scene().mouseGrabberItem() is item
                          else Qt.CursorShape.OpenHandCursor)
            elif self.tool == "scale":
                for layer in self.scene().selectedItems():
                    if not isinstance(layer, ThumbnailLayer):
                        continue
                    rect = layer.content_rect()
                    for hx, hy, corner in ((-1, -1, rect.topLeft()), (1, -1, rect.topRight()),
                                           (-1, 1, rect.bottomLeft()), (1, 1, rect.bottomRight())):
                        point = layer.mapFromScene(self.mapToScene(position))
                        if (point - corner).manhattanLength() < 18:
                            cursor = self.resize_cursor(hx, hy)
        self.setCursor(cursor)

    def cancel_crop(self):
        if self.crop_item is not None:
            self.scene().removeItem(self.crop_item)
        self.crop_item = None
        self.crop_start = None
        self.cropChanged.emit(False)

    def commit_crop(self):
        if self.crop_item is None:
            return
        rect = self.crop_item.rect()
        if rect.width() < 4 or rect.height() < 4:
            return
        self.cancel_crop()
        self.scene().setSceneRect(rect)
        self.fit_canvas()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (
                self.space_pressed and event.button() == Qt.MouseButton.LeftButton):
            self.pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif self.tool == "image_size" and event.button() == Qt.MouseButton.LeftButton:
            frame = self.canvas_preview_frame()
            for handle, point in self.image_handles(frame):
                if (self.mapFromScene(point) - event.position().toPoint()).manhattanLength() <= 10:
                    self.image_resize_handle = handle
                    offset = (self.image_resize_preview.topLeft()
                              if self.image_resize_preview is not None else QPointF())
                    self.image_resize_source = QRectF(frame)
                    self.image_resize_offset = offset
                    break
            else:
                point = self.mapToScene(event.position().toPoint())
                if frame.contains(point):
                    self.image_move_start = point
                    self.image_resize_source = QRectF(
                        self.image_resize_preview or QRectF(QPointF(), frame.size()))
                    self.image_resize_preview = QRectF(self.image_resize_source)
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif self.tool == "text" and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, ThumbnailLayer) and item.model.text is not None:
                self.scene().clearSelection()
                item.setSelected(True)
                self.textEditRequested.emit(item)
            elif self.scene().sceneRect().contains(point):
                self.textRequested.emit(point)
            event.accept()
        elif self.crop_mode and event.button() == Qt.MouseButton.LeftButton:
            self.cancel_crop()
            self.crop_start = self.mapToScene(event.position().toPoint())
            self.crop_item = self.scene().addRect(QRectF(), QPen(QColor("#308cff"), 2))
            self.crop_item.setZValue(100000)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.update_cursor(event.position().toPoint())
        if self.pan_start is not None:
            delta = event.position().toPoint() - self.pan_start
            self.pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
        elif self.image_move_start is not None:
            delta = self.mapToScene(event.position().toPoint()) - self.image_move_start
            frame = QRectF(self.image_resize_source)
            frame.moveTo(max(-100000, min(100000, round(frame.x() + delta.x()))),
                         max(-100000, min(100000, round(frame.y() + delta.y()))))
            self.image_resize_preview = frame
            self.imageSizePreview.emit(round(frame.width()), round(frame.height()))
            self.viewport().update()
            event.accept()
        elif self.image_resize_handle is not None:
            self.preview_image_resize(self.mapToScene(event.position().toPoint()))
            event.accept()
        elif self.crop_start is not None:
            if self.crop_item is None:
                raise RuntimeError("切り抜き範囲が初期化されていません")
            rect = QRectF(self.crop_start, self.mapToScene(event.position().toPoint())).normalized()
            self.crop_item.setRect(rect.intersected(self.scene().sceneRect()))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.pan_start is not None:
            self.pan_start = None
            self.update_cursor()
            event.accept()
        elif self.image_move_start is not None:
            self.image_move_start = None
            self.update_cursor()
            event.accept()
        elif self.image_resize_handle is not None:
            if self.image_resize_preview is None:
                raise RuntimeError("キャンバスサイズ変更のプレビューが初期化されていません")
            size = self.image_resize_preview.size().toSize()
            self.image_resize_handle = None
            self.imageSizePreview.emit(max(1, size.width()), max(1, size.height()))
            event.accept()
        elif self.crop_start is not None:
            if self.crop_item is None:
                raise RuntimeError("切り抜き範囲が初期化されていません")
            rect = self.crop_item.rect()
            self.crop_start = None
            self.cropChanged.emit(rect.width() >= 4 and rect.height() >= 4)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        self.update_cursor(event.position().toPoint())

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if self.tool == "text" and isinstance(item, ThumbnailLayer) and item.model.text is not None:
            self.scene().clearSelection()
            item.setSelected(True)
            self.textEditRequested.emit(item)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class ThumbnailDialog(QDialog):
    def __init__(self, pixmap: QPixmap, parent=None, *, icon_manager=None):
        super().__init__(parent)
        loaded = load_ui("dialogs/ThumbnailDialog.ui")
        if not isinstance(loaded, QDialog):
            raise TypeError("ThumbnailDialog.ui は QDialog ではありません")
        self.setWindowTitle(loaded.windowTitle())
        self.resize(loaded.size())
        loaded.setWindowFlags(Qt.WindowType.Widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(loaded)
        self.editor_form = loaded
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        for button in self.findChildren(QToolButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.original = QPixmap(pixmap)
        self.layers: list[ThumbnailLayer] = []
        self.syncing = False
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(QRectF(pixmap.rect()))
        self.view = ThumbnailView(self.scene)
        require_child(self, QVBoxLayout, "layoutPreview").addWidget(self.view)
        self.text = require_child(self, QLineEdit, "editText")
        self.font_input = require_child(self, QFontComboBox, "comboFont")
        self.font_size = require_child(self, QDoubleSpinBox, "spinFontSize")
        self.outline_width = require_child(self, QDoubleSpinBox, "spinOutline")
        self.width_input = require_child(self, QDoubleSpinBox, "spinWidth")
        self.height_input = require_child(self, QDoubleSpinBox, "spinHeight")
        self.rotation_input = require_child(self, QDoubleSpinBox, "spinRotation")
        self.ratio_lock = require_child(self, QCheckBox, "checkRatio")
        self.image_width = require_child(self, QSpinBox, "spinImageWidth")
        self.image_height = require_child(self, QSpinBox, "spinImageHeight")
        self.image_x = require_child(self, QSpinBox, "spinImageX")
        self.image_y = require_child(self, QSpinBox, "spinImageY")
        self.image_ratio = require_child(self, QCheckBox, "checkImageRatio")
        self.interpolation = require_child(self, QComboBox, "comboInterpolation")
        for control, description in (
            (self.image_width, "変更後のキャンバスの幅"),
            (self.image_height, "変更後のキャンバスの高さ"),
            (self.image_x, "元キャンバスと全レイヤーを水平に移動して左右の余白を調整"),
            (self.image_y, "元キャンバスと全レイヤーを垂直に移動して上下の余白を調整"),
            (self.width_input, "選択レイヤーの幅"),
            (self.height_input, "選択レイヤーの高さ"),
            (self.interpolation, "補間方式\n最近傍法：ドット絵向け。バイリニア：軽量。バイキュービック：滑らか。\nLanczos：細部を保持。BOX：平均化。HAMMING：輪郭を保った縮小。\nMKS2021：シャープさを調整。面積平均：縮小時のモアレを抑制"),
        ):
            control.setToolTip(description)
        self.view_zoom = require_child(self, QDoubleSpinBox, "spinViewZoom")
        self.x_input = require_child(self, QDoubleSpinBox, "spinX")
        self.y_input = require_child(self, QDoubleSpinBox, "spinY")
        opacity_host = require_child(self, QGroupBox, "layersGroup")
        self.opacity = RangeScrubberWidget(
            opacity_host, text_alignment="right", min_value=0, max_value=100,
            format_text=lambda value, maximum: f"{value}%",
        )
        self.opacity.setObjectName("opacityScrubber")
        self.opacity.setAccessibleName("選択レイヤーの不透明度")
        require_child(self, QLayout, "opacityScrubberLayout").addWidget(self.opacity)
        for name, delta in (("buttonOpacityMinus", -1), ("buttonOpacityPlus", 1)):
            button = require_child(self, QToolButton, name)
            button.setFixedSize(26, 26)
            button.clicked.connect(
                lambda checked=False, step=delta: self.set_opacity(self.opacity.current_page + step))
        self.opacity.value_changed.connect(self.set_opacity)
        self.layer_list = require_child(self, QListWidget, "listLayers")
        self.text_settings = require_child(self, QGroupBox, "textSettings")
        self.scale_settings = require_child(self, QWidget, "scaleOptions")
        self.rotation_settings = require_child(self, QWidget, "rotationOptions")
        self.tool_settings = require_child(self, QGroupBox, "toolSettings")
        self.tool_stack = require_child(self, QStackedWidget, "toolSettingsStack")
        self.tool_pages = {
            tool: require_child(self, QWidget, name)
            for tool, name in (
                ("move", "moveOptions"), ("scale", "scaleOptions"),
                ("rotate", "rotationOptions"), ("align", "alignmentOptions"),
                ("crop", "cropOptions"), ("text", "textOptions"),
                ("image_size", "imageSizeOptions"),
            )
        }
        splitter = require_child(self, QSplitter, "editorSplitter")
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([48, 842, 290])
        inspector = require_child(self, QSplitter, "inspectorSplitter")
        inspector.setStretchFactor(0, 1)
        inspector.setStretchFactor(1, 1)
        require_child(self, QVBoxLayout, "layoutMain").setStretch(0, 1)
        callbacks = {
            "buttonRotateLeft": lambda: self.rotate(-90),
            "buttonRotateRight": lambda: self.rotate(90),
            "buttonReset": self.reset,
            "buttonCommitCrop": self.commit_crop,
            "buttonCancelCrop": self.cancel_crop,
            "buttonApplyImageSize": lambda: self.resize_image(
                self.image_width.value(), self.image_height.value()),
            "buttonZoomOut": lambda: self.view.set_zoom(self.view.transform().m11() * 100 / 1.2),
            "buttonZoomIn": lambda: self.view.set_zoom(self.view.transform().m11() * 100 * 1.2),
            "buttonFit": self.view.fit_canvas,
            "buttonTextColor": lambda: self.choose_color("color"),
            "buttonOutlineColor": lambda: self.choose_color("outline"),
            "buttonAddImage": self.add_image,
            "buttonLayerUp": lambda: self.reorder(-1),
            "buttonLayerDown": lambda: self.reorder(1),
            "buttonRemoveLayer": self.remove_layer,
            "buttonApply": self.accept,
            "buttonCancel": self.reject,
        }
        for name, callback in callbacks.items():
            require_child(self, QPushButton, name).clicked.connect(callback)
        for name, icon_name, description in (
            ("buttonMove", "move", "移動：選択レイヤーの位置を変更"),
            ("buttonScale", "scale", "拡大縮小：選択レイヤーの幅・高さと補間方式を設定"),
            ("buttonImageSize", "canvas-size", "キャンバスのサイズ変更\nオレンジの枠：変更後の範囲。青の破線：元キャンバス。\n枠内のドラッグで元キャンバスと全レイヤーを移動し、ハンドルでサイズ変更。\n「サイズ変更を適用」で確定"),
            ("buttonRotate", "rotate", "回転：選択レイヤーの角度を変更"),
            ("buttonAlign", "align-center-horizontal", "整列：選択レイヤーをキャンバスに合わせて配置"),
            ("buttonText", "text-add", "文字：キャンバスをクリックして追加・編集"),
            ("buttonAddImage", "image-add", "画像を追加"),
            ("buttonCrop", "crop", "切り抜き：指定範囲でキャンバスを切り抜く"),
            ("buttonRotateLeft", "rotate-left-90", "左に90度回転"),
            ("buttonRotateRight", "rotate-right-90", "右に90度回転"),
            ("buttonReset", "undo-2", "元画像に戻す（加工をすべて解除）"),
            ("buttonLayerUp", "arrow-up", "重なり順を上へ"),
            ("buttonLayerDown", "arrow-down", "重なり順を下へ"),
            ("buttonRemoveLayer", "trash", "削除"),
        ):
            button = require_child(self, QPushButton, name)
            button.setToolTip(description)
            button.setAccessibleName(description)
            if icon_manager is not None:
                icon = icon_manager.get_icon(icon_name)
                if not icon.isNull():
                    button.setIcon(icon)
                    button.setIconSize(QSize(24, 24))
                    button.setText("")
        tools_layout = require_child(self, QVBoxLayout, "layoutTools")
        for name in (
            "buttonMove", "buttonScale", "buttonRotate", "buttonAlign",
            "buttonCrop", "buttonText", "buttonAddImage", "buttonReset", "buttonImageSize",
        ):
            button = require_child(self, QPushButton, name)
            button.setFixedSize(36, 36)
            tools_layout.setAlignment(button, Qt.AlignmentFlag.AlignHCenter)
        self.action_flows = {}
        for host_name, layout_name in (
            ("rotationActions", "rotationActionsLayout"),
            ("alignmentOptions", "alignmentActionsLayout"),
        ):
            source = require_child(self, QHBoxLayout, layout_name)
            flow = FlowLayout()
            while source.count():
                flow.addItem(source.takeAt(0))
            source.addLayout(flow)
            self.action_flows[host_name] = flow
            require_child(self, QWidget, host_name).installEventFilter(self)
        for suffix, icon_name, axis, fraction in (
            ("Left", "align-left", "x", 0),
            ("CenterHorizontal", "align-center-horizontal", "x", .5),
            ("Right", "align-right", "x", 1),
            ("Top", "align-top", "y", 0),
            ("CenterVertical", "align-center-vertical", "y", .5),
            ("Bottom", "align-bottom", "y", 1),
        ):
            button = require_child(self, QToolButton, "buttonAlign" + suffix)
            button.clicked.connect(lambda checked=False, a=axis, f=fraction: self.align_layer(a, f))
            if icon_manager is not None:
                icon = icon_manager.get_icon(icon_name)
                if not icon.isNull():
                    button.setIcon(icon)
                    button.setText("")
        self.text.textEdited.connect(self.edit_text)
        self.font_input.currentFontChanged.connect(self.update_text_style)
        self.font_size.valueChanged.connect(self.update_text_style)
        self.outline_width.valueChanged.connect(self.update_text_style)
        for spin in (self.x_input, self.y_input):
            spin.valueChanged.connect(self.transform_layer)
        self.width_input.valueChanged.connect(lambda value: self.resize_layer("width", value))
        self.height_input.valueChanged.connect(lambda value: self.resize_layer("height", value))
        self.rotation_input.valueChanged.connect(self.set_rotation)
        self.ratio_lock.toggled.connect(self.update_ratio_lock)
        self.interpolation.currentIndexChanged.connect(self.update_interpolation)
        self.image_width.valueChanged.connect(lambda value: self.update_image_dimension("width", value))
        self.image_height.valueChanged.connect(lambda value: self.update_image_dimension("height", value))
        self.image_x.valueChanged.connect(self.preview_image_range)
        self.image_y.valueChanged.connect(self.preview_image_range)
        self.image_ratio.toggled.connect(lambda checked: setattr(self.view, "image_ratio_locked", checked))
        self.image_ratio.toggled.connect(
            lambda checked: self.update_image_dimension("width", self.image_width.value()) if checked else None)
        self.view.imageSizePreview.connect(self.preview_image_size)
        self.view.imageResizeCancelled.connect(self.sync_image_size)
        self.view_zoom.valueChanged.connect(self.view.set_zoom)
        self.view.zoomChanged.connect(self.sync_view_zoom)
        self.view.textRequested.connect(self.add_text_at)
        self.view.textEditRequested.connect(self.focus_text)
        self.view.cropChanged.connect(
            require_child(self, QPushButton, "buttonCommitCrop").setEnabled)
        self.tool_buttons = QButtonGroup(self)
        for name, tool in (("buttonMove", "move"), ("buttonScale", "scale"),
                           ("buttonRotate", "rotate"),
                           ("buttonAlign", "align"), ("buttonCrop", "crop"),
                           ("buttonText", "text")):
            button = require_child(self, QPushButton, name)
            self.tool_buttons.addButton(button)
            button.clicked.connect(lambda checked=False, selected=tool: self.set_tool(selected))
        image_size_button = require_child(self, QPushButton, "buttonImageSize")
        self.tool_buttons.addButton(image_size_button)
        image_size_button.clicked.connect(lambda: self.set_tool("image_size"))
        self.layer_list.currentRowChanged.connect(self.select_row)
        self.scene.selectionChanged.connect(self.sync_controls)
        self.base = self.add_layer(pixmap, "元画像")
        self.set_tool("move")
        self.sync_controls()
        self.sync_image_size()
        inspector.setSizes([350, 350])
        self.editor_form.installEventFilter(self)
        self.two_stage_tooltips = TwoStageTooltips(self)

    def set_tool(self, tool):
        self.view.cancel_crop()
        self.view.cancel_image_resize()
        self.view.tool = tool
        self.view.crop_mode = tool == "crop"
        self.view.update_cursor()
        name = {"move": "buttonMove", "scale": "buttonScale", "rotate": "buttonRotate",
                "align": "buttonAlign", "crop": "buttonCrop", "text": "buttonText",
                "image_size": "buttonImageSize"}[tool]
        require_child(self, QPushButton, name).setChecked(True)
        self.tool_stack.setCurrentWidget(self.tool_pages[tool])
        self.tool_settings.setTitle({
            "move": "移動", "scale": "拡大縮小", "rotate": "回転", "align": "整列",
            "crop": "切り抜き", "text": "文字",
            "image_size": "キャンバスのサイズ変更",
        }[tool])
        for layer in self.layers:
            self.configure_layer(layer)
        self.view.viewport().update()
        self.sync_controls()
        if tool == "image_size":
            self.sync_image_size()
        self.view.setFocus()

    def eventFilter(self, watched, event):
        if (watched is self.editor_form and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            self.keyPressEvent(event)
            return True
        if watched.objectName() in getattr(self, "action_flows", {}) and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show):
            margins = watched.layout().contentsMargins()
            height = self.action_flows[watched.objectName()].heightForWidth(
                max(1, watched.width() - margins.left() - margins.right()))
            watched.setMinimumHeight(height + margins.top() + margins.bottom())
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.view.crop_mode:
                self.view.cancel_crop()
            if self.view.tool == "image_size":
                self.view.cancel_image_resize()
            event.accept()
            return
        super().keyPressEvent(event)

    def configure_layer(self, layer):
        layer.resize_mode = self.view.tool == "scale"
        layer.lock_ratio = self.ratio_lock.isChecked()
        layer.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                      self.view.tool == "move")
        layer.update()

    def update_ratio_lock(self):
        for layer in self.layers:
            layer.lock_ratio = self.ratio_lock.isChecked()

    def update_interpolation(self):
        for layer in self.layers:
            layer.model.interpolation = list(Interpolation)[self.interpolation.currentIndex()]
            layer.update()

    def sync_view_zoom(self, percent):
        blocked = self.view_zoom.blockSignals(True)
        self.view_zoom.setValue(percent)
        self.view_zoom.blockSignals(blocked)

    def add_text_at(self, point):
        self.add_text("文字")
        layer = self.current()
        if layer is None:
            raise RuntimeError("追加した文字レイヤーが選択されていません")
        layer.setPos(point)
        self.focus_text(layer)

    def focus_text(self, layer):
        self.set_tool("text")
        self.sync_controls()
        self.text.setFocus()
        self.text.selectAll()

    def commit_crop(self):
        self.view.commit_crop()
        self.sync_image_size()
        self.set_tool("move")

    def cancel_crop(self):
        self.view.cancel_crop()
        self.set_tool("move")

    def current(self):
        return next((item for item in self.layers if item.isSelected()), None)

    def add_layer(self, pixmap, name, text=None):
        layer = ThumbnailLayer(pixmap, self.sync_controls, text)
        layer.model.interpolation = list(Interpolation)[self.interpolation.currentIndex()]
        self.configure_layer(layer)
        layer.name = name
        self.layers.insert(0, layer)
        self.scene.addItem(layer)
        self.scene.clearSelection()
        layer.setSelected(True)
        self.refresh_layers()
        return layer

    def refresh_layers(self):
        self.syncing = True
        self.layer_list.clear()
        for index, layer in enumerate(self.layers):
            layer.setZValue(len(self.layers) - index)
            self.layer_list.addItem(layer.name)
            if layer.isSelected():
                self.layer_list.setCurrentRow(index)
        self.syncing = False
        self.sync_controls()

    def select_row(self, index):
        if not self.syncing and 0 <= index < len(self.layers):
            self.scene.clearSelection()
            self.layers[index].setSelected(True)

    def sync_controls(self):
        layer = self.current()
        if self.syncing:
            return
        self.text_settings.setEnabled(
            self.view.tool == "text" and layer is not None and layer.model.text is not None)
        require_child(self, QWidget, "moveOptions").setEnabled(layer is not None)
        require_child(self, QWidget, "alignmentOptions").setEnabled(layer is not None)
        self.width_input.setEnabled(layer is not None)
        self.height_input.setEnabled(layer is not None)
        self.ratio_lock.setEnabled(layer is not None)
        self.rotation_settings.setEnabled(layer is not None)
        self.opacity.setEnabled(layer is not None)
        for name in ("buttonOpacityMinus", "buttonOpacityPlus"):
            require_child(self, QToolButton, name).setEnabled(layer is not None)
        require_child(self, QPushButton, "buttonRemoveLayer").setEnabled(layer is not None)
        for name, enabled in (
            ("buttonLayerUp", layer is not None and self.layers.index(layer) > 0),
            ("buttonLayerDown", layer is not None and self.layers.index(layer) < len(self.layers) - 1),
        ):
            require_child(self, QPushButton, name).setEnabled(enabled)
        if layer is None:
            return
        self.syncing = True
        bounds = layer.transform().mapRect(layer.content_rect())
        self.width_input.setValue(bounds.width())
        self.height_input.setValue(bounds.height())
        self.rotation_input.setValue(layer.rotation())
        self.x_input.setValue(layer.x())
        self.y_input.setValue(layer.y())
        opacity = round(layer.opacity() * 100)
        self.opacity.set_pages(opacity, 100)
        require_child(self, QToolButton, "buttonOpacityMinus").setEnabled(opacity > 0)
        require_child(self, QToolButton, "buttonOpacityPlus").setEnabled(opacity < 100)
        self.layer_list.setCurrentRow(self.layers.index(layer))
        if layer.model.text is not None:
            self.text.setText(layer.model.text)
            self.font_input.setCurrentFont(layer.model.font)
            self.font_size.setValue(layer.model.font.pixelSize())
            self.outline_width.setValue(layer.model.outline_width)
        self.syncing = False

    def transform_layer(self):
        layer = self.current()
        if self.syncing or layer is None:
            return
        self.syncing = True
        layer.setPos(self.x_input.value(), self.y_input.value())
        self.syncing = False

    def set_opacity(self, value):
        layer = self.current()
        if self.syncing or layer is None:
            return
        layer.setOpacity(max(0, min(100, value)) / 100)
        self.sync_controls()

    def resize_layer(self, axis, value):
        layer = self.current()
        if self.syncing or layer is None:
            return
        bounds = layer.transform().mapRect(layer.content_rect())
        dimension = bounds.width() if axis == "width" else bounds.height()
        sx, sy = resize_factors(dimension, value, axis, self.ratio_lock.isChecked())
        layer.setTransform(QTransform(layer.transform()).scale(sx, sy))
        self.sync_controls()

    def align_layer(self, axis, fraction):
        layer = self.current()
        if layer:
            frame = self.scene.sceneRect()
            bounds = layer.mapRectToScene(layer.content_rect())
            if axis == "x":
                layer.setX(layer.x() + alignment_offset(frame, bounds, axis, fraction))
            else:
                layer.setY(layer.y() + alignment_offset(frame, bounds, axis, fraction))

    def add_text(self, text):
        if text.strip():
            layer = self.add_layer(QPixmap(), f"文字「{text}」", text)
            layer.setPos(self.scene.sceneRect().topLeft())
            self.update_text_style()

    def edit_text(self, text):
        layer = self.current()
        if layer and layer.model.text is not None:
            layer.model.text = text
            layer.name = f"文字「{text}」"
            layer.refresh_text()
            self.refresh_layers()

    def update_text_style(self):
        layer = self.current()
        if not self.syncing and layer and layer.model.text is not None:
            layer.model.font = self.font_input.currentFont()
            layer.model.font.setPixelSize(int(self.font_size.value()))
            layer.model.outline_width = self.outline_width.value()
            layer.refresh_text()
            self.sync_controls()

    def choose_color(self, attribute):
        layer = self.current()
        if layer and layer.model.text is not None:
            color = QColorDialog.getColor(getattr(layer.model, attribute), self)
            if color.isValid():
                setattr(layer.model, attribute, color)
                layer.update()

    def add_image(self):
        patterns = " ".join(f"*{extension}" for extension in readable_image_extensions())
        path, _ = QFileDialog.getOpenFileName(self, "重ねる画像を選択", "", f"画像 ({patterns})")
        if path:
            try:
                image = load_layer_image(path)
            except ValueError as exc:
                QMessageBox.warning(self, "エラー", str(exc))
                return
            pixmap = QPixmap.fromImage(image)
            layer = self.add_layer(pixmap, path.replace("\\", "/").rsplit("/", 1)[-1])
            layer.setPos(self.scene.sceneRect().topLeft())
            self.set_tool("move")

    def reorder(self, delta):
        layer = self.current()
        if layer:
            index = self.layers.index(layer)
            target = max(0, min(len(self.layers) - 1, index + delta))
            self.layers[index], self.layers[target] = self.layers[target], self.layers[index]
            self.refresh_layers()

    def remove_layer(self):
        layer = self.current()
        if layer:
            index = self.layers.index(layer)
            self.layers.remove(layer)
            self.scene.removeItem(layer)
            if self.layers:
                self.layers[min(index, len(self.layers) - 1)].setSelected(True)
            self.refresh_layers()

    def rotate(self, angle):
        layer = self.current()
        if layer:
            self.set_rotation(layer.rotation() + angle)

    def set_rotation(self, angle):
        layer = self.current()
        if self.syncing or layer is None:
            return
        angle = normalized_rotation(angle)
        center = layer.content_rect().center()
        scene_center = layer.mapToScene(center)
        layer.setTransformOriginPoint(center)
        layer.setRotation(angle)
        layer.setPos(layer.pos() + scene_center - layer.mapToScene(center))
        self.sync_controls()

    def reset(self):
        self.view.cancel_crop()
        self.layers.clear()
        self.scene.clear()
        self.scene.setSceneRect(QRectF(self.original.rect()))
        self.base = self.add_layer(QPixmap(self.original), "元画像")
        self.sync_controls()
        self.set_tool("move")
        self.sync_image_size()
        self.view.fit_canvas()

    def sync_image_size(self):
        self.syncing = True
        for layer, position in getattr(self, "canvas_layer_positions", {}).items():
            if layer in self.layers:
                layer.setPos(position)
        self.canvas_layer_positions = {}
        self.syncing = False
        rect = self.scene.sceneRect()
        for control, value in ((self.image_x, 0), (self.image_y, 0)):
            blocked = control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(blocked)
        size = rect.size().toSize()
        self.preview_image_size(size.width(), size.height())

    def preview_image_size(self, width, height):
        rect = self.view.image_resize_preview or QRectF(QPointF(), self.scene.sceneRect().size())
        for control, value in ((self.image_width, width), (self.image_height, height),
                               (self.image_x, round(rect.x())), (self.image_y, round(rect.y()))):
            blocked = control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(blocked)
        self.preview_canvas_layers()

    def preview_canvas_layers(self):
        if self.view.image_resize_preview is None:
            return
        if not getattr(self, "canvas_layer_positions", {}):
            self.canvas_layer_positions = {layer: QPointF(layer.pos()) for layer in self.layers}
        offset = QPointF(self.image_x.value(), self.image_y.value())
        self.syncing = True
        for layer, position in self.canvas_layer_positions.items():
            layer.setPos(position + offset)
        self.syncing = False
        self.view.viewport().update()

    def preview_image_range(self):
        self.view.image_resize_preview = QRectF(
            self.image_x.value(), self.image_y.value(),
            self.image_width.value(), self.image_height.value())
        self.preview_canvas_layers()
        self.view.viewport().update()

    def update_image_dimension(self, axis, value):
        if not self.image_ratio.isChecked():
            self.preview_image_range()
            return
        rect = self.scene.sceneRect()
        width, height = linked_dimensions(round(rect.width()), round(rect.height()), axis, value)
        for control, dimension in ((self.image_width, width), (self.image_height, height)):
            blocked = control.blockSignals(True)
            control.setValue(dimension)
            control.blockSignals(blocked)
        self.preview_image_range()

    def resize_image(self, width, height):
        """Change the canvas bounds while preserving every layer's geometry."""
        self.view.cancel_crop()
        width, height = canvas_size(width, height)
        self.preview_image_range()
        rect = self.scene.sceneRect()
        self.scene.setSceneRect(rect.x(), rect.y(), width, height)
        self.canvas_layer_positions = {}
        self.view.image_resize_preview = None
        self.sync_image_size()
        self.sync_controls()
        self.view.fit_canvas()

    def result_layers(self) -> list[ThumbnailLayerData]:
        self.view.cancel_crop()
        self.view.cancel_image_resize()
        return [replace(layer.model, transform=layer.sceneTransform(), opacity=layer.opacity())
                for layer in reversed(self.layers)]

    def result_pixmap(self):
        return QPixmap.fromImage(compose_thumbnail(self.scene.sceneRect(), self.result_layers()))

    def result_data(self):
        layers = self.result_layers()
        image, encoded = thumbnail_result(self.scene.sceneRect(), layers)
        return QPixmap.fromImage(image), encoded

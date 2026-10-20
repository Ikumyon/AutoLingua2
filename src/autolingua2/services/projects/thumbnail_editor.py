"""Image loading and composition without GUI widgets."""
from __future__ import annotations

from collections.abc import Iterable
from base64 import b64encode
from math import hypot
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColorSpace, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer

from autolingua2.core.thumbnail import Interpolation, ThumbnailLayerData
from autolingua2.services.projects.thumbnail_mark import encode_thumbnail


def readable_image_extensions() -> tuple[str, ...]:
    """Supported inputs; raster formats use Pillow and SVG uses Qt SVG."""
    return (
        ".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp", ".dib",
        ".tiff", ".tif", ".tga", ".dds", ".gif", ".ico", ".icns",
        ".jp2", ".j2k", ".qoi", ".psd", ".cur", ".svg", ".svgz",
    )


def load_layer_image(path: str) -> QImage:
    if Path(path).suffix.lower() in {".svg", ".svgz"}:
        renderer = QSvgRenderer()
        renderer.setAnimationEnabled(False)
        if not renderer.load(path):
            raise ValueError("有効なSVG画像ではありません。")
        size = renderer.defaultSize()
        if size.isEmpty():
            raise ValueError("SVG画像のサイズが不正です。")
        image = QImage(size, QImage.Format.Format_RGBA8888)
        if image.isNull():
            raise ValueError("SVG画像を作成できません。")
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            renderer.render(painter)
        finally:
            painter.end()
        image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        return image
    try:
        with Image.open(path) as source:
            with ImageOps.exif_transpose(source) as oriented:
                with oriented.convert("RGBA") as rgba:
                    image = QImage(rgba.tobytes(), rgba.width, rgba.height,
                                   rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
                if image.isNull():
                    raise ValueError("画像のコピーに失敗しました。")
                profile = oriented.info.get("icc_profile")
                if isinstance(profile, bytes):
                    space = QColorSpace.fromIccProfile(profile)
                    if not space.isValid():
                        raise ValueError("画像のICCプロファイルが無効です。")
                    image.setColorSpace(space)
                    image = image.convertedToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
                else:
                    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
                exif = oriented.getexif()
                if exif:
                    image.setText("autolingua-source-exif", b64encode(exif.tobytes()).decode("ascii"))
                for key, value in oriented.info.items():
                    if isinstance(key, str) and isinstance(value, str) and key not in ("al2-thumbnail-v1", "autolingua-source-exif"):
                        image.setText(key, value)
                dpi = oriented.info.get("dpi")
                if isinstance(dpi, tuple) and len(dpi) == 2:
                    image.setDotsPerMeterX(round(float(dpi[0]) / .0254))
                    image.setDotsPerMeterY(round(float(dpi[1]) / .0254))
                return image
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("有効な画像ファイルではありません。") from exc


def resample_image(image: QImage, width: int, height: int, method: Interpolation) -> QImage:
    srgb = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    if image.colorSpace().isValid() and image.colorSpace() != srgb:
        image = image.convertedToColorSpace(srgb)
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(rgba.constBits())
    if method == Interpolation.AREA:
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(rgba.height(), rgba.width(), 4)
        premultiplied = pixels.astype(np.float32) / 255.0
        premultiplied[:, :, :3] *= premultiplied[:, :, 3:4]
        resized = cv2.resize(premultiplied, (width, height), interpolation=cv2.INTER_AREA)
        alpha = resized[:, :, 3:4]
        np.divide(resized[:, :, :3], alpha, out=resized[:, :, :3], where=alpha > 0)
        result = np.clip(np.rint(resized * 255), 0, 255).astype(np.uint8).tobytes()
    else:
        filters = {
            Interpolation.NEAREST: Image.Resampling.NEAREST,
            Interpolation.BILINEAR: Image.Resampling.BILINEAR,
            Interpolation.BICUBIC: Image.Resampling.BICUBIC,
            Interpolation.LANCZOS: Image.Resampling.LANCZOS,
            Interpolation.BOX: Image.Resampling.BOX,
            Interpolation.HAMMING: Image.Resampling.HAMMING,
            Interpolation.MKS2021: Image.Resampling.MKS2021,
        }
        with Image.frombytes("RGBA", (rgba.width(), rgba.height()), raw) as source:
            with source.resize((width, height), filters[method]) as resized:
                result = resized.tobytes()
    return QImage(result, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


def paint_layer(painter: QPainter, layer: ThumbnailLayerData) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                          layer.interpolation != Interpolation.NEAREST)
    if layer.text is None:
        transform = painter.deviceTransform()
        width = max(1, min(8192, round(layer.image.width() * hypot(transform.m11(), transform.m12()))))
        height = max(1, min(8192, round(layer.image.height() * hypot(transform.m21(), transform.m22()))))
        key = (layer.image.cacheKey(), width, height, layer.interpolation)
        if layer.raster_key != key:
            layer.raster = resample_image(layer.image, width, height, layer.interpolation)
            layer.raster_key = key
        painter.drawImage(QRectF(layer.image.rect()), layer.raster)
    else:
        painter.setPen(QPen(layer.outline, layer.outline_width * 2)
                       if layer.outline_width else QPen(Qt.PenStyle.NoPen))
        painter.setBrush(layer.color)
        painter.drawPath(layer.text_path())


def compose_thumbnail(canvas: QRectF, layers: Iterable[ThumbnailLayerData]) -> QImage:
    layers = list(layers)
    size = canvas.size().toSize()
    if max(size.width(), size.height()) > 4096:
        size.scale(4096, 4096, Qt.AspectRatioMode.KeepAspectRatio)
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    if layers:
        original = layers[0].image
        image.setDotsPerMeterX(original.dotsPerMeterX())
        image.setDotsPerMeterY(original.dotsPerMeterY())
        for key in original.textKeys():
            if key != "al2-thumbnail-v1":
                image.setText(key, original.text(key))
    painter = QPainter(image)
    try:
        painter.scale(size.width() / canvas.width(), size.height() / canvas.height())
        painter.translate(-canvas.left(), -canvas.top())
        for layer in layers:
            painter.save()
            painter.setWorldTransform(layer.transform, True)
            painter.setOpacity(layer.opacity)
            paint_layer(painter, layer)
            painter.restore()
    finally:
        painter.end()
    return image


def thumbnail_result(canvas: QRectF, layers: Iterable[ThumbnailLayerData]) -> tuple[QImage, str]:
    image = compose_thumbnail(canvas, layers)
    return image, encode_thumbnail(image)

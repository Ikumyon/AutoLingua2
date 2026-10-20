"""Image export and optional plugin-owned descriptor updates."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol

from PIL import Image, PngImagePlugin
from PySide6.QtGui import QImage

from autolingua2.services.exporting.export_contract import ExportFile
from autolingua2.services.projects.thumbnail_mark import encode_thumbnail
from base64 import b64decode


class ThumbnailExportHook(Protocol):
    def plan(self, destination: Path, settings: dict[str, object]) -> list[ExportFile]: ...


@dataclass(frozen=True)
class ThumbnailExportSettings:
    format: str = "PNG"
    metadata: bool = True
    compression: int = 6
    optimize: bool = True
    quality: int = 90
    subsampling: int = 0
    progressive: bool = False
    background: str = "#ffffff"


def export_thumbnail(image: QImage, destination: Path, settings: ThumbnailExportSettings,
                     hook: ThumbnailExportHook | None = None,
                     plugin_settings: dict[str, object] | None = None) -> None:
    if image.isNull():
        raise ValueError("出力するサムネイルがありません。")
    updates = hook.plan(destination, plugin_settings or {}) if hook is not None else []
    for update in updates:
        target = (destination.parent / update.relative_path).resolve()
        if not target.is_relative_to(destination.parent.resolve()) or target == destination.resolve():
            raise ValueError("プラグインの画像指定更新先が不正です。")
    # Reuse the metadata and identification pipeline before selecting the output encoding.
    with BytesIO(b64decode(encode_thumbnail(image))) as source:
        with Image.open(source) as original:
            if not isinstance(original, PngImagePlugin.PngImageFile):
                raise ValueError("サムネイルの内部形式が不正です。")
            with BytesIO() as output:
                if settings.format == "PNG":
                    metadata = PngImagePlugin.PngInfo()
                    for key, value in original.text.items():
                        if settings.metadata or key == "al2-thumbnail-v1":
                            metadata.add_itxt(key, value)
                    original.save(output, "PNG", compress_level=settings.compression,
                                  optimize=settings.optimize, pnginfo=metadata,
                                  icc_profile=original.info.get("icc_profile"),
                                  exif=original.info.get("exif", b"") if settings.metadata else b"",
                                  dpi=original.info.get("dpi", (72, 72)))
                elif settings.format == "JPEG":
                    with original.convert("RGBA") as rgba:
                        with Image.new("RGB", original.size, settings.background) as flattened:
                            with rgba.getchannel("A") as alpha:
                                flattened.paste(rgba, mask=alpha)
                            flattened.save(output, "JPEG", quality=settings.quality,
                                           subsampling=settings.subsampling, progressive=settings.progressive,
                                           optimize=settings.optimize, icc_profile=original.info.get("icc_profile"),
                                           exif=original.info.get("exif", b"") if settings.metadata else b"",
                                           dpi=original.info.get("dpi", (72, 72)))
                else:
                    raise ValueError("対応していない画像出力方式です。")
                destination.write_bytes(output.getvalue())
    for update in updates:
        try:
            (destination.parent / update.relative_path).write_bytes(update.content)
        except OSError as exc:
            raise OSError(f"画像は保存しましたが、画像指定の更新に失敗しました: {exc}") from exc

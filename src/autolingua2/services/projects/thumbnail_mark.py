"""PNG thumbnail identification. The distribution contains only an encryption key."""
from __future__ import annotations

from base64 import b64decode, b64encode
from io import BytesIO
from functools import lru_cache
from hashlib import sha256
import json
from struct import pack
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from PIL import Image, PngImagePlugin
from PySide6.QtGui import QImage

from autolingua2 import __version__


PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAqa/Ft8HdInDcVqiStu1o
P5xvAT1uOYaFGlhftkmUlKIdUJmT+SZ9oEe5QrVOUSsEuvmImA2ZQHZ5WEm7odLY
GrkkuxtO3jq32324kN7BXrZL9zp69CvhPUr8rLUUMOQJdqLWOx3z4766r/qeLBGk
vBzUl/eWCcQCLvDBmPnOkhb8jbbblq2OlqPXM3j0Yfr+4A0LpwnJCX7dOBwqmZ4Z
jj2gahaaEXbJi0I0sqvdnwB0oQllmvHPMFD+r5kK0Z49ozXMJDspUsxrd1UsYKTb
3Tg6r0L2Nx99Ls8Fx9SMV6KilusPUxr3kXxAP9Amn50lKsn7B/uWv31cboL4cxrR
2Hx0Ked7myJl50NtEW7N5eWTYuxBUmuIVWRmuyX3GDOztHMY8u0DURr+y7oiQUkT
eu5VI8A5zPfZWJxvU/gwQsWELv5SzE/rDGopoxcYE9wpNcUN8xgMbN6HH6RwZVR2
LrpdgQlxaosjUql2wjtWdleVFKi1choLrDWqZPg+2jofAgMBAAE=
-----END PUBLIC KEY-----
"""
MAGIC = b"AL2T\x01"
TEXT_KEY = "al2-thumbnail-v1"
CLEAR_LOW_BIT = bytes(value & 254 for value in range(256))


def fingerprint(image: QImage) -> str:
    """Ignore RGB low bits; alpha, image size and all other bits remain bound."""
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytearray(rgba.constBits())
    for channel in range(3):
        raw[channel::4] = bytes(raw[channel::4]).translate(CLEAR_LOW_BIT)
    return sha256(pack(">II", rgba.width(), rgba.height()) + raw).hexdigest()


@lru_cache(maxsize=1)
def _public_key() -> rsa.RSAPublicKey:
    key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("Invalid thumbnail encryption key")
    return key


def marked_thumbnail(image: QImage) -> QImage:
    if image.isNull():
        raise ValueError("有効な画像ファイルではありません。")
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    payload = json.dumps({
        "issuer": "AUTOlingua", "format": 1, "id": uuid4().hex,
        "version": __version__, "image": fingerprint(rgba),
    }, separators=(",", ":")).encode("utf-8")
    key = _public_key()
    ciphertext = key.encrypt(payload, padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    key_id = sha256(key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()[:8]
    packet = MAGIC + key_id + pack(">H", len(ciphertext)) + ciphertext
    required = len(packet) * 8
    raw = bytearray(rgba.constBits())
    positions: list[int] = []
    # Only opaque RGB channels are used, so premultiplication cannot destroy bits.
    for offset in range(0, len(raw), 4):
        if raw[offset + 3] == 255:
            positions.extend((offset, offset + 1, offset + 2))
            if len(positions) >= required:
                break
    if len(positions) >= required:
        for bit, position in enumerate(positions[:required]):
            value = (packet[bit // 8] >> (7 - bit % 8)) & 1
            raw[position] = (raw[position] & 254) | value
        # Construct a new image to discard stale text from a previously marked input.
        return QImage(bytes(raw), rgba.width(), rgba.height(), rgba.bytesPerLine(),
                      QImage.Format.Format_RGBA8888).copy()
    # Tiny or transparent thumbnails have no room for the pixel payload.
    result = QImage(bytes(raw), rgba.width(), rgba.height(), rgba.bytesPerLine(),
                    QImage.Format.Format_RGBA8888).copy()
    result.setText(TEXT_KEY, b64encode(packet).decode("ascii"))
    return result


def encode_thumbnail(image: QImage) -> str:
    marked = marked_thumbnail(image).convertToFormat(QImage.Format.Format_RGBA8888)
    metadata = PngImagePlugin.PngInfo()
    for key in image.textKeys():
        if key not in (TEXT_KEY, "autolingua-source-exif"):
            metadata.add_itxt(key, image.text(key))
    if marked.text(TEXT_KEY):
        metadata.add_itxt(TEXT_KEY, marked.text(TEXT_KEY))
    exif = Image.Exif()
    stored_exif = image.text("autolingua-source-exif")
    if stored_exif:
        exif.load(b64decode(stored_exif, validate=True))
        exif[274] = 1
        exif[256], exif[257] = image.width(), image.height()
        if 34665 in exif:
            details = exif.get_ifd(34665)
            details[40962], details[40963] = image.width(), image.height()
            details[40961] = 1
    try:
        with Image.frombytes("RGBA", (marked.width(), marked.height()), bytes(marked.constBits())) as output:
            with BytesIO() as buffer:
                output.save(buffer, "PNG", pnginfo=metadata, exif=exif.tobytes() if exif else b"",
                            icc_profile=image.colorSpace().iccProfile().data() or None,
                            dpi=(image.dotsPerMeterX() * .0254, image.dotsPerMeterY() * .0254))
                return b64encode(buffer.getvalue()).decode("ascii")
    except OSError as exc:
        raise ValueError("サムネイル画像を保存できませんでした。") from exc

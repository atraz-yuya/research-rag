#!/usr/bin/env python3
"""Generate the deterministic Research RAG macOS application icon."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)


MASTER_SIZE = 1024
MASTER_FILENAME = "ResearchRAG-master-1024.png"
ICONSET_DIRECTORY_NAME = "ResearchRAG.iconset"
ICNS_FILENAME = "ResearchRAG.icns"
ICONSET_REPRESENTATIONS: tuple[tuple[int, str], ...] = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)


class IconGenerationError(RuntimeError):
    """Raised when a reproducible icon artifact cannot be generated."""


def draw_master_icon() -> QImage:
    """Draw the square, unmasked document-and-evidence source image."""

    image = QImage(
        MASTER_SIZE,
        MASTER_SIZE,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(QColor("#24376f"))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    background = QLinearGradient(0, 0, MASTER_SIZE, MASTER_SIZE)
    background.setColorAt(0.0, QColor("#1d2d63"))
    background.setColorAt(1.0, QColor("#4265b5"))
    painter.fillRect(QRectF(0, 0, MASTER_SIZE, MASTER_SIZE), background)

    # A broad, low-contrast evidence field gives the icon depth without
    # relying on tiny detail that disappears at Finder's smallest sizes.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(118, 160, 226, 70))
    painter.drawEllipse(QRectF(78, 92, 868, 868))

    page_path = QPainterPath()
    page_path.moveTo(256, 142)
    page_path.lineTo(642, 142)
    page_path.lineTo(780, 280)
    page_path.lineTo(780, 790)
    page_path.quadTo(780, 836, 734, 836)
    page_path.lineTo(290, 836)
    page_path.quadTo(244, 836, 244, 790)
    page_path.lineTo(244, 188)
    page_path.quadTo(244, 142, 290, 142)
    page_path.closeSubpath()

    painter.setBrush(QColor("#f4f7ff"))
    painter.setPen(
        QPen(
            QColor("#132452"),
            28,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.drawPath(page_path)

    fold_path = QPainterPath()
    fold_path.moveTo(642, 142)
    fold_path.lineTo(642, 258)
    fold_path.quadTo(642, 280, 664, 280)
    fold_path.lineTo(780, 280)
    fold_path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#bfd7ff"))
    painter.drawPath(fold_path)

    # Three bold source lines suggest document evidence without text glyphs.
    painter.setPen(
        QPen(
            QColor("#5473b9"),
            30,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    painter.drawLine(QPointF(354, 370), QPointF(674, 370))
    painter.drawLine(QPointF(354, 458), QPointF(690, 458))
    painter.drawLine(QPointF(354, 546), QPointF(590, 546))

    # Connected evidence nodes form a clear citation/retrieval motif.
    connection_pen = QPen(
        QColor("#88c8ff"),
        34,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(connection_pen)
    painter.drawLine(QPointF(400, 674), QPointF(526, 756))
    painter.drawLine(QPointF(526, 756), QPointF(684, 650))

    painter.setPen(QPen(QColor("#132452"), 24))
    painter.setBrush(QColor("#d8eeff"))
    for center in (QPointF(400, 674), QPointF(526, 756), QPointF(684, 650)):
        painter.drawEllipse(center, 52, 52)

    painter.end()
    return image


def write_iconset_pngs(output_directory: Path) -> tuple[Path, Path]:
    """Write the master and conventional macOS iconset PNG representations."""

    output_directory.mkdir(parents=True, exist_ok=True)
    iconset_directory = output_directory / ICONSET_DIRECTORY_NAME
    if iconset_directory.exists():
        if not iconset_directory.is_dir():
            raise IconGenerationError(
                f"Iconset output is not a directory: {iconset_directory}"
            )
        shutil.rmtree(iconset_directory)
    iconset_directory.mkdir()

    master = draw_master_icon()
    master_path = output_directory / MASTER_FILENAME
    if not master.save(str(master_path), "PNG"):
        raise IconGenerationError(f"Could not write icon master: {master_path}")

    for pixel_size, filename in ICONSET_REPRESENTATIONS:
        representation = master.scaled(
            pixel_size,
            pixel_size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        output_path = iconset_directory / filename
        if not representation.save(str(output_path), "PNG"):
            raise IconGenerationError(
                f"Could not write icon representation: {output_path}"
            )
    return master_path, iconset_directory


def generate_icns(output_path: Path, *, iconutil_command: str = "iconutil") -> None:
    """Generate one ICNS file with the macOS system iconutil command."""

    if platform.system() != "Darwin":
        raise IconGenerationError("Research RAG ICNS generation requires macOS")
    resolved_iconutil = shutil.which(iconutil_command)
    if resolved_iconutil is None:
        raise IconGenerationError(
            f"iconutil was not found: {iconutil_command}"
        )
    resolved_xattr = shutil.which("xattr")
    if resolved_xattr is None:
        raise IconGenerationError("xattr was not found on macOS")

    _, iconset_directory = write_iconset_pngs(output_path.parent)
    # FileProvider-managed workspaces may attach quarantine/provenance metadata
    # that makes iconutil reject an otherwise valid iconset. Clear attributes
    # only from this known generated directory before conversion.
    attributes = subprocess.run(
        (resolved_xattr, "-cr", str(iconset_directory)),
        check=False,
    )
    if attributes.returncode != 0:
        raise IconGenerationError(
            f"Could not clear generated iconset attributes: {iconset_directory}"
        )
    completed = subprocess.run(
        (
            resolved_iconutil,
            "-c",
            "icns",
            "-o",
            str(output_path),
            str(iconset_directory),
        ),
        check=False,
    )
    if completed.returncode != 0 or not output_path.is_file():
        raise IconGenerationError(
            f"iconutil did not create the expected file: {output_path}"
        )
    attributes = subprocess.run(
        (resolved_xattr, "-c", str(output_path)),
        check=False,
    )
    if attributes.returncode != 0:
        raise IconGenerationError(
            f"Could not clear generated ICNS attributes: {output_path}"
        )


def _default_output() -> Path:
    return Path(__file__).resolve().parents[1] / "build" / "generated" / ICNS_FILENAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=_default_output())
    parser.add_argument(
        "--iconutil",
        default="iconutil",
        help="iconutil executable name or path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print deterministic outputs without writing files",
    )
    arguments = parser.parse_args(argv)
    if arguments.output.name != ICNS_FILENAME:
        parser.error(f"output filename must be {ICNS_FILENAME}")

    if arguments.dry_run:
        print(f"Master PNG: {arguments.output.parent / MASTER_FILENAME}")
        for _, filename in ICONSET_REPRESENTATIONS:
            print(
                "Iconset PNG: "
                f"{arguments.output.parent / ICONSET_DIRECTORY_NAME / filename}"
            )
        print(f"ICNS: {arguments.output}")
        return 0

    try:
        generate_icns(arguments.output, iconutil_command=arguments.iconutil)
    except IconGenerationError as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Generated macOS icon: {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

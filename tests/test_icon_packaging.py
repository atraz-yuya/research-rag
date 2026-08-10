from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from scripts import generate_app_icon


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate_app_icon.py"


def test_icon_design_constants_are_deterministic_and_complete() -> None:
    assert generate_app_icon.MASTER_SIZE == 1024
    assert generate_app_icon.ICNS_FILENAME == "ResearchRAG.icns"
    assert generate_app_icon.ICONSET_REPRESENTATIONS == (
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


def test_generator_writes_expected_square_pngs_from_one_master(
    tmp_path: Path,
) -> None:
    master_path, iconset_path = generate_app_icon.write_iconset_pngs(tmp_path)

    master = QImage(str(master_path))
    assert master.width() == master.height() == 1024
    assert master.pixelColor(0, 0).alpha() == 255
    assert sorted(path.name for path in iconset_path.iterdir()) == sorted(
        filename
        for _, filename in generate_app_icon.ICONSET_REPRESENTATIONS
    )
    for pixel_size, filename in generate_app_icon.ICONSET_REPRESENTATIONS:
        representation = QImage(str(iconset_path / filename))
        assert representation.width() == representation.height() == pixel_size


def test_png_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first_master, first_iconset = generate_app_icon.write_iconset_pngs(
        tmp_path / "first"
    )
    second_master, second_iconset = generate_app_icon.write_iconset_pngs(
        tmp_path / "second"
    )

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert digest(first_master) == digest(second_master)
    for _, filename in generate_app_icon.ICONSET_REPRESENTATIONS:
        assert digest(first_iconset / filename) == digest(second_iconset / filename)


def test_icon_drawing_contains_no_text_or_prerounded_mask() -> None:
    source = GENERATOR.read_text()
    image = generate_app_icon.draw_master_icon()

    assert "drawText" not in source
    assert image.width() == image.height()
    assert all(
        image.pixelColor(x, y).alpha() == 255
        for x, y in ((0, 0), (1023, 0), (0, 1023), (1023, 1023))
    )


def test_real_icns_generation_rejects_missing_iconutil(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generate_app_icon.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(generate_app_icon.shutil, "which", lambda command: None)

    with pytest.raises(
        generate_app_icon.IconGenerationError,
        match="iconutil was not found",
    ):
        generate_app_icon.generate_icns(
            tmp_path / generate_app_icon.ICNS_FILENAME,
            iconutil_command="missing-iconutil",
        )

    assert not list(tmp_path.iterdir())


def test_generated_icon_and_dmg_artifacts_are_not_tracked() -> None:
    tracked = subprocess.run(
        ("git", "ls-files"),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert not any(path.startswith("build/") for path in tracked)
    assert not any(
        path.endswith((".icns", ".dmg", ".dmg.sha256"))
        or ".iconset/" in path
        for path in tracked
    )

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILES_WITH_EXIFTOOL = [
    REPO_ROOT / "Dockerfile",
    REPO_ROOT / "packages" / "Dockerfile",
    REPO_ROOT / "packages" / "markitdown-mcp" / "Dockerfile",
]


def test_exiftool_runtime_images_use_safe_debian_package_source() -> None:
    unsafe_base = "slim-bullseye"

    for dockerfile in DOCKERFILES_WITH_EXIFTOOL:
        text = dockerfile.read_text()

        assert unsafe_base not in text, (
            f"{dockerfile.relative_to(REPO_ROOT)} installs ExifTool from Debian "
            "bullseye, whose apt candidate is 12.16 and is rejected by "
            "MarkItDown's CVE-2021-22204 guard."
        )


def test_exiftool_runtime_images_verify_minimum_version_at_build_time() -> None:
    for dockerfile in DOCKERFILES_WITH_EXIFTOOL:
        text = dockerfile.read_text()

        assert "EXIFTOOL_MIN_VERSION=12.24" in text
        assert '["exiftool", "-ver"]' in text

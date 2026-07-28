from pathlib import Path


def test_development_image_installs_test_tooling():
    dockerfile = Path(__file__).resolve().parents[3] / "Dockerfile.dev"
    text = dockerfile.read_text(encoding="utf-8")

    assert "requirements/base.txt" in text
    assert "requirements/dev.txt" in text

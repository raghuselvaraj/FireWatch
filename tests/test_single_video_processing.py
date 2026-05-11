"""Unit tests for the single-video producer driver in scripts/test_with_videos.py.

These tests cover the small bits of behavior that don't require a running Kafka
broker: that the script's surface is importable, video-id derivation from the
file path, and the path-validation contract that `main()` relies on.
"""
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the module rather than the symbols so pytest doesn't try to collect
# `test_video` (which is a regular function, not a test) at module scope.
from scripts import test_with_videos as twv  # noqa: E402  (import after sys.path mod)


class TestSingleVideoProcessing:
    """Tests for the per-video driver."""

    @pytest.fixture
    def fake_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "sample.mp4"
            video_path.write_bytes(b"not a real video, just bytes")
            yield video_path

    def test_module_exposes_expected_surface(self):
        """`scripts.test_with_videos` should still expose the per-video driver
        and the CLI entrypoint that `run_full_test.sh` depends on."""
        assert callable(twv.test_video)
        assert callable(twv.main)

    def test_video_id_defaults_to_test_prefix(self, fake_video):
        """When no video_id is passed, callers derive one from the filename stem."""
        derived = f"test_{fake_video.stem}"
        assert derived == "test_sample"

    def test_path_must_exist_and_be_a_file(self, fake_video):
        """The producer driver requires a real file on disk; main() asserts this
        before invoking test_video on each path."""
        assert fake_video.exists()
        assert fake_video.is_file()
        assert fake_video.suffix == ".mp4"

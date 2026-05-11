"""OpenCV ``VideoWriter`` setup + finalize.

This module isolates two pieces of fragile behavior:

1. Codec probing — try HEVC variants first, fall back to mp4v.
2. Graceful release — write the last buffered frame, ``release()``,
   force ``gc.collect()`` + ``os.fsync()``, then ``cv2.VideoCapture`` the
   result to confirm the moov atom landed. Without this, killed processes
   leave .mp4 files with "moov atom not found" errors.
"""
import gc
import os
import time
from typing import Optional, Tuple

import cv2
import numpy as np


_CODEC_PROBE_ORDER = ("HEVC", "hvc1", "avc1", "H264", "mp4v")


def probe_codec(width: int, height: int, fps: float) -> Tuple[int, str]:
    """Find the first codec from the probe order that OpenCV can actually open
    a writer for at this resolution/FPS. Returns ``(fourcc, codec_name)``.

    Falls back to ``mp4v`` (always available on macOS/Linux ffmpeg builds)
    if every preferred codec fails.
    """
    test_path = "/tmp/test_codec_firewatch.mp4"
    for codec_name in _CODEC_PROBE_ORDER:
        try:
            fourcc = cv2.VideoWriter_fourcc(*codec_name)
            test_writer = cv2.VideoWriter(test_path, fourcc, fps, (width, height))
            if test_writer.isOpened():
                test_writer.release()
                if os.path.exists(test_path):
                    os.remove(test_path)
                return fourcc, codec_name
        except Exception:
            continue
    return cv2.VideoWriter_fourcc(*"mp4v"), "mp4v"


def open_writer(
    filepath: str, width: int, height: int, fps: float, verbose: bool = True
) -> Tuple[Optional[cv2.VideoWriter], str]:
    """Open a ``VideoWriter`` at ``filepath``, probing for the best codec.

    If ``filepath`` already exists, an integer suffix is appended (``_1.mp4``,
    ``_2.mp4``, …) to avoid clobbering an earlier run's output.

    Returns ``(writer, realized_filepath)``. ``writer`` is ``None`` if every
    codec failed to initialize. ``realized_filepath`` is the path the writer
    is actually bound to (which may differ from the input after suffix bumps).
    """
    if os.path.exists(filepath):
        if verbose:
            print(f"⚠️  WARNING: Output file already exists: {filepath}")
            print("   This may indicate an old stream processor instance is still running.")
            print("   Using a numbered suffix to avoid overwriting.")
        base, ext = os.path.splitext(filepath)
        counter = 1
        while os.path.exists(filepath):
            filepath = f"{base}_{counter}{ext}"
            counter += 1
        if verbose:
            print(f"   Using alternative path: {filepath}")

    fourcc, codec_used = probe_codec(width, height, fps)
    if verbose:
        if codec_used == "mp4v":
            print(f"⚠️  Using fallback codec: {codec_used}")
        else:
            print(f"✓ Using codec: {codec_used}")

    writer = cv2.VideoWriter(filepath, fourcc, fps, (width, height))
    if not writer.isOpened():
        if verbose:
            print(f"Error: Could not open video writer for {filepath}")
        return None, filepath

    if verbose:
        estimated_size_mb = (fps * 60 * 2.5) / 1024  # rough heuristic
        print(f"📹 Started writing: {filepath}")
        print(f"  Codec: {codec_used}, Resolution: {width}x{height}, FPS: {fps:.1f}")
        print(f"  Estimated file size: ~{estimated_size_mb:.1f}MB per minute of video")

    return writer, filepath


def finalize_writer(
    writer: cv2.VideoWriter,
    filepath: str,
    frames_written: int,
    last_frame: Optional[np.ndarray] = None,
    verbose: bool = True,
) -> bool:
    """Flush, release, fsync, and verify the MP4 has a readable moov atom.

    Returns True if the resulting file opens with ``cv2.VideoCapture`` (moov
    atom present); False otherwise. The verbose flag controls human-readable
    status logging.
    """
    size_before = os.path.getsize(filepath) if filepath and os.path.exists(filepath) else 0
    if verbose:
        print(
            f"  Releasing video writer (frames written: {frames_written}, "
            f"current file size: {size_before / 1024 / 1024:.1f}MB)..."
        )

    # Some codecs need one extra write to flush the in-memory buffer.
    if writer is not None and writer.isOpened() and last_frame is not None:
        try:
            writer.write(last_frame)
        except Exception:
            pass

    writer.release()

    # Push file handles out of Python and onto disk before we probe the file.
    gc.collect()
    time.sleep(2.0)
    try:
        if filepath and os.path.exists(filepath):
            fd = os.open(filepath, os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
    except Exception:
        pass

    size_after = os.path.getsize(filepath) if filepath and os.path.exists(filepath) else 0
    if verbose:
        if size_after > size_before:
            print(
                f"  ✓ Video finalized: {size_after / 1024 / 1024:.1f}MB "
                f"(wrote {size_after - size_before} bytes from buffer)"
            )
        else:
            print("  ⚠️  File size unchanged after release (may indicate issue)")

    if not filepath or not os.path.exists(filepath) or size_after == 0:
        if verbose:
            print(f"⚠️  Warning: Video file is empty or missing: {filepath}")
        return False

    # One more beat for the kernel page cache, then probe for moov atom.
    time.sleep(1.0)
    cap = cv2.VideoCapture(filepath)
    opened = cap.isOpened()
    if opened:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        if frame_count == 0 or fps == 0:
            if verbose:
                print(f"⚠️  Warning: Video file has 0 frames or invalid FPS: {filepath}")
                print("   This may indicate the video writer did not finalize properly")
            # Still report success — some players cope with this metadata quirk.
    else:
        cap.release()
        if verbose:
            print(f"⚠️  Warning: Video file may be corrupted (moov atom missing): {filepath}")
            print("   This can happen if OpenCV VideoWriter didn't properly finalize the file")
            print("   On macOS, try using 'avc1' codec for better compatibility")

    return opened

"""Read/write the per-video progress JSON file shared with run_full_test.sh.

The file is a single object with a ``videos`` list. The producer writes
``producer_progress`` and ``total_frames`` per video; the stream processor
writes ``stream_progress``. Both readers use ``fcntl`` advisory locks so a
producer and consumer updating the same file don't race.
"""
import fcntl
import json
import time
from typing import Optional


_MAX_RETRIES = 5
_RETRY_DELAY = 0.1


def _read_locked(progress_file: str) -> dict:
    """Read the progress JSON with a shared advisory lock. Returns ``{"videos": []}``
    if the file is missing, malformed, or contended for too long."""
    for attempt in range(_MAX_RETRIES):
        try:
            with open(progress_file, "r") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                data = json.load(f)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return data
        except (IOError, OSError, json.JSONDecodeError):
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY)
                continue
            return {"videos": []}
    return {"videos": []}


def _write_locked(progress_file: str, data: dict) -> None:
    """Write the progress JSON with an exclusive advisory lock. Silent on failure
    — progress updates are best-effort and must never block the hot path."""
    for attempt in range(_MAX_RETRIES):
        try:
            with open(progress_file, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                json.dump(data, f)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return
        except (IOError, OSError):
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY)
                continue


def update_stream_progress(progress_file: str, video_id: str, frames_processed: int) -> None:
    """Recompute and persist ``stream_progress`` for a single video.

    Stream progress is normalized against ``total_frames`` (same denominator
    the producer uses) so the producer and stream bars share scale. It is
    capped at the current ``producer_progress`` — the consumer can never be
    ahead of the producer — and never decreases.
    """
    try:
        data = _read_locked(progress_file)

        producer_prog = 0
        total_frames: Optional[int] = None
        target = None
        for v in data.get("videos", []):
            if v.get("video_id") == video_id:
                target = v
                producer_prog = v.get("producer_progress", 0)
                if v.get("total_frames", 0) > 0:
                    total_frames = v["total_frames"]
                break

        if total_frames and total_frames > 0:
            if frames_processed >= total_frames:
                stream_prog: Optional[int] = min(100, producer_prog)
            else:
                raw = int((frames_processed * 100) / total_frames)
                stream_prog = min(raw, producer_prog, 100)
        else:
            stream_prog = None  # Can't compute; leave prior value.

        if target is not None:
            if stream_prog is not None:
                target["stream_progress"] = max(target.get("stream_progress", 0), stream_prog)
        elif stream_prog is not None:
            data.setdefault("videos", []).append(
                {
                    "video_id": video_id,
                    "name": video_id,
                    "producer_progress": 0,
                    "stream_progress": stream_prog,
                }
            )

        _write_locked(progress_file, data)
    except Exception:
        # Progress updates must never break the pipeline; swallow.
        pass


def finalize_stream_progress(progress_file: str, video_id: str, frames_processed: int) -> None:
    """Pin ``stream_progress`` to its terminal value once the writer closes.

    If all frames the producer sent have been processed, snap to 100% (capped
    at the producer's reported progress). Otherwise, compute the normalized
    fraction the same way ``update_stream_progress`` does. Like that function,
    progress never decreases.
    """
    try:
        data = _read_locked(progress_file)
        target = None
        producer_prog = 0
        total_frames = 0
        for v in data.get("videos", []):
            if v.get("video_id") == video_id:
                target = v
                producer_prog = v.get("producer_progress", 0)
                total_frames = v.get("total_frames", 0) or 0
                break

        if target is None:
            return

        if total_frames > 0:
            if frames_processed >= total_frames:
                stream_prog = min(100, producer_prog)
            else:
                raw = int((frames_processed * 100) / total_frames)
                stream_prog = min(raw, producer_prog, 100)
            target["stream_progress"] = max(target.get("stream_progress", 0), stream_prog)

        _write_locked(progress_file, data)
    except Exception:
        pass


def should_force_update(progress_file: str, video_id: str, frames_processed: int) -> bool:
    """Return True if the producer has reported ~100% and the stream is on the
    last expected frame — used to ensure the final progress tick lands even
    when ``frames_processed % 10 != 0``.
    """
    try:
        with open(progress_file, "r") as f:
            data = json.load(f)
        for v in data.get("videos", []):
            if v.get("video_id") == video_id:
                total = v.get("total_frames", 0)
                prod = v.get("producer_progress", 0)
                return prod >= 99 and total > 0 and frames_processed >= total - 1
    except Exception:
        return False
    return False

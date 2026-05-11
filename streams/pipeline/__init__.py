"""Helpers used by the fire-detection stream pipeline.

Each submodule has a single responsibility:
- serialization: numpy → native-Python conversion for JSON encoding.
- overlay: blend a heatmap onto a video frame.
- video_writer: codec probing, VideoWriter init, and graceful finalize.
- progress: read/write the progress file shared with run_full_test.sh.
"""

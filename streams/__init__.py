"""Kafka streams package for ML-based fire detection.

Public surface:

- :class:`FireDetectionStream` (in :mod:`streams.stream`) — the consumer loop.
- :class:`FireDetectionModel` (in :mod:`streams.models`) — model dispatcher.
- :func:`convert_numpy_types` (in :mod:`streams.pipeline.serialization`) —
  legacy JSON-serialization helper, re-exported for tests that still import
  it from this package.
"""
from streams.models import FireDetectionModel
from streams.pipeline.serialization import convert_numpy_types
from streams.stream import FireDetectionStream

__all__ = ["FireDetectionModel", "FireDetectionStream", "convert_numpy_types"]

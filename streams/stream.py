"""Kafka stream processor that drives the fire-detection pipeline.

Consumes JPEG-encoded frames from ``video-frames``, runs ML inference,
overlays a GradCAM heatmap (when fire is detected), writes the annotated
frame to a per-video MP4, and publishes detection + completion events to
their respective topics.

The heavy lifting (model inference, codec probing, heatmap blending,
progress-file I/O) lives in :mod:`streams.models` and :mod:`streams.pipeline`;
this module owns the consumer loop, per-video state dicts, and Kafka I/O.
"""
import base64
import json
import os
import signal
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
from kafka import KafkaConsumer, KafkaProducer

# Suppress noisy library warnings (carried over from the monolith).
warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")
warnings.filterwarnings("ignore", message=".*x265.*")

# Make ``import config`` work when the package is executed directly.
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import config  # noqa: E402

from streams.models import FireDetectionModel  # noqa: E402
from streams.pipeline import progress, video_writer  # noqa: E402
from streams.pipeline.overlay import overlay_heatmap_on_frame  # noqa: E402
from streams.pipeline.serialization import convert_numpy_types  # noqa: E402


class FireDetectionStream:
    """Kafka stream processor for fire detection.

    The public API matches the pre-Phase-2 monolith — tests instantiate this
    class with the Kafka clients and model patched out and exercise
    ``decode_frame``, ``_initialize_video_writer``, ``_close_video_writer``,
    ``_overlay_heatmap_on_frame``, ``_initialize_video_state``, ``process_frame``,
    ``_cleanup``, and ``run``. Internally each of those delegates to functions
    in :mod:`streams.pipeline` and :mod:`streams.models`.
    """

    def __init__(self):
        group_id = os.environ.get("KAFKA_GROUP_ID", "fire-detection-stream")

        self.consumer = KafkaConsumer(
            config.KAFKA_VIDEO_TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
            group_id=group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            consumer_timeout_ms=2147483647,  # ~24 days — effectively forever
            max_poll_records=300,
            fetch_min_bytes=32768,
            fetch_max_wait_ms=500,
            max_partition_fetch_bytes=10485760,
        )

        self.producer = KafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks=1,
            retries=3,
            max_in_flight_requests_per_connection=5,
            compression_type="gzip",
            batch_size=16384,
            linger_ms=10,
        )

        self.model = FireDetectionModel()
        self.detections_topic = config.KAFKA_DETECTIONS_TOPIC
        self.video_completions_topic = config.KAFKA_VIDEO_COMPLETIONS_TOPIC

        # Per-video state. Multiple videos can be in flight at once (one per
        # video_id). The plan calls for collapsing these into a VideoStateRegistry
        # in a later phase; for now they stay as plain dicts so existing tests
        # that reach in (`stream.video_writers[video_id]`) keep working.
        self.video_writers: Dict[str, Optional[cv2.VideoWriter]] = {}
        self.video_metadata: Dict[str, Dict[str, Any]] = {}
        self.video_frame_counts: Dict[str, int] = {}
        self.video_total_frames: Dict[str, int] = {}
        self.video_last_frame_numbers: Dict[str, Optional[int]] = {}
        self.video_last_frames: Dict[str, Optional[np.ndarray]] = {}
        self.video_stats: Dict[str, Dict[str, float]] = {}
        self.progress_file = os.getenv("PROGRESS_FILE", "/tmp/firewatch_video_progress.json")
        self.last_progress_update: Dict[str, float] = {}

    # ----- frame I/O -------------------------------------------------------

    def decode_frame(self, frame_data: str) -> np.ndarray:
        """Decode a base64 JPEG payload back to a BGR numpy array."""
        frame_bytes = base64.b64decode(frame_data)
        nparr = np.frombuffer(frame_bytes, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # ----- video writer state ---------------------------------------------

    def _initialize_video_state(
        self,
        video_id: str,
        timestamp: str,
        frame_number: int,
        fps: float,
        width: int,
        height: int,
    ) -> None:
        """Seed the per-video state dicts for a video we haven't seen before."""
        if video_id in self.video_metadata:
            return
        self.video_metadata[video_id] = {
            "fps": fps,
            "width": width,
            "height": height,
            "filepath": None,
            "start_timestamp": timestamp,
        }
        self.video_frame_counts[video_id] = 0
        self.video_last_frame_numbers[video_id] = None
        self.video_last_frames[video_id] = None
        self.video_stats.setdefault(video_id, {"frames": 0, "fires": 0, "max_prob": 0.0})

    def _initialize_video_writer(
        self, video_id: str, width: int, height: int, fps: float
    ) -> Optional[str]:
        """Open the per-video MP4 writer if it isn't open already.

        Returns the filepath the writer is bound to, or ``None`` on failure.
        """
        if video_id in self.video_writers and self.video_writers[video_id] is not None:
            return self.video_metadata.get(video_id, {}).get("filepath")

        try:
            start_timestamp = self.video_metadata.get(video_id, {}).get("start_timestamp")
            if not start_timestamp:
                start_timestamp = datetime.utcnow().isoformat()

            output_dir = config.CLIP_STORAGE_PATH
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, f"{video_id}_with_heatmaps.mp4")

            writer, realized_filepath = video_writer.open_writer(filepath, width, height, fps)
            if writer is None:
                if video_id in self.video_writers:
                    self.video_writers[video_id] = None
                return None

            self.video_writers[video_id] = writer
            self.video_metadata[video_id] = {
                "fps": fps,
                "width": width,
                "height": height,
                "filepath": realized_filepath,
                "start_timestamp": start_timestamp,
            }
            self.video_frame_counts[video_id] = 0
            return realized_filepath

        except Exception as e:
            print(f"Error initializing video writer for {video_id}: {e}")
            import traceback

            traceback.print_exc()
            if video_id in self.video_writers:
                self.video_writers[video_id] = None
            return None

    def _close_video_writer(self, video_id: str, print_summary: bool = True) -> Optional[str]:
        """Release the writer, finalize the MP4, and publish a completion event."""
        if video_id not in self.video_writers or self.video_writers[video_id] is None:
            return None

        try:
            writer = self.video_writers[video_id]
            metadata = self.video_metadata.get(video_id, {})
            filepath = metadata.get("filepath")
            frame_count = self.video_frame_counts.get(video_id, 0)

            video_writer.finalize_writer(
                writer=writer,
                filepath=filepath,
                frames_written=frame_count,
                last_frame=self.video_last_frames.get(video_id),
            )
            self.video_writers[video_id] = None

            stats = self.video_stats.get(video_id, {})
            fire_count = stats.get("fires", 0)
            total_frames = stats.get("frames", frame_count)
            max_prob = stats.get("max_prob", 0.0)

            if video_id and filepath and os.path.exists(filepath):
                self._publish_video_completion(
                    video_id,
                    filepath,
                    {
                        "total_frames": total_frames,
                        "fire_count": fire_count,
                        "max_fire_probability": max_prob,
                    },
                    {
                        "fps": metadata.get("fps"),
                        "width": metadata.get("width"),
                        "height": metadata.get("height"),
                        "frame_count": frame_count,
                    },
                )

            if print_summary and video_id:
                print(f"\n{'='*60}")
                print(f"📹 Video Complete: {video_id}")
                print(f"{'='*60}")
                print(f"  Local file: {filepath}")
                print(f"  Total frames: {total_frames}")
                print(f"  Frames with fire: {fire_count}")
                print(f"  Max fire probability: {max_prob:.2%}")
                if fire_count == 0:
                    print("  Result: ✅ No fires detected")
                else:
                    print(f"  Result: 🔥 Fire detected in {fire_count} frame(s)")
                print(f"  → Published to {self.video_completions_topic} for S3 upload")
                print(f"{'='*60}\n")

            # Pin the progress bar to its terminal value, then reset the counter.
            if video_id in self.video_frame_counts:
                progress.finalize_stream_progress(
                    self.progress_file, video_id, self.video_frame_counts[video_id]
                )
                self.video_frame_counts[video_id] = 0

            return filepath

        except Exception as e:
            print(f"Error closing video writer for {video_id}: {e}")
            import traceback

            traceback.print_exc()
            if video_id in self.video_writers:
                self.video_writers[video_id] = None
            return None

    # ----- frame post-processing ------------------------------------------

    def _overlay_heatmap_on_frame(
        self, frame: np.ndarray, heatmap: Optional[np.ndarray], alpha: Optional[float] = None
    ) -> np.ndarray:
        return overlay_heatmap_on_frame(frame, heatmap, alpha)

    def _update_stream_progress(self, video_id: str) -> None:
        progress.update_stream_progress(
            self.progress_file, video_id, self.video_frame_counts.get(video_id, 0)
        )

    def _publish_video_completion(
        self,
        video_id: str,
        local_filepath: str,
        stats: Dict[str, Any],
        video_metadata: Dict[str, Any],
    ) -> None:
        """Publish a synchronous completion event for the S3 upload consumer."""
        try:
            event = {
                "video_id": video_id,
                "local_filepath": local_filepath,
                "timestamp": datetime.utcnow().isoformat(),
                "stats": stats,
                "video_metadata": video_metadata,
            }
            future = self.producer.send(self.video_completions_topic, key=video_id, value=event)
            future.get(timeout=10)
            print(f"📤 Published video completion event for {video_id}")
        except Exception as e:
            print(f"⚠️  Error publishing video completion: {e}")

    # ----- per-frame processing -------------------------------------------

    def process_frame(self, message_value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Decode, classify, render, and emit one frame's detection payload."""
        try:
            frame = self.decode_frame(message_value["frame_data"])

            video_id = message_value["video_id"]
            frame_number = int(message_value["frame_number"])
            timestamp = message_value["timestamp"]
            fps = message_value.get("fps", 30.0)
            width = message_value.get("width")
            height = message_value.get("height")

            # Track the highest frame number seen — used for the progress %.
            self.video_total_frames[video_id] = max(
                self.video_total_frames.get(video_id, frame_number), frame_number
            )

            if video_id not in self.video_metadata:
                self._initialize_video_state(video_id, timestamp, frame_number, fps, width, height)

            # If we see a 300-frame gap, treat that as the prior video ending.
            # The threshold is intentionally generous so out-of-order or delayed
            # frames don't trigger a premature close.
            last_seen = self.video_last_frame_numbers.get(video_id)
            if last_seen is not None and frame_number - last_seen > 300:
                print(f"⚠️  Detected large gap of {frame_number - last_seen} frames - closing video {video_id}")
                self._close_video_writer(video_id, print_summary=True)
                self._initialize_video_state(video_id, timestamp, frame_number, fps, width, height)

            self.video_last_frame_numbers[video_id] = frame_number

            # Backfill metadata defaults if we got missing dimensions earlier.
            meta = self.video_metadata.get(video_id, {})
            if meta.get("fps") is None:
                meta["fps"] = fps
            if meta.get("width") is None and width:
                meta["width"] = width
            if meta.get("height") is None and height:
                meta["height"] = height

            # Lazy-open the writer once we know dimensions.
            if video_id not in self.video_writers or self.video_writers[video_id] is None:
                if meta.get("width") and meta.get("height"):
                    self._initialize_video_writer(video_id, meta["width"], meta["height"], meta["fps"])

            prediction = self.model.predict(frame)

            if video_id in self.video_stats:
                self.video_stats[video_id]["frames"] += 1
                if prediction["has_fire"]:
                    self.video_stats[video_id]["fires"] += 1
                    self.video_stats[video_id]["max_prob"] = max(
                        self.video_stats[video_id]["max_prob"], prediction["fire_probability"]
                    )

            heatmap = prediction.get("heatmap")
            processed_frame = frame.copy()
            if heatmap is not None:
                processed_frame = self._overlay_heatmap_on_frame(processed_frame, heatmap)

            if video_id in self.video_writers and self.video_writers[video_id] is not None:
                self.video_writers[video_id].write(processed_frame)
                self.video_frame_counts[video_id] = self.video_frame_counts.get(video_id, 0) + 1
                self.video_last_frames[video_id] = processed_frame.copy()

                frames_processed = self.video_frame_counts[video_id]
                should_update = (frames_processed % 10 == 0) or progress.should_force_update(
                    self.progress_file, video_id, frames_processed
                )
                if should_update:
                    self._update_stream_progress(video_id)

            detection_result = {
                "video_id": video_id,
                "frame_number": frame_number,
                "timestamp": timestamp,
                "processing_timestamp": datetime.utcnow().isoformat(),
                "has_fire": prediction["has_fire"],
                "fire_probability": prediction["fire_probability"],
                "detections": prediction["detections"],
                "frame_metadata": {
                    "width": message_value.get("width"),
                    "height": message_value.get("height"),
                    "fps": fps,
                },
            }
            return convert_numpy_types(detection_result)

        except Exception as e:
            print(f"Error processing frame: {e}")
            return None

    # ----- lifecycle ------------------------------------------------------

    def _cleanup(self) -> None:
        """Finalize every open video writer. Called on SIGINT/SIGTERM."""
        print("\n🛑 Cleaning up and finalizing all videos...")
        for video_id in list(self.video_writers.keys()):
            if self.video_writers[video_id] is not None:
                try:
                    self._close_video_writer(video_id, print_summary=True)
                except Exception as e:
                    print(f"Error closing video {video_id} during cleanup: {e}")

    def run(self) -> None:
        """Main consumer loop. Blocks until SIGINT/SIGTERM or fatal error."""
        print("Starting fire detection stream processor...")
        print(f"Consuming from topic: {config.KAFKA_VIDEO_TOPIC}")
        print(f"Publishing to topic: {config.KAFKA_DETECTIONS_TOPIC}")
        print("Waiting for messages... (Press Ctrl+C to stop)\n")

        def signal_handler(sig, _frame):
            print(f"\n\nReceived signal {sig}, shutting down gracefully...")
            self._cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        message_count = 0
        detection_count = 0
        fire_count = 0

        try:
            for message in self.consumer:
                message_count += 1
                video_id = message.key
                frame_data = message.value

                if message_count % 10 == 0:
                    print(
                        f"Processed {message_count} frames... "
                        f"(latest: frame {frame_data.get('frame_number')} from video {video_id})"
                    )

                detection_result = self.process_frame(frame_data)
                if detection_result is None:
                    print(
                        f"⚠️  Failed to process frame {frame_data.get('frame_number')} "
                        f"from video {video_id}"
                    )
                    continue

                detection_count += 1
                if detection_result["has_fire"]:
                    fire_count += 1
                    print(
                        f"🔥 Fire detected! Frame {frame_data.get('frame_number')} from video "
                        f"{video_id} - Probability: {detection_result['fire_probability']:.2%}"
                    )

                future = self.producer.send(
                    self.detections_topic, key=video_id, value=detection_result
                )

                # Only attach callbacks for positive detections — keeps the
                # hot-path overhead down for the (much larger) negative stream.
                if detection_result["has_fire"]:
                    def on_send_success(record_metadata):
                        print(
                            f"  → Detection sent to topic {record_metadata.topic} "
                            f"partition {record_metadata.partition}"
                        )

                    def on_send_error(excp):
                        print(f"  ⚠️  Error sending detection: {excp}")

                    future.add_callback(on_send_success)
                    future.add_errback(on_send_error)

                # Commit every 250 messages: throughput tradeoff per the
                # original module's comment. Phase 3 will revisit this.
                if message_count % 250 == 0:
                    try:
                        self.consumer.commit()
                    except Exception as e:
                        print(f"⚠️  Error committing offset: {e}")

            # Loop exited via consumer timeout — close any open writers.
            try:
                self.consumer.commit()
            except Exception:
                pass

            active_videos = [vid for vid, writer in self.video_writers.items() if writer is not None]
            if active_videos:
                print(f"\n⚠️  Consumer loop exited - processed {message_count} messages total")
                print(f"  Closing {len(active_videos)} active video(s)...")
                for video_id in active_videos:
                    self._close_video_writer(video_id, print_summary=True)

        except KeyboardInterrupt:
            print("\n\nStopping stream processor...")
            self._cleanup()
            print(
                f"Summary: Processed {message_count} messages, "
                f"{detection_count} detections, {fire_count} fires"
            )
        except Exception as e:
            print(f"\nError in stream processor: {e}")
            self._cleanup()
            import traceback

            traceback.print_exc()
        finally:
            # Defensive: if anything above threw before the active-videos loop,
            # this catches anything we still have open.
            for video_id in list(self.video_writers.keys()):
                if self.video_writers[video_id] is not None:
                    try:
                        self._close_video_writer(video_id, print_summary=False)
                    except Exception:
                        pass
            self.consumer.close()
            self.producer.flush()
            self.producer.close()
            print(
                f"Final summary: {message_count} messages processed, "
                f"{detection_count} detections created, {fire_count} fires detected"
            )

"""
Inspect Kafka topics: status, raw messages, or formatted fire detections.

Subcommands:
  status       Show broker connectivity and per-topic message counts.
  messages     Dump raw messages from a topic as pretty JSON.
  detections   Stream the fire-detections topic with human-readable formatting.

Examples:
  python3 scripts/kafka_inspect.py status
  python3 scripts/kafka_inspect.py messages fire-detections --limit 20
  python3 scripts/kafka_inspect.py detections --new-only
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka import KafkaConsumer, KafkaProducer

import config


def cmd_status(_args: argparse.Namespace) -> int:
    """Print broker connectivity and message counts per topic."""
    print("=" * 60)
    print("Kafka Topic Status")
    print("=" * 60)
    print(f"Bootstrap servers: {config.KAFKA_BOOTSTRAP_SERVERS}\n")

    try:
        producer = KafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            request_timeout_ms=5000,
        )
        producer.close()
        print("✓ Kafka connection successful\n")
    except Exception as exc:
        print(f"✗ Cannot connect to Kafka: {exc}")
        print("  Ensure Kafka is running (e.g. `docker-compose up -d`).")
        return 1

    for topic in (
        config.KAFKA_VIDEO_TOPIC,
        config.KAFKA_DETECTIONS_TOPIC,
        config.KAFKA_VIDEO_COMPLETIONS_TOPIC,
    ):
        _print_topic_status(topic)
        print()
    return 0


def _print_topic_status(topic: str) -> None:
    try:
        consumer = KafkaConsumer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            consumer_timeout_ms=2000,
        )
        consumer.subscribe([topic])
        consumer.poll(timeout_ms=2000)
        partitions = consumer.assignment()

        if not partitions:
            print(f"Topic: {topic} — (no partitions; may not exist yet)")
            consumer.close()
            return

        end_offsets = consumer.end_offsets(partitions)
        total = sum(end_offsets.values())
        print(f"Topic: {topic}  (partitions: {len(partitions)}, messages: {total})")
        for tp, offset in sorted(end_offsets.items(), key=lambda kv: kv[0].partition):
            print(f"  partition {tp.partition}: {offset}")
        consumer.close()
    except Exception as exc:
        print(f"Topic: {topic} — error: {exc}")


def cmd_messages(args: argparse.Namespace) -> int:
    """Dump raw messages from a topic."""
    print(f"Consuming raw messages from: {args.topic} (limit={args.limit or 'none'})")
    print("Press Ctrl+C to stop.\n")

    consumer = KafkaConsumer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        group_id=f"inspect-messages-{uuid.uuid4().hex[:8]}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        # 10s gives time for the rebalance + first fetch before the iterator
        # decides the topic is empty.
        consumer_timeout_ms=10000,
    )
    consumer.subscribe([args.topic])
    # Drive at least one poll so partitions get assigned before we iterate.
    consumer.poll(timeout_ms=5000)
    partitions = consumer.assignment()
    if partitions:
        consumer.seek_to_beginning(*partitions)

    try:
        count = 0
        for message in consumer:
            count += 1
            print("=" * 70)
            print(f"#{count}  key={message.key}  partition={message.partition}  offset={message.offset}")
            print(json.dumps(message.value, indent=2))
            if args.limit and count >= args.limit:
                break
        if count == 0:
            print("No messages found.")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        consumer.close()
    return 0


def cmd_detections(args: argparse.Namespace) -> int:
    """Format and display messages from the fire-detections topic."""
    print("=" * 70)
    print("FireWatch Detection Viewer")
    print("=" * 70)
    print(f"Topic: {config.KAFKA_DETECTIONS_TOPIC}")
    print(f"Bootstrap servers: {config.KAFKA_BOOTSTRAP_SERVERS}")

    group_id = f"inspect-detections-{uuid.uuid4().hex[:8]}"
    consumer = KafkaConsumer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        # 10s gives time for the rebalance + first fetch before the iterator
        # decides the topic is empty.
        consumer_timeout_ms=10000,
    )
    consumer.subscribe([config.KAFKA_DETECTIONS_TOPIC])
    # Drive polls until partitions are assigned (rebalance can take several seconds
    # on the first connection to a new broker).
    for _ in range(5):
        consumer.poll(timeout_ms=2000)
        partitions = consumer.assignment()
        if partitions:
            break
        time.sleep(1)
    else:
        print("⚠️  No partitions assigned after 15s; topic may be empty.")
        consumer.close()
        return 0

    if args.new_only:
        consumer.seek_to_end(*partitions)
    else:
        consumer.seek_to_beginning(*partitions)

    print(f"Reading from {'end' if args.new_only else 'beginning'} of {len(partitions)} partition(s).")
    print("Press Ctrl+C to stop.\n")

    try:
        message_count = 0
        fire_count = 0
        for message in consumer:
            message_count += 1
            detection = message.value
            print(_format_detection(detection))
            if detection.get("has_fire"):
                fire_count += 1
            if args.limit and message_count >= args.limit:
                break

        if message_count == 0:
            print("\n⚠️  No detections found.")
            print("  Is the stream processor running? Has the producer published frames?")
        else:
            print("=" * 70)
            print(f"Summary: {message_count} messages processed, {fire_count} fires detected")
            print("=" * 70)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        consumer.close()
    return 0


def _format_detection(detection: dict) -> str:
    video_id = detection.get("video_id", "unknown")
    frame_num = detection.get("frame_number", "?")
    timestamp = detection.get("timestamp", "?")
    has_fire = detection.get("has_fire", False)
    probability = detection.get("fire_probability", 0.0)
    detections = detection.get("detections", []) or []

    lines = [
        "=" * 70,
        f"Video: {video_id} | Frame: {frame_num} | Time: {timestamp}",
        "=" * 70,
    ]
    if has_fire:
        lines.append(f"🔥 FIRE DETECTED  (probability: {probability:.2%})")
        for i, det in enumerate(detections, 1):
            lines.append(
                f"  {i}. class={det.get('class','?')} "
                f"conf={det.get('confidence', 0.0):.2%} "
                f"bbox={det.get('bbox')}"
            )
    else:
        lines.append(f"✓ No fire (probability: {probability:.2%})")
    lines.append("=" * 70)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect FireWatch Kafka topics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show broker connectivity and topic message counts.")

    p_messages = sub.add_parser("messages", help="Dump raw messages from a topic.")
    p_messages.add_argument(
        "topic",
        nargs="?",
        default=config.KAFKA_DETECTIONS_TOPIC,
        help="Topic name (default: fire-detections).",
    )
    p_messages.add_argument("-l", "--limit", type=int, default=None)

    p_det = sub.add_parser("detections", help="Formatted view of fire detections.")
    p_det.add_argument(
        "-n",
        "--new-only",
        action="store_true",
        help="Only show messages produced after this command starts.",
    )
    p_det.add_argument("-l", "--limit", type=int, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "status": cmd_status,
        "messages": cmd_messages,
        "detections": cmd_detections,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

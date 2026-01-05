"""Kafka Streams application for real-time forest fire detection using ML models."""
import json
import base64
import numpy as np
import cv2
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from ultralytics import YOLO

# Add parent directory to path to import config and modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import config

# Import fire-detect-nn if using that model type
# Try importing from installed package first, then fall back to local directory
FIRE_DETECT_NN_AVAILABLE = False
if config.ML_MODEL_TYPE == "fire-detect-nn" or config.ML_MODEL_SOURCE == "fire-detect-nn":
    try:
        # First try importing from installed package (site-packages)
        try:
            import fire_detect_nn
            FIRE_DETECT_NN_AVAILABLE = True
            print("✓ fire-detect-nn found in site-packages")
        except ImportError:
            # Fall back to local directory (for backwards compatibility)
            fire_detect_dir = project_root / config.FIRE_DETECT_NN_DIR
            if fire_detect_dir.exists():
                sys.path.insert(0, str(fire_detect_dir))
                FIRE_DETECT_NN_AVAILABLE = True
                print(f"✓ fire-detect-nn found in local directory: {fire_detect_dir}")
            else:
                print(f"⚠️  fire-detect-nn not found in site-packages or local directory")
                print(f"   Run: python3 scripts/install_fire_detect_nn.py")
    except Exception as e:
        print(f"⚠️  fire-detect-nn not available: {e}")


class FireDetectionModel:
    """Unified fire detection model supporting fire-detect-nn (default) and Ultralytics YOLOv8 (alternative)."""
    
    def __init__(self, model_path: str = None):
        """Initialize the fire detection model."""
        self.model_path = model_path or config.ML_MODEL_PATH
        self.confidence_threshold = config.CONFIDENCE_THRESHOLD
        self.iou_threshold = config.IOU_THRESHOLD
        self.model_source = config.ML_MODEL_SOURCE
        self.model_name = config.ML_MODEL_NAME
        self.model_type = config.ML_MODEL_TYPE
        
        # Determine which model to use
        self.use_fire_detect_nn = (self.model_type == "fire-detect-nn" or self.model_source == "fire-detect-nn")
        
        if self.use_fire_detect_nn:
            # Load fire-detect-nn model
            self.model, self.device = self._load_fire_detect_nn()
            print(f"fire-detect-nn model initialized (DenseNet121)")
        else:
            # Load Ultralytics YOLOv8 model
            self.model = self._load_model()
            print(f"Fire detection model initialized: {self.model_name}")
        
        print(f"Confidence threshold: {self.confidence_threshold}, IOU threshold: {self.iou_threshold}")
    
    def _load_fire_detect_nn(self):
        """Load fire-detect-nn model by importing from installed package or local directory."""
        try:
            import torch
            import site
            
            # Try to import from installed package first
            try:
                import fire_detect_nn
                # Get the installed package path
                fire_detect_nn_path = Path(fire_detect_nn.__file__).parent
                from fire_detect_nn.models import FireClassifier
                from fire_detect_nn.datasets.combo import transform as fire_transform
                weights_path = fire_detect_nn_path / "weights" / "firedetect-densenet121-pretrained.pt"
                print(f"Using fire-detect-nn from installed package: {fire_detect_nn_path}")
            except ImportError:
                # Fall back to local directory (for backwards compatibility)
                fire_detect_dir = project_root / config.FIRE_DETECT_NN_DIR
                if not fire_detect_dir.exists():
                    raise FileNotFoundError(
                        f"fire-detect-nn not found in site-packages or local directory.\n"
                        f"Run: python3 scripts/install_fire_detect_nn.py"
                    )
                sys.path.insert(0, str(fire_detect_dir))
                from models import FireClassifier
                from datasets.combo import transform as fire_transform
                weights_path = project_root / config.FIRE_DETECT_NN_WEIGHTS
                print(f"Using fire-detect-nn from local directory: {fire_detect_dir}")
            
            if not weights_path.exists():
                raise FileNotFoundError(
                    f"fire-detect-nn weights not found: {weights_path}\n"
                    f"Run: python3 scripts/install_fire_detect_nn.py to download weights"
                )
            
            print(f"Loading fire-detect-nn model from: {weights_path}")
            
            # Use FireClassifier from the repository (DenseNet121 with binary classification)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = FireClassifier(backbone='densenet121', pretrained=False)
            
            # Load pretrained weights
            state_dict = torch.load(weights_path, map_location=device)
            model.load_state_dict(state_dict)
            model.eval()
            model.to(device)
            
            # Store transform for preprocessing
            self.fire_transform = fire_transform
            
            # Enable gradient computation for GradCAM (even though model is in eval mode)
            # We'll compute gradients manually when needed
            
            print(f"✓ fire-detect-nn model loaded successfully on {device}")
            return model, device
            
        except ImportError as e:
            raise ImportError(
                f"Required modules not found. Make sure fire-detect-nn is installed.\n"
                f"Run: python3 scripts/install_fire_detect_nn.py\n"
                f"Original error: {e}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load fire-detect-nn model: {e}")
    
    def _load_model(self) -> YOLO:
        """Load YOLO model from local path or Hugging Face."""
        try:
            if self.model_source == "local" and os.path.exists(self.model_path):
                # Load from local file
                print(f"Loading model from local path: {self.model_path}")
                model = YOLO(self.model_path)
                self._print_model_info(model)
                return model
            elif self.model_source == "huggingface":
                # Try to load from Hugging Face Hub
                print(f"Attempting to load from Hugging Face: {self.model_name}")
                try:
                    model = YOLO(self.model_name)
                    self._print_model_info(model)
                    # Try to save locally for future use
                    try:
                        os.makedirs(os.path.dirname(self.model_path) if os.path.dirname(self.model_path) else "models", exist_ok=True)
                        model.save(self.model_path)
                        print(f"Model saved to: {self.model_path}")
                    except:
                        pass
                    return model
                except Exception as hf_error:
                    print(f"⚠️  Could not load from Hugging Face: {hf_error}")
                    print(f"   Model '{self.model_name}' may not exist or be accessible")
                    # Fall through to try local file or default
            else:
                # Try to download from Hugging Face and save locally
                print(f"Attempting to download from Hugging Face: {self.model_name}")
                try:
                    model = YOLO(self.model_name)
                    self._print_model_info(model)
                    os.makedirs(os.path.dirname(self.model_path) if os.path.dirname(self.model_path) else "models", exist_ok=True)
                    model.save(self.model_path)
                    print(f"Model saved to: {self.model_path}")
                    return model
                except Exception as dl_error:
                    print(f"⚠️  Could not download model: {dl_error}")
            
            # Try local file as fallback
            if os.path.exists(self.model_path):
                print(f"Using local model file: {self.model_path}")
                model = YOLO(self.model_path)
                self._print_model_info(model)
                return model
            
            # Final fallback - raise error instead of using non-fire-detection model
            raise ValueError(
                f"Could not load YOLOv8 model from any source.\n"
                f"  Tried: {self.model_path}, {self.model_name}\n"
                f"  To fix:\n"
                f"  1. Set ML_MODEL_TYPE=fire-detect-nn (recommended, default)\n"
                f"  2. Or provide a valid fire detection YOLOv8 model\n"
                f"  3. Set ML_MODEL_SOURCE=local and ML_MODEL_PATH to your model file"
            )
            
        except Exception as e:
            raise ValueError(
                f"Error loading YOLOv8 model: {e}\n"
                f"  To fix:\n"
                f"  1. Set ML_MODEL_TYPE=fire-detect-nn (recommended, default)\n"
                f"  2. Or provide a valid fire detection YOLOv8 model\n"
                f"  3. Set ML_MODEL_SOURCE=local and ML_MODEL_PATH to your model file"
            ) from e
    
    def _print_model_info(self, model: YOLO):
        """Print information about the loaded model."""
        try:
            if hasattr(model, 'names') and model.names:
                classes = list(model.names.values())
                fire_classes = [c for c in classes if any(kw in c.lower() for kw in ['fire', 'smoke', 'flame', 'burn'])]
                print(f"   Model classes: {len(classes)} total")
                if fire_classes:
                    print(f"   ✓ Fire-related classes found: {fire_classes}")
                else:
                    print(f"   ⚠️  No fire-related classes found in model!")
                    print(f"   ⚠️  This model may not be suitable for fire detection")
                    print(f"   ⚠️  First few classes: {classes[:10]}")
        except:
            pass
    
    def predict(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Predict if frame contains fire using the configured model.
        
        Args:
            frame: Input frame as numpy array (BGR format from OpenCV)
        
        Returns:
            Dictionary with prediction results including bounding boxes
        """
        # Use fire-detect-nn if configured
        if self.use_fire_detect_nn:
            return self._predict_fire_detect_nn(frame)
        
        # Otherwise use Ultralytics YOLOv8
        try:
            # YOLO expects RGB format, so convert from BGR
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Run inference
            # Use lower confidence for model.predict to see all detections
            # We'll filter by fire classes and threshold later
            inference_conf = min(0.1, self.confidence_threshold)  # Lower threshold to see more
            results = self.model.predict(
                frame_rgb,
                conf=inference_conf,
                iou=self.iou_threshold,
                verbose=False,
                imgsz=640  # YOLOv8 standard input size
            )
            
            # Process results
            detections = []
            max_confidence = 0.0
            has_fire = False
            all_detections_debug = []  # For debugging
            
            for result in results:
                boxes = result.boxes
                
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        # Get box coordinates (xyxy format)
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        confidence = float(box.conf[0].cpu().numpy())
                        class_id = int(box.cls[0].cpu().numpy())
                        class_name = result.names[class_id] if hasattr(result, 'names') else f"class_{class_id}"
                        
                        # Store all detections for debugging (first 10 frames only)
                        all_detections_debug.append((class_name, confidence))
                        
                        # Check if this is a fire-related detection
                        # Common fire-related class names: fire, smoke, flame, etc.
                        # Exclude false positives like "fire hydrant", "fire truck", etc.
                        fire_keywords = ['fire', 'smoke', 'flame', 'burn', 'wildfire']
                        exclude_keywords = ['hydrant', 'truck', 'extinguisher', 'alarm', 'station', 'engine']
                        
                        class_lower = class_name.lower()
                        is_fire_class = any(keyword in class_lower for keyword in fire_keywords)
                        is_excluded = any(exclude in class_lower for exclude in exclude_keywords)
                        
                        # Only consider it fire if:
                        # 1. The class name contains fire keywords AND
                        # 2. It's not an excluded class (like "fire hydrant") AND
                        # 3. The confidence is above threshold
                        if is_fire_class and not is_excluded and confidence > self.confidence_threshold:
                            has_fire = True
                            max_confidence = max(max_confidence, confidence)
                            
                            detections.append({
                                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                                "confidence": float(confidence),
                                "class": class_name,
                                "class_id": class_id
                            })
            
            # Debug output (only for first few frames to avoid spam)
            import os
            debug_file = os.getenv("DEBUG_DETECTIONS", "")
            if debug_file or (hasattr(self, '_debug_frame_count') and self._debug_frame_count < 5):
                if not hasattr(self, '_debug_frame_count'):
                    self._debug_frame_count = 0
                if self._debug_frame_count < 5:
                    if all_detections_debug:
                        print(f"   [DEBUG] Frame detections: {[(c, f'{conf:.1%}') for c, conf in all_detections_debug[:5]]}")
                    else:
                        print(f"   [DEBUG] No detections in frame (threshold: {inference_conf})")
                self._debug_frame_count += 1
            
            return {
                "has_fire": bool(has_fire),
                "fire_probability": float(max_confidence) if has_fire else 0.0,
                "detections": detections,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            print(f"Error during prediction: {e}")
            # Return safe default on error
            return {
                "has_fire": False,
                "fire_probability": 0.0,
                "detections": [],
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            }
    
    def _compute_gradcam_heatmap(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Compute GradCAM heatmap for fire region visualization.
        
        Args:
            frame: Input frame as numpy array (BGR format from OpenCV)
        
        Returns:
            2D numpy array heatmap, or None if computation fails
        """
        try:
            import torch
            from PIL import Image
            
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Convert to PIL Image and apply fire-detect-nn transform
            pil_image = Image.fromarray(frame_rgb)
            input_tensor = self.fire_transform(pil_image).unsqueeze(0).to(self.device)
            input_tensor.requires_grad = True
            
            # Get activations from the last feature layer before classifier
            # For DenseNet121, this is the features output
            activations = None
            gradients = None
            
            def forward_hook(module, input, output):
                nonlocal activations
                activations = output
            
            def backward_hook(module, grad_input, grad_output):
                nonlocal gradients
                if grad_output[0] is not None:
                    gradients = grad_output[0]
            
            # Register hooks on the features layer (before global pooling)
            # DenseNet121 backbone has a 'features' attribute
            hook_handle = None
            grad_handle = None
            
            if hasattr(self.model.backbone, 'features'):
                # Hook into the features output (before global pooling)
                features_layer = self.model.backbone.features
                hook_handle = features_layer.register_forward_hook(forward_hook)
                grad_handle = features_layer.register_backward_hook(backward_hook)
            
            # Forward pass (need to enable gradients)
            self.model.train()  # Temporarily enable training mode for gradients
            output = self.model(input_tensor)
            fire_score = output[0]
            
            # Backward pass
            self.model.zero_grad()
            fire_score.backward(retain_graph=False)
            self.model.eval()  # Back to eval mode
            
            # Compute GradCAM
            if activations is not None and gradients is not None:
                # activations shape: [batch, channels, height, width]
                # gradients shape: [batch, channels, height, width]
                
                # Pool gradients across spatial dimensions
                pooled_gradients = torch.mean(gradients, dim=[0, 2, 3], keepdim=True)
                
                # Weight activations by gradients
                weighted_activations = activations * pooled_gradients
                
                # Average over channels
                heatmap = torch.mean(weighted_activations, dim=1, keepdim=False)
                heatmap = heatmap[0].cpu().detach().numpy()  # Remove batch dimension
                
                # Apply ReLU
                heatmap = np.maximum(heatmap, 0)
                
                # Normalize
                if heatmap.max() > 0:
                    heatmap = heatmap / heatmap.max()
                
                # Remove hooks
                if hook_handle is not None:
                    hook_handle.remove()
                if grad_handle is not None:
                    grad_handle.remove()
                
                return heatmap
            
            # Clean up hooks if computation failed
            if hook_handle is not None:
                hook_handle.remove()
            if grad_handle is not None:
                grad_handle.remove()
            
            return None
            
        except Exception as e:
            # Silently fail - heatmap is optional
            # Reset model to eval mode
            try:
                self.model.eval()
            except:
                pass
            return None
    
    def _predict_fire_detect_nn(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Predict using fire-detect-nn model (imported from GitHub repository).
        
        This is a binary classification model (fire/no-fire), so we return
        a full-frame detection if fire probability exceeds threshold.
        Also computes GradCAM heatmap for visual fire identification.
        
        Args:
            frame: Input frame as numpy array (BGR format from OpenCV)
        
        Returns:
            Dictionary with prediction results including heatmap
        """
        try:
            import torch
            from PIL import Image
            
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Convert to PIL Image and apply fire-detect-nn transform
            # (uses custom normalization: mean=(0.4005, 0.3702, 0.3419), std=(0.2858, 0.2749, 0.2742))
            pil_image = Image.fromarray(frame_rgb)
            input_tensor = self.fire_transform(pil_image).unsqueeze(0).to(self.device)
            
            # Run inference
            # FireClassifier outputs a single value (0-1) after sigmoid, where higher = more fire
            with torch.no_grad():
                output = self.model(input_tensor)
                fire_prob = float(output[0].cpu().numpy())  # Single value, already sigmoid (0-1)
                no_fire_prob = 1.0 - fire_prob
            
            # Check if fire probability exceeds threshold
            has_fire = fire_prob >= self.confidence_threshold
            
            # Compute heatmap if fire detected (for visual identification)
            heatmap = None
            if has_fire:
                try:
                    heatmap = self._compute_gradcam_heatmap(frame)
                except Exception as e:
                    # Heatmap is optional, continue without it
                    pass
            
            # For classification models, we create a full-frame detection
            # since there are no bounding boxes
            detections = []
            if has_fire:
                h, w = frame.shape[:2]
                detections.append({
                    "bbox": [0, 0, w, h],  # Full frame
                    "confidence": fire_prob,
                    "class": "fire",
                    "class_id": 1
                })
            
            return {
                "has_fire": bool(has_fire),
                "fire_probability": float(fire_prob) if has_fire else 0.0,
                "detections": detections,
                "timestamp": datetime.utcnow().isoformat(),
                "model_type": "fire-detect-nn",
                "no_fire_probability": float(no_fire_prob),
                "heatmap": heatmap  # GradCAM heatmap for visual fire identification
            }
        
        except Exception as e:
            print(f"Error in fire-detect-nn prediction: {e}")
            import traceback
            traceback.print_exc()
            return {
                "has_fire": False,
                "fire_probability": 0.0,
                "detections": [],
                "timestamp": datetime.utcnow().isoformat(),
                "model_type": "fire-detect-nn",
                "error": str(e)
            }


def convert_numpy_types(obj):
    """Recursively convert numpy types to native Python types for JSON serialization."""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_numpy_types(item) for item in obj)
    else:
        return obj


class FireDetectionStream:
    """Kafka Streams application for fire detection."""
    
    def __init__(self):
        """Initialize the stream processor."""
        self.consumer = KafkaConsumer(
            config.KAFKA_VIDEO_TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            key_deserializer=lambda k: k.decode('utf-8') if k else None,
            group_id="fire-detection-stream",  # Multiple consumers with same group_id share partitions
            auto_offset_reset='earliest',  # Read from beginning if no offset exists
            enable_auto_commit=True,
            consumer_timeout_ms=5000,  # Wait 5 seconds for messages before timing out
            max_poll_records=100,  # Process up to 100 records per poll for better throughput
            fetch_min_bytes=1024,  # Wait for at least 1KB before returning
            fetch_max_wait_ms=500  # Max wait time for fetch
        )
        
        self.producer = KafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks='all'
        )
        
        self.model = FireDetectionModel()
        self.detections_topic = config.KAFKA_DETECTIONS_TOPIC
        self.video_completions_topic = config.KAFKA_VIDEO_COMPLETIONS_TOPIC
        
        # Track video state for incremental writing
        self.current_video_id = None
        self.video_writer = None  # OpenCV VideoWriter for current video
        self.video_fps = None
        self.video_width = None
        self.video_height = None
        self.video_filepath = None
        self.video_frame_count = 0
        self.video_start_timestamp = None  # First frame timestamp for filename
        self.last_frame_number = None  # Track last frame number to detect video end
        self.video_stats = {}  # Track stats per video: {video_id: {"frames": count, "fires": count, "max_prob": float}}
    
    def decode_frame(self, frame_data: str) -> np.ndarray:
        """Decode base64 frame data to numpy array."""
        frame_bytes = base64.b64decode(frame_data)
        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return frame
    
    def _initialize_video_writer(self, video_id: str, width: int, height: int, fps: float) -> Optional[str]:
        """Initialize video writer for a new video."""
        # Don't re-initialize if writer already exists
        if self.video_writer is not None:
            return self.video_filepath
            
        try:
            # Generate output path using the first frame timestamp
            timestamp_str = self.video_start_timestamp.replace(":", "-").replace(".", "-") if self.video_start_timestamp else datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
            output_dir = config.CLIP_STORAGE_PATH
            os.makedirs(output_dir, exist_ok=True)
            filename = f"{video_id}_with_heatmaps.mp4"
            filepath = os.path.join(output_dir, filename)
            
            # Create video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(filepath, fourcc, fps, (width, height))
            
            if not self.video_writer.isOpened():
                print(f"Error: Could not open video writer for {filepath}")
                self.video_writer = None
                return None
            
            self.video_filepath = filepath
            self.video_frame_count = 0
            print(f"📹 Started writing video: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"Error initializing video writer: {e}")
            import traceback
            traceback.print_exc()
            self.video_writer = None
            return None
    
    def _publish_video_completion(self, video_id: str, local_filepath: str, stats: Dict[str, Any], video_metadata: Dict[str, Any]):
        """Publish video completion event to Kafka for S3 upload consumer."""
        try:
            completion_event = {
                "video_id": video_id,
                "local_filepath": local_filepath,
                "timestamp": datetime.utcnow().isoformat(),
                "stats": stats,
                "video_metadata": video_metadata
            }
            
            future = self.producer.send(
                self.video_completions_topic,
                key=video_id,
                value=completion_event
            )
            future.get(timeout=10)
            print(f"📤 Published video completion event for {video_id}")
        except Exception as e:
            print(f"⚠️  Error publishing video completion: {e}")
    
    def _close_video_writer(self, print_summary: bool = True) -> Optional[str]:
        """Close the current video writer and publish completion event for S3 upload."""
        if self.video_writer is not None:
            try:
                self.video_writer.release()
                filepath = self.video_filepath
                frame_count = self.video_frame_count
                video_id = self.current_video_id
                
                # Get stats
                stats = self.video_stats.get(video_id, {})
                fire_count = stats.get("fires", 0)
                total_frames = stats.get("frames", frame_count)
                max_prob = stats.get("max_prob", 0.0)
                
                # Publish video completion event for S3 upload consumer
                if video_id and filepath and os.path.exists(filepath):
                    self._publish_video_completion(
                        video_id,
                        filepath,
                        {
                            "total_frames": total_frames,
                            "fire_count": fire_count,
                            "max_fire_probability": max_prob
                        },
                        {
                            "fps": self.video_fps,
                            "width": self.video_width,
                            "height": self.video_height,
                            "frame_count": frame_count
                        }
                    )
                
                # Print summary if requested
                if print_summary and video_id:
                    print(f"\n{'='*60}")
                    print(f"📹 Video Complete: {video_id}")
                    print(f"{'='*60}")
                    print(f"  Local file: {filepath}")
                    print(f"  Total frames: {total_frames}")
                    print(f"  Frames with fire: {fire_count}")
                    print(f"  Max fire probability: {max_prob:.2%}")
                    if fire_count == 0:
                        print(f"  Result: ✅ No fires detected")
                    else:
                        print(f"  Result: 🔥 Fire detected in {fire_count} frame(s)")
                    print(f"  → Published to {self.video_completions_topic} for S3 upload")
                    print(f"{'='*60}\n")
                
                self.video_writer = None
                self.video_filepath = None
                self.video_frame_count = 0
                return filepath
            except Exception as e:
                print(f"Error closing video writer: {e}")
                import traceback
                traceback.print_exc()
                self.video_writer = None
                self.video_filepath = None
                return None
        return None
    
    def _reset_video_state(self, video_id: str, timestamp: str, frame_number: int):
        """Reset video state when video changes."""
        if video_id != self.current_video_id:
            # Close previous video writer if it exists
            if self.current_video_id is not None:
                self._close_video_writer(print_summary=True)
            
            # Reset for new video
            self.current_video_id = video_id
            self.video_fps = None
            self.video_width = None
            self.video_height = None
            self.video_start_timestamp = timestamp  # Store first frame timestamp
            self.last_frame_number = None
            
            # Initialize stats for new video
            if video_id not in self.video_stats:
                self.video_stats[video_id] = {"frames": 0, "fires": 0, "max_prob": 0.0}
    
    def _overlay_heatmap_on_frame(self, frame: np.ndarray, heatmap: Optional[np.ndarray], 
                                   alpha: float = None) -> np.ndarray:
        """
        Overlay heatmap on frame for visualization.
        
        Args:
            frame: Input frame (BGR format)
            heatmap: 2D heatmap array, or None
            alpha: Transparency of heatmap overlay (0.0-1.0), None to use config value
        
        Returns:
            Frame with heatmap overlaid
        """
        if heatmap is None:
            return frame
        
        if alpha is None:
            alpha = config.CLIP_HEATMAP_OVERLAY_ALPHA
        
        # Resize heatmap to match frame dimensions
        h, w = frame.shape[:2]
        heatmap_resized = cv2.resize(heatmap, (w, h))
        
        # Normalize heatmap to 0-255
        heatmap_norm = (heatmap_resized - heatmap_resized.min()) / (heatmap_resized.max() - heatmap_resized.min() + 1e-8)
        heatmap_uint8 = (heatmap_norm * 255).astype(np.uint8)
        
        # Apply colormap (JET for fire-like colors: blue->green->yellow->red)
        heatmap_colored = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_JET)
        
        # Overlay heatmap on frame
        frame_with_heatmap = cv2.addWeighted(frame, 1.0 - alpha, heatmap_colored, alpha, 0)
        
        return frame_with_heatmap
    
    
    def process_frame(self, message_value: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single frame through the ML model."""
        try:
            # Decode frame
            frame = self.decode_frame(message_value["frame_data"])
            
            # Get frame metadata
            video_id = message_value["video_id"]
            frame_number = int(message_value["frame_number"])  # Ensure it's an int
            timestamp = message_value["timestamp"]
            fps = message_value.get("fps", 30.0)
            width = message_value.get("width")
            height = message_value.get("height")
            
            # Check if video ended (large gap in frame numbers suggests video finished)
            if self.current_video_id == video_id and self.last_frame_number is not None:
                frame_gap = frame_number - self.last_frame_number
                # If gap is more than 30 frames (1 second at 30fps), likely video ended
                if frame_gap > 30:
                    print(f"⚠️  Detected gap of {frame_gap} frames - closing video {video_id}")
                    self._close_video_writer(print_summary=True)
                    # Reset state for new video (or continuation)
                    self._reset_video_state(video_id, timestamp, frame_number)
            
            # Reset state if video changed
            if video_id != self.current_video_id:
                self._reset_video_state(video_id, timestamp, frame_number)
            
            # Update last frame number
            self.last_frame_number = frame_number
            
            # Store video metadata and initialize writer if needed
            if self.video_fps is None:
                self.video_fps = fps
            if self.video_width is None and width:
                self.video_width = width
            if self.video_height is None and height:
                self.video_height = height
            
            # Initialize video writer if not already open (only once per video)
            if self.video_writer is None and self.video_width and self.video_height:
                self._initialize_video_writer(
                    video_id,
                    self.video_width, self.video_height, 
                    self.video_fps
                )
            
            # Run inference to get heatmap (for fire-detect-nn)
            prediction = self.model.predict(frame)
            
            # Update video statistics
            if video_id in self.video_stats:
                self.video_stats[video_id]["frames"] += 1
                if prediction["has_fire"]:
                    self.video_stats[video_id]["fires"] += 1
                    self.video_stats[video_id]["max_prob"] = max(
                        self.video_stats[video_id]["max_prob"],
                        prediction["fire_probability"]
                    )
            
            # Get heatmap if available
            heatmap = prediction.get("heatmap")
            
            # Overlay heatmap on frame if available
            processed_frame = frame.copy()
            if heatmap is not None:
                processed_frame = self._overlay_heatmap_on_frame(processed_frame, heatmap)
            
            # Write frame directly to video file (incremental writing)
            if self.video_writer is not None:
                self.video_writer.write(processed_frame)
                self.video_frame_count += 1
            
            # Create detection result
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
                    "fps": fps
                }
            }
            
            # Convert all numpy types to native Python types for JSON serialization
            detection_result = convert_numpy_types(detection_result)
            
            return detection_result
            
        except Exception as e:
            print(f"Error processing frame: {e}")
            return None
    
    def run(self):
        """Run the stream processor."""
        print(f"Starting fire detection stream processor...")
        print(f"Consuming from topic: {config.KAFKA_VIDEO_TOPIC}")
        print(f"Publishing to topic: {config.KAFKA_DETECTIONS_TOPIC}")
        print(f"Waiting for messages... (Press Ctrl+C to stop)\n")
        
        message_count = 0
        detection_count = 0
        fire_count = 0
        
        try:
            for message in self.consumer:
                message_count += 1
                video_id = message.key
                frame_data = message.value
                
                if message_count % 10 == 0:  # Print every 10th frame to reduce noise
                    print(f"Processed {message_count} frames... (latest: frame {frame_data.get('frame_number')} from video {video_id})")
                
                # Process frame
                detection_result = self.process_frame(frame_data)
                
                if detection_result:
                    detection_count += 1
                    
                    # Only send if fire detected or for all frames (configurable)
                    if detection_result["has_fire"]:
                        fire_count += 1
                        print(f"🔥 Fire detected! Frame {frame_data.get('frame_number')} from video {video_id} - Probability: {detection_result['fire_probability']:.2%}")
                    
                    # Send ALL detection results to topic (not just fires)
                    # This allows tracking of all processed frames
                    future = self.producer.send(
                        self.detections_topic,
                        key=video_id,
                        value=detection_result
                    )
                    
                    try:
                        record_metadata = future.get(timeout=10)
                        if detection_result["has_fire"]:
                            print(f"  → Detection sent to topic {record_metadata.topic} partition {record_metadata.partition}")
                    except KafkaError as e:
                        print(f"Error sending detection: {e}")
                else:
                    print(f"⚠️  Failed to process frame {frame_data.get('frame_number')} from video {video_id}")
            
            # If we exit the loop (timeout or end of messages), close current video
            if self.video_writer is not None:
                print("\n⚠️  No more messages - closing current video...")
                self._close_video_writer(print_summary=True)
        
        except KeyboardInterrupt:
            print(f"\n\nStopping stream processor...")
            # Close final video if processing
            if self.video_writer is not None:
                print("Closing final video...")
                self._close_video_writer()
            print(f"Summary: Processed {message_count} messages, {detection_count} detections, {fire_count} fires")
        except Exception as e:
            print(f"\nError in stream processor: {e}")
            # Close video even on error
            if self.video_writer is not None:
                try:
                    self._close_video_writer()
                except:
                    pass
            import traceback
            traceback.print_exc()
        finally:
            # Close any remaining video writer
            if self.video_writer is not None:
                try:
                    self._close_video_writer()
                except:
                    pass
            self.consumer.close()
            self.producer.flush()
            self.producer.close()
            print(f"Final summary: {message_count} messages processed, {detection_count} detections created, {fire_count} fires detected")


if __name__ == "__main__":
    stream = FireDetectionStream()
    stream.run()

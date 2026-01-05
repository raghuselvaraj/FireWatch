# FireWatch Unit Tests

This directory contains unit tests for the FireWatch codebase.

## Running Tests

### Run all tests:
```bash
pytest
```

### Run with coverage:
```bash
pytest --cov=. --cov-report=html
```

### Run specific test file:
```bash
pytest tests/test_video_producer.py
```

### Run specific test:
```bash
pytest tests/test_video_producer.py::TestVideoProducer::test_encode_frame
```

### Run with verbose output:
```bash
pytest -v
```

## Test Structure

- `test_utils.py` - Utility function tests (convert_numpy_types, etc.)
- `test_video_producer.py` - VideoProducer class tests
- `test_fire_detection_stream.py` - FireDetectionStream class tests
- `test_s3_upload_consumer.py` - S3UploadConsumer class tests
- `test_model_loading.py` - Model loading tests
- `conftest.py` - Pytest fixtures and configuration

## Test Coverage

Current test coverage includes:
- ✅ Utility functions (convert_numpy_types)
- ✅ VideoProducer (frame encoding, video processing)
- ✅ FireDetectionStream (frame decoding, video writing, heatmap overlay)
- ✅ S3VideoUploader (upload logic, error handling)
- ✅ S3VideoConsumer (message processing)
- ✅ Model loading (fire-detect-nn and YOLOv8)

## Writing New Tests

1. Create test file: `tests/test_<module_name>.py`
2. Import pytest and the module to test
3. Use fixtures from `conftest.py` for common mocks
4. Follow naming convention: `test_<function_name>`
5. Use descriptive docstrings

Example:
```python
def test_encode_frame(self, producer, sample_frame):
    """Test frame encoding to base64."""
    # Test implementation
    pass
```

## Mocking External Dependencies

Tests use mocks for:
- Kafka producers/consumers
- S3 clients
- ML models
- File I/O
- Network calls

This allows tests to run without:
- Actual Kafka cluster
- AWS credentials
- ML model files
- Test video files

## Continuous Integration

Tests should be run in CI/CD pipeline:
```yaml
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest --cov=. --cov-report=xml
```


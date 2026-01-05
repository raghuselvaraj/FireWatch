"""Tests for utility functions."""
import pytest
import numpy as np
from streams.fire_detection_stream import convert_numpy_types


class TestConvertNumpyTypes:
    """Tests for convert_numpy_types utility function."""
    
    def test_convert_numpy_int64(self):
        """Test conversion of numpy int64 to Python int."""
        value = np.int64(42)
        result = convert_numpy_types(value)
        assert isinstance(result, int)
        assert result == 42
    
    def test_convert_numpy_float64(self):
        """Test conversion of numpy float64 to Python float."""
        value = np.float64(3.14)
        result = convert_numpy_types(value)
        assert isinstance(result, float)
        assert result == 3.14
    
    def test_convert_numpy_array(self):
        """Test conversion of numpy array to list."""
        value = np.array([1, 2, 3])
        result = convert_numpy_types(value)
        assert isinstance(result, list)
        assert result == [1, 2, 3]
    
    def test_convert_numpy_array_2d(self):
        """Test conversion of 2D numpy array."""
        value = np.array([[1, 2], [3, 4]])
        result = convert_numpy_types(value)
        assert isinstance(result, list)
        assert result == [[1, 2], [3, 4]]
    
    def test_convert_dict_with_numpy(self):
        """Test conversion of dict containing numpy types."""
        value = {
            "frame_number": np.int64(100),
            "confidence": np.float64(0.85),
            "bbox": np.array([10, 20, 30, 40])
        }
        result = convert_numpy_types(value)
        assert isinstance(result["frame_number"], int)
        assert isinstance(result["confidence"], float)
        assert isinstance(result["bbox"], list)
        assert result["frame_number"] == 100
        assert result["confidence"] == 0.85
        assert result["bbox"] == [10, 20, 30, 40]
    
    def test_convert_list_with_numpy(self):
        """Test conversion of list containing numpy types."""
        value = [np.int64(1), np.float64(2.5), np.array([3, 4])]
        result = convert_numpy_types(value)
        assert isinstance(result[0], int)
        assert isinstance(result[1], float)
        assert isinstance(result[2], list)
    
    def test_convert_nested_structure(self):
        """Test conversion of nested structures."""
        value = {
            "detections": [
                {
                    "bbox": np.array([10, 20, 30, 40]),
                    "confidence": np.float64(0.9)
                }
            ],
            "frame_number": np.int64(5)
        }
        result = convert_numpy_types(value)
        assert isinstance(result["detections"][0]["bbox"], list)
        assert isinstance(result["detections"][0]["confidence"], float)
        assert isinstance(result["frame_number"], int)
    
    def test_convert_python_types_unchanged(self):
        """Test that Python native types remain unchanged."""
        value = {
            "string": "test",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"key": "value"}
        }
        result = convert_numpy_types(value)
        assert result == value
    
    def test_convert_none(self):
        """Test that None values are preserved."""
        assert convert_numpy_types(None) is None
    
    def test_convert_tuple(self):
        """Test conversion of tuple containing numpy types."""
        value = (np.int64(1), np.float64(2.5))
        result = convert_numpy_types(value)
        assert isinstance(result, tuple)
        assert isinstance(result[0], int)
        assert isinstance(result[1], float)


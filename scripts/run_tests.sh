#!/bin/bash
# Script to run unit tests with coverage

set -e

echo "=========================================="
echo "FireWatch Unit Tests"
echo "=========================================="
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "⚠️  pytest not found. Installing..."
    pip install pytest pytest-cov pytest-mock
fi

# Run tests
echo "Running unit tests..."
echo ""

pytest tests/ \
    -v \
    --cov=. \
    --cov-report=term-missing \
    --cov-report=html \
    --cov-exclude="*/tests/*" \
    --cov-exclude="*/fire-detect-nn/*" \
    --cov-exclude="*/infrastructure/*" \
    "$@"

echo ""
echo "=========================================="
echo "Test Coverage Report"
echo "=========================================="
echo ""
echo "HTML coverage report: htmlcov/index.html"
echo ""
echo "To view coverage report:"
echo "  open htmlcov/index.html"
echo ""


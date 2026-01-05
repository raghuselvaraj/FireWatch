"""
Setup script for FireWatch that installs dependencies and fire-detect-nn.
Run: pip install -e .  or  python setup.py install
"""
from setuptools import setup, find_packages
from setuptools.command.install import install
from pathlib import Path
import subprocess
import sys

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    with open(requirements_path) as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

# Remove the comment line about fire-detect-nn
requirements = [r for r in requirements if "fire-detect-nn" not in r.lower()]


class PostInstallCommand(install):
    """Post-installation command to install fire-detect-nn."""
    def run(self):
        install.run(self)
        # Install fire-detect-nn after main package installation
        try:
            script_path = Path(__file__).parent / "scripts" / "install_fire_detect_nn.py"
            if script_path.exists():
                print("\n" + "="*60)
                print("Installing fire-detect-nn to site-packages...")
                print("="*60)
                subprocess.run([sys.executable, str(script_path)], check=True)
        except Exception as e:
            print(f"Warning: Could not automatically install fire-detect-nn: {e}")
            print("Please run manually: python3 scripts/install_fire_detect_nn.py")


setup(
    name="firewatch",
    version="0.1.0",
    description="Real-time forest fire detection using Kafka and ML",
    author="FireWatch Team",
    packages=find_packages(exclude=["fire-detect-nn", "test_files", "clips", "logs"]),
    install_requires=requirements,
    python_requires=">=3.8",
    cmdclass={
        'install': PostInstallCommand,
    },
    entry_points={
        "console_scripts": [
            "firewatch-stream=streams.fire_detection_stream:main",
            "firewatch-producer=producer.video_producer:main",
            "firewatch-s3-upload=consumer.s3_video_consumer:main",
        ],
    },
)


"""
Install fire-detect-nn as a Python package in site-packages.
This allows importing it from anywhere without adding to sys.path.
"""
import os
import sys
import subprocess
import site
from pathlib import Path
import urllib.request
import shutil

def get_site_packages_dir():
    """Get the site-packages directory for the current Python environment."""
    # Get site-packages directories
    site_packages = site.getsitepackages()
    if site_packages:
        return Path(site_packages[0])
    # Fallback: use user site-packages
    user_site = site.getusersitepackages()
    if user_site:
        return Path(user_site)
    # Last resort: use venv/lib/pythonX.X/site-packages
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    venv_lib = Path(sys.prefix) / "lib" / f"python{python_version}" / "site-packages"
    if venv_lib.exists():
        return venv_lib
    raise RuntimeError("Could not determine site-packages directory")

def install_fire_detect_nn():
    """Install fire-detect-nn to site-packages."""
    site_packages = get_site_packages_dir()
    fire_detect_nn_dir = site_packages / "fire_detect_nn"
    
    print(f"Installing fire-detect-nn to: {fire_detect_nn_dir}")
    print(f"Site-packages: {site_packages}")
    
    # Clone repository if needed
    if not fire_detect_nn_dir.exists():
        print("\nCloning fire-detect-nn repository...")
        temp_dir = Path("/tmp") / "fire-detect-nn-temp"
        
        # Clean up temp dir if it exists
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        
        try:
            subprocess.run(
                ["git", "clone", "https://github.com/tomasz-lewicki/fire-detect-nn.git", str(temp_dir)],
                check=True,
                capture_output=True,
                text=True
            )
            print("✓ Repository cloned")
            
            # Move to site-packages
            shutil.move(str(temp_dir), str(fire_detect_nn_dir))
            print(f"✓ Moved to site-packages: {fire_detect_nn_dir}")
            
        except subprocess.CalledProcessError as e:
            print(f"✗ Error cloning repository: {e.stderr}")
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            return False
        except FileNotFoundError:
            print("✗ Git not found. Please install git first.")
            return False
        except Exception as e:
            print(f"✗ Error: {e}")
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            return False
    else:
        print(f"✓ Repository already exists at: {fire_detect_nn_dir}")
    
    # Download weights if needed
    weights_dir = fire_detect_nn_dir / "weights"
    weights_file = weights_dir / "firedetect-densenet121-pretrained.pt"
    
    if not weights_file.exists():
        print("\nDownloading pretrained weights...")
        weights_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            url = "https://dl.dropbox.com/s/6t17srif65vzqfn/firedetect-densenet121-pretrained.pt"
            print(f"Downloading from: {url}")
            urllib.request.urlretrieve(url, str(weights_file))
            print(f"✓ Weights downloaded to: {weights_file}")
        except Exception as e:
            print(f"⚠️  Could not download weights automatically: {e}")
            print(f"   Please download manually:")
            print(f"   1. Visit: {url}")
            print(f"   2. Save to: {weights_file}")
            return False
    else:
        print(f"✓ Weights already exist at: {weights_file}")
    
    # Create __init__.py if it doesn't exist to make it a proper package
    init_file = fire_detect_nn_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# fire-detect-nn package\n")
        print("✓ Created __init__.py")
    
    print(f"\n✓ fire-detect-nn installed successfully!")
    print(f"   Location: {fire_detect_nn_dir}")
    print(f"   Weights: {weights_file}")
    print(f"\nYou can now import it with: from fire_detect_nn.models import FireClassifier")
    
    return True

if __name__ == "__main__":
    success = install_fire_detect_nn()
    sys.exit(0 if success else 1)


import sys
from pathlib import Path

# Add project root to sys.path so `import build` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

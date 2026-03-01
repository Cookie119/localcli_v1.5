# api/index.py
import sys
import os
from pathlib import Path

# Add the project root to Python path
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

# Import your Flask app from app.py
from app import app

# This is what Vercel looks for
app = app
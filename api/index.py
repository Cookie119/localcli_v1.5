# api/index.py
import sys
import os
from pathlib import Path

# Add project root to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

# Import the create_app function
from app import create_app

# Create the Flask app instance
app = create_app()

# This is what Vercel looks for
# 'app' is now the Flask instance
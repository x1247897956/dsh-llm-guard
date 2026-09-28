"""Unit tests never use local API credentials or contact model services."""
import os

# Set before importing service modules: dotenv must not load the local key in tests.
os.environ["DEEPSEEK_API_KEY"] = ""

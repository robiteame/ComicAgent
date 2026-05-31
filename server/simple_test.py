print("Hello, World!")
print("Testing Python execution...")

import sys
print(f"Python version: {sys.version}")
print(f"Python path: {sys.path}")

import os
print(f"Current directory: {os.getcwd()}")
print(f"Files in current directory: {os.listdir('.')}")

try:
    import fastapi
    print(f"FastAPI version: {fastapi.__version__}")
except ImportError as e:
    print(f"FastAPI import error: {e}")

print("Simple test completed.")
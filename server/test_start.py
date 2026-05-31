import sys
from pathlib import Path

# 添加当前目录到sys.path
sys.path.insert(0, str(Path(__file__).parent))

try:
    print("Testing imports...")
    from config import settings
    print(f"Config loaded: {settings.DATABASE_URL}")

    from db import init_db
    print("DB module imported")

    from api.routes import asset, character, chat, graph, project, render, script, shot
    print("All route modules imported successfully")

    from api.websocket import ws_manager
    print("WebSocket manager imported")

    print("All imports successful!")

except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("\nTesting database initialization...")
    init_db()
    print("Database initialized successfully!")

except Exception as e:
    print(f"Database error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nAll tests passed! The application should start correctly.")
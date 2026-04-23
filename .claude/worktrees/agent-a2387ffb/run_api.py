#!/usr/bin/env python3
"""Run the NEXUS API server."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    import uvicorn
    from api.server import app
    print("\n  NEXUS — AURUM Finance API")
    print("  http://localhost:8000")
    print("  http://localhost:8000/docs\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)

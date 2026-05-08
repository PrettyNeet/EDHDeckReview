"""Launch the MTG Commander Deck Review server."""
import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import uvicorn
from app.agents.ai_advisor import _load_env_file

if __name__ == "__main__":
    print("=" * 60)
    print("  MTG Commander Deck Review")
    print("  http://localhost:8000")
    print("=" * 60)

    # Optionally load provider keys and model defaults from .env
    _load_env_file()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(ROOT / "app"), str(ROOT / "frontend")],
    )

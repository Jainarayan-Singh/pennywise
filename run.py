"""Local development entry point: python run.py"""
import os
from pathlib import Path

from wsgi import app

if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=app.config["DEBUG"],
        # Settings are read once at startup, so also restart when .env changes.
        extra_files=[str(Path(__file__).with_name(".env"))],
    )
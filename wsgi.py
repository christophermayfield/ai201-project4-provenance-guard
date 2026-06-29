"""WSGI entrypoint. Run locally with: python wsgi.py (or: flask --app wsgi run).

Defaults to port 5050 because macOS reserves 5000 for the AirPlay Receiver.
Override with the PORT env var.
"""

import os

from dotenv import load_dotenv

from provenance_guard import create_app

load_dotenv()
app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5050")), debug=True)

"""Fetch a single Panopto session's info + transcript by ID and save to disk."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from panopto_client import PanoptoClient

SESSION_ID = sys.argv[1] if len(sys.argv) > 1 else "3b81fdeb-9bd8-43c6-b61a-b471010b3131"

client = PanoptoClient(
    server=os.getenv("PANOPTO_SERVER", "upenn.hosted.panopto.com"),
    client_id=os.getenv("PANOPTO_CLIENT_ID"),
    client_secret=os.getenv("PANOPTO_CLIENT_SECRET"),
    username=os.getenv("PANOPTO_USERNAME"),
    password=os.getenv("PANOPTO_PASSWORD"),
    cookie=os.getenv("PANOPTO_COOKIE"),
)
client.authenticate()

info = client.get_session_info(SESSION_ID)
print("=== SESSION INFO ===")
for k, v in info.items():
    print(f"{k}: {v}")

transcript = client.get_transcript(SESSION_ID)
print(f"\n=== TRANSCRIPT ({len(transcript)} chars) ===")

out = Path(__file__).resolve().parent.parent / "logs" / "one_transcript.txt"
out.write_text(transcript, encoding="utf-8")
print(f"Saved to: {out}")

# Manual utility — NOT a pytest test (pytest only collects test_*.py).
# Sends a signed fake Cal.com BOOKING_CREATED webhook to a locally running backend
# so the /webhooks/cal flow can be exercised without exposing localhost to Cal.
#
# Usage:
#   Scripts/python.exe tests/manual_cal_webhook.py            # BOOKING_CREATED
#   Scripts/python.exe tests/manual_cal_webhook.py cancel     # then cancel it
#
# Requires CAL_WEBHOOK_SECRET in .env (same value as the Cal dashboard).
import hashlib
import hmac
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()
import os

SECRET = os.getenv("CAL_WEBHOOK_SECRET")
URL = os.getenv("WEBHOOK_TEST_URL", "http://localhost:8000/webhooks/cal")
# Must match a mentors.booking_url prefix in your DB.
CAL_USERNAME = os.getenv("WEBHOOK_TEST_CAL_USERNAME", "yokesh-dhanabal-4hwiui")

if not SECRET:
    sys.exit("CAL_WEBHOOK_SECRET is not set in .env")

uid = sys.argv[2] if len(sys.argv) > 2 else f"test_{uuid.uuid4().hex[:12]}"
mode = sys.argv[1] if len(sys.argv) > 1 else "create"

start = datetime.now(timezone.utc) + timedelta(days=2)
payload = {
    "triggerEvent": "BOOKING_CANCELLED" if mode == "cancel" else "BOOKING_CREATED",
    "payload": {
        "uid": uid,
        "title": "30 Min Meeting between Mentor and Test User",
        "startTime": start.isoformat(),
        "endTime": (start + timedelta(minutes=30)).isoformat(),
        "organizer": {"username": CAL_USERNAME, "email": "mentor@example.com"},
        "attendees": [
            {"email": "yokeshmd99@gmail.com", "name": "Test Candidate", "timeZone": "Europe/Amsterdam"}
        ],
        "metadata": {"videoCallUrl": "https://cal.com/video/test"},
        **({"cancellationReason": "testing cancellation"} if mode == "cancel" else {}),
    },
}

body = json.dumps(payload).encode()
signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

resp = httpx.post(URL, content=body, headers={
    "Content-Type": "application/json",
    "X-Cal-Signature-256": signature,
})
print(f"{payload['triggerEvent']} uid={uid}")
print(f"HTTP {resp.status_code}: {resp.text}")
print("\nNow check Supabase: webhook_events should have a processed row,")
print("bookings should show the booking with the matching status.")

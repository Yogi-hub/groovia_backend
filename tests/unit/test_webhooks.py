# Cal.com webhook endpoint: signature verification + intake logging + booking upsert.
import hashlib
import hmac
import json

from unittest.mock import patch

SECRET = "test-webhook-secret"


def _signed(body: dict) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


def _cal_body(event="BOOKING_CREATED", uid="cal_uid_1"):
    return {
        "triggerEvent": event,
        "payload": {
            "uid": uid,
            "title": "30 Min Meeting",
            "startTime": "2026-06-20T10:00:00Z",
            "endTime": "2026-06-20T10:30:00Z",
            "organizer": {"username": "yokesh-dhanabal-4hwiui"},
            "attendees": [{"email": "test@example.com", "name": "Test", "timeZone": "Europe/Amsterdam"}],
            "metadata": {"videoCallUrl": "https://cal.com/video/x"},
        },
    }


def test_webhook_503_when_secret_unset(client):
    with patch("config.CAL_WEBHOOK_SECRET", None):
        resp = client.post("/webhooks/cal", content=b"{}")
    assert resp.status_code == 503


def test_webhook_rejects_bad_signature(client):
    raw, _ = _signed(_cal_body())
    with patch("config.CAL_WEBHOOK_SECRET", SECRET), \
         patch("db.log_webhook_event", return_value="evt-1") as log_mock:
        resp = client.post(
            "/webhooks/cal", content=raw,
            headers={"X-Cal-Signature-256": "deadbeef", "Content-Type": "application/json"},
        )
    assert resp.status_code == 401
    log_mock.assert_called_once()  # forensics row still written


def test_webhook_processes_booking_created(client):
    raw, sig = _signed(_cal_body())
    with patch("config.CAL_WEBHOOK_SECRET", SECRET), \
         patch("db.log_webhook_event", return_value="evt-1"), \
         patch("db.mark_webhook_processed") as done_mock, \
         patch("db.find_mentor_by_cal_path", return_value={"id": "mentor-uuid"}), \
         patch("db.get_profile_id_by_email", return_value=None), \
         patch("db.upsert_booking") as upsert_mock:
        resp = client.post(
            "/webhooks/cal", content=raw,
            headers={"X-Cal-Signature-256": sig, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["processed"] is True
    fields = upsert_mock.call_args.args[0]
    assert fields["external_id"] == "cal_uid_1"
    assert fields["mentor_id"] == "mentor-uuid"
    assert fields["status"] == "confirmed"
    assert upsert_mock.call_args.kwargs["insert_only"] is True
    done_mock.assert_called_once_with("evt-1", None)


def test_webhook_unknown_mentor_kept_for_replay(client):
    raw, sig = _signed(_cal_body())
    with patch("config.CAL_WEBHOOK_SECRET", SECRET), \
         patch("db.log_webhook_event", return_value="evt-2"), \
         patch("db.mark_webhook_processed") as done_mock, \
         patch("db.find_mentor_by_cal_path", return_value=None), \
         patch("db.upsert_booking") as upsert_mock:
        resp = client.post(
            "/webhooks/cal", content=raw,
            headers={"X-Cal-Signature-256": sig, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200  # still 200 — event stays logged with the error
    assert resp.json()["processed"] is False
    upsert_mock.assert_not_called()
    error = done_mock.call_args.args[1]
    assert "no mentor matches" in error


def test_webhook_ignores_unmapped_event(client):
    raw, sig = _signed(_cal_body(event="FORM_SUBMITTED"))
    with patch("config.CAL_WEBHOOK_SECRET", SECRET), \
         patch("db.log_webhook_event", return_value="evt-3"), \
         patch("db.mark_webhook_processed"):
        resp = client.post(
            "/webhooks/cal", content=raw,
            headers={"X-Cal-Signature-256": sig, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["ignored"] is True


def test_webhook_status_only_event_updates_status(client):
    raw, sig = _signed(_cal_body(event="MEETING_ENDED"))
    with patch("config.CAL_WEBHOOK_SECRET", SECRET), \
         patch("db.log_webhook_event", return_value="evt-4"), \
         patch("db.mark_webhook_processed") as done_mock, \
         patch("db.update_booking_status", return_value=True) as upd_mock:
        resp = client.post(
            "/webhooks/cal", content=raw,
            headers={"X-Cal-Signature-256": sig, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["processed"] is True
    upd_mock.assert_called_once_with("cal_uid_1", "completed")
    done_mock.assert_called_once_with("evt-4", None)

import logging

from fastapi import APIRouter, Depends, HTTPException

import db
from auth import AuthUser, require_admin

logger = logging.getLogger("immigroov.routers.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/mentors/pending")
def list_pending_mentors(user: AuthUser = Depends(require_admin)):
    """List all mentors awaiting admin approval."""
    return db.list_mentors_by_status("pending_review")


@router.post("/mentors/{mentor_id}/approve")
def approve_mentor(mentor_id: str, user: AuthUser = Depends(require_admin)):
    """Approve a pending mentor application."""
    try:
        return db.set_mentor_status(mentor_id, "approved")
    except ValueError:
        raise HTTPException(status_code=404, detail="Mentor not found")


@router.post("/mentors/{mentor_id}/reject")
def reject_mentor(mentor_id: str, user: AuthUser = Depends(require_admin)):
    """Reject a pending mentor application."""
    try:
        return db.set_mentor_status(mentor_id, "rejected")
    except ValueError:
        raise HTTPException(status_code=404, detail="Mentor not found")

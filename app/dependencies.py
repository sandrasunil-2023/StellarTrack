import hmac
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Role, User


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return user


def admin_user(user: User = Depends(current_user)):
    if user.role != Role.ADMIN: raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


async def csrf(request: Request):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.headers.get("X-CSRF-Token") or (await request.form()).get("csrf_token")
        expected = request.session.get("csrf_token")
        if not expected or not supplied or not hmac.compare_digest(supplied, expected): raise HTTPException(403, "Invalid CSRF token")

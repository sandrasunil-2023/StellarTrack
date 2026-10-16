import csv, io, json, secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from argon2 import PasswordHasher
from fastapi import HTTPException, status
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from app.config import get_settings
from app.models import AuditLog, Company, Engagement, Role, TimeEntry, User

password_hasher = PasswordHasher()


def hash_password(password: str) -> str: return password_hasher.hash(password)
def verify_password(password: str, hashed: str) -> bool:
    try: return password_hasher.verify(hashed, password)
    except Exception: return False
def require_password(password: str):
    if len(password) < 8: raise HTTPException(422, "Password must be at least 8 characters")
def csrf_token(): return secrets.token_urlsafe(32)


def audit(db: Session, actor: User | None, action: str, entity: str, entity_id: int, before=None, after=None):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity_type=entity, entity_id=entity_id,
                    before_data=json.dumps(before, default=str) if before else None, after_data=json.dumps(after, default=str) if after else None))


def validate_entry(db: Session, company_id: int, engagement_id: int | None, hours: Decimal, description: str):
    company = db.get(Company, company_id)
    if not company or not company.is_active: raise HTTPException(422, "Select an active company")
    if engagement_id is not None:
        engagement = db.get(Engagement, engagement_id)
        if not engagement or not engagement.is_active or engagement.company_id != company_id:
            raise HTTPException(422, "Select an active engagement for the selected company")
    if not hours.is_finite() or hours <= 0 or hours >= 24: raise HTTPException(422, "Hours must be greater than 0 and less than 24")
    if not description.strip(): raise HTTPException(422, "Description is required")
    return company


def create_entry(db: Session, actor: User, company_id: int, engagement_id: int | None, work_date: date, hours: Decimal, description: str):
    validate_entry(db, company_id, engagement_id, hours, description)
    item = TimeEntry(employee_id=actor.id, company_id=company_id, engagement_id=engagement_id, work_date=work_date, hours=hours, description=description.strip())
    db.add(item); db.flush(); audit(db, actor, "CREATE_TIME_ENTRY", "time_entry", item.id, after=entry_dict(item)); db.commit(); return item


def entry_dict(item: TimeEntry): return {"employee_id": item.employee_id, "company_id": item.company_id, "engagement_id": item.engagement_id, "work_date": item.work_date, "hours": item.hours, "description": item.description}


def update_entry(db: Session, actor: User, entry_id: int, company_id: int, engagement_id: int | None, work_date: date, hours: Decimal, description: str):
    item = db.get(TimeEntry, entry_id)
    if not item: raise HTTPException(404, "Time entry not found")
    if actor.role != Role.ADMIN and item.employee_id != actor.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted")
    validate_entry(db, company_id, engagement_id, hours, description); before = entry_dict(item)
    item.company_id, item.engagement_id, item.work_date, item.hours, item.description = company_id, engagement_id, work_date, hours, description.strip()
    db.flush(); audit(db, actor, "UPDATE_TIME_ENTRY", "time_entry", item.id, before, entry_dict(item)); db.commit(); return item


def filtered_entries(db: Session, employee_id=None, company_id=None, start=None, end=None):
    stmt = select(TimeEntry).options(joinedload(TimeEntry.employee), joinedload(TimeEntry.company), joinedload(TimeEntry.engagement)).order_by(TimeEntry.work_date.desc(), TimeEntry.id.desc())
    if employee_id: stmt = stmt.where(TimeEntry.employee_id == employee_id)
    if company_id: stmt = stmt.where(TimeEntry.company_id == company_id)
    if start: stmt = stmt.where(TimeEntry.work_date >= start)
    if end: stmt = stmt.where(TimeEntry.work_date <= end)
    return db.scalars(stmt).all()


def report_rows(db: Session, **filters): return filtered_entries(db, **filters)


def export_csv(rows, metadata):
    out = io.StringIO(); writer = csv.writer(out); writer.writerow(["StellarTrack Report"])
    for key, value in metadata.items(): writer.writerow([key, value])
    writer.writerow([]); writer.writerow(["Employee", "Company", "Engagement", "Engagement code", "Date", "Hours", "Description"])
    for x in rows: writer.writerow([x.employee.full_name, x.company.name, x.engagement.name if x.engagement else "", x.engagement.code if x.engagement else "", x.work_date.isoformat(), str(x.hours), x.description])
    return out.getvalue().encode()


def export_xlsx(rows, metadata):
    wb = Workbook(); ws = wb.active; ws.title = "Report"; ws.append(["StellarTrack Report"])
    for key, value in metadata.items(): ws.append([key, value])
    ws.append([]); ws.append(["Employee", "Company", "Engagement", "Engagement code", "Date", "Hours", "Description"])
    for x in rows: ws.append([x.employee.full_name, x.company.name, x.engagement.name if x.engagement else "", x.engagement.code if x.engagement else "", x.work_date, float(x.hours), x.description])
    ws.freeze_panes = "A7"; ws.column_dimensions["A"].width = 24; ws.column_dimensions["B"].width = 24; ws.column_dimensions["E"].width = 55
    ws.column_dimensions["C"].width = 24; ws.column_dimensions["D"].width = 18
    out = io.BytesIO(); wb.save(out); return out.getvalue()


def kolkata_today(): return datetime.now(ZoneInfo(get_settings().app_timezone)).date()
def week_bounds(day): return day - timedelta(days=day.weekday()), day + timedelta(days=6-day.weekday())

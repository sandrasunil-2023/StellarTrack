from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.database import Base, engine, get_db
from app.dependencies import admin_user, csrf, current_user
from app.models import AuditLog, Company, Engagement, Role, TimeEntry, User
from app.services import (audit, create_entry, csrf_token, export_csv, export_xlsx, filtered_entries,
    hash_password, kolkata_today, require_password, update_entry, verify_password, week_bounds)

settings = get_settings()
app = FastAPI(title="StellarTrack")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=settings.secure_cookies, same_site="lax")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


class Login(BaseModel): username: str; password: str
class PasswordChange(BaseModel): current_password: str; new_password: str
class EmployeeIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=160); username: str = Field(min_length=3, max_length=80)
    initial_password: str = Field(min_length=8); role: Role = Role.EMPLOYEE; is_active: bool = True
class CompanyIn(BaseModel): name: str = Field(min_length=1, max_length=160); code: str | None = Field(None, max_length=40); is_active: bool = True
class EngagementIn(BaseModel): company_id: int; name: str = Field(min_length=1, max_length=160); code: str = Field(min_length=1, max_length=40); is_active: bool = True
class EntryIn(BaseModel): company_id: int; engagement_id: int | None = None; work_date: date; hours: Decimal; description: str = Field(min_length=1)
class ResetIn(BaseModel): new_password: str = Field(min_length=8)


def display_hours(value: Decimal) -> str:
    """Return precise decimal hours without database-added trailing zeroes."""
    return format(value.normalize(), "f")

def serialize_entry(x): return {"id":x.id,"employee_id":x.employee_id,"company_id":x.company_id,"engagement_id":x.engagement_id,"work_date":x.work_date,"hours":display_hours(x.hours),"description":x.description,"created_at":x.created_at,"updated_at":x.updated_at}
def totals(db, employee_id=None, company_id=None, start=None, end=None):
    stmt = select(func.coalesce(func.sum(TimeEntry.hours), 0))
    if employee_id: stmt = stmt.where(TimeEntry.employee_id == employee_id)
    if company_id: stmt = stmt.where(TimeEntry.company_id == company_id)
    if start: stmt = stmt.where(TimeEntry.work_date >= start)
    if end: stmt = stmt.where(TimeEntry.work_date <= end)
    return str(db.scalar(stmt))
def report_filter(start, end, week, month):
    if week: start, end = week_bounds(date.fromisoformat(week))
    if month:
        y, m = map(int, month.split("-")); start = date(y,m,1); end = date(y + (m==12), 1 if m==12 else m+1, 1) - __import__('datetime').timedelta(days=1)
    return start, end


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    if not request.session.get("csrf_token"): request.session["csrf_token"] = csrf_token()
    uid = request.session.get("user_id")
    user = db.get(User, uid) if uid else None
    if user and user.is_active: return RedirectResponse("/dashboard", 303)
    return templates.TemplateResponse(request, "login.html", {"csrf_token":request.session["csrf_token"]})


@app.post("/auth/login")
def login(payload: Login, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash): raise HTTPException(401, "Invalid username or password")
    request.session.clear(); request.session.update({"user_id":user.id, "csrf_token":csrf_token()})
    return {"message":"Logged in", "must_change_password":user.must_change_password, "redirect":"/dashboard", "csrf_token":request.session["csrf_token"]}


@app.post("/auth/logout", dependencies=[Depends(csrf)])
def logout(request: Request): request.session.clear(); return {"message":"Logged out"}

@app.post("/auth/change-password", dependencies=[Depends(csrf)])
def change_password(payload: PasswordChange, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not verify_password(payload.current_password, user.password_hash): raise HTTPException(422, "Current password is incorrect")
    require_password(payload.new_password); user.password_hash = hash_password(payload.new_password); user.must_change_password = False; audit(db,user,"CHANGE_PASSWORD","user",user.id); db.commit(); return {"message":"Password updated"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, user: User = Depends(current_user)):
    template = "admin.html" if user.role == Role.ADMIN else "employee.html"
    return templates.TemplateResponse(request, template, {"user":user, "csrf_token":request.session["csrf_token"]})

@app.get("/profile")
def profile(user: User = Depends(current_user)):
    return {"id": user.id, "full_name": user.full_name, "username": user.username, "role": user.role, "is_active": user.is_active, "created_at": user.created_at}


@app.get("/employee/dashboard")
def employee_dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.must_change_password: raise HTTPException(403,"Password change required before logging hours")
    today=kolkata_today(); ws,we=week_bounds(today)
    week_entries=filtered_entries(db, employee_id=user.id, start=ws, end=we)
    rows={}
    for entry in week_entries:
        key=(entry.company_id, entry.engagement_id)
        if key not in rows:
            rows[key]={"company":entry.company.name,"company_code":entry.company.code,"engagement":entry.engagement.name if entry.engagement else "Unassigned","engagement_code":entry.engagement.code if entry.engagement else "—","daily":[Decimal("0") for _ in range(7)]}
        rows[key]["daily"][(entry.work_date-ws).days] += entry.hours
    weekly_rows=[]
    for row in rows.values():
        daily=[display_hours(value) if value else "" for value in row["daily"]]
        weekly_rows.append({**row,"daily":daily,"total":display_hours(sum(row["daily"],Decimal("0")))})
    weekly_rows.sort(key=lambda row:(row["company"],row["engagement"]))
    return {"today":totals(db,user.id,start=today,end=today),"week":totals(db,user.id,start=ws,end=we),"month":totals(db,user.id,start=today.replace(day=1),end=today),"week_dates":[{"date":(ws+__import__('datetime').timedelta(days=index)).isoformat(),"weekday":(ws+__import__('datetime').timedelta(days=index)).strftime("%a"),"day":(ws+__import__('datetime').timedelta(days=index)).day} for index in range(7)],"weekly_rows":weekly_rows}

@app.get("/employee/companies")
def active_companies(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": x.id, "name": x.name, "code": x.code} for x in db.scalars(select(Company).where(Company.is_active.is_(True)).order_by(Company.name))]

@app.get("/employee/companies/{company_id}/engagements")
def active_engagements(company_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": x.id, "name": x.name, "code": x.code} for x in db.scalars(select(Engagement).where(Engagement.company_id == company_id, Engagement.is_active.is_(True)).order_by(Engagement.name))]

@app.get("/employee/time-entries")
def my_entries(start: date|None=None, end: date|None=None, company_id: int|None=None, week: date|None=None, month: str|None=None, db: Session=Depends(get_db), user: User=Depends(current_user)):
    start,end=report_filter(start,end,week.isoformat() if week else None,month); rows=filtered_entries(db,user.id,company_id,start,end); return {"total_hours":str(sum((x.hours for x in rows),Decimal("0"))),"items":[serialize_entry(x) | {"company": x.company.name, "engagement":x.engagement.name if x.engagement else None, "engagement_code":x.engagement.code if x.engagement else None} for x in rows]}

@app.post("/employee/time-entries", dependencies=[Depends(csrf)])
def add_entry(payload: EntryIn, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if user.must_change_password: raise HTTPException(403,"Password change required")
    return serialize_entry(create_entry(db,user,**payload.model_dump()))

@app.get("/employee/time-entries/{entry_id}")
def get_entry(entry_id:int, db:Session=Depends(get_db), user:User=Depends(current_user)):
    item=db.get(TimeEntry,entry_id)
    if not item: raise HTTPException(404,"Time entry not found")
    if item.employee_id != user.id: raise HTTPException(403,"Not permitted")
    return serialize_entry(item)

@app.put("/employee/time-entries/{entry_id}", dependencies=[Depends(csrf)])
def edit_entry(entry_id:int,payload:EntryIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    raise HTTPException(403, "Employees cannot edit time entries")


@app.get("/admin/dashboard")
def admin_dashboard(db:Session=Depends(get_db), user:User=Depends(admin_user)):
    today=kolkata_today(); ws,we=week_bounds(today)
    employees=db.scalars(select(User).where(User.role==Role.EMPLOYEE)).all(); companies=db.scalars(select(Company)).all()
    return {"overall":{"today":totals(db,start=today,end=today),"week":totals(db,start=ws,end=we),"month":totals(db,start=today.replace(day=1),end=today),"active_employees":sum(x.is_active for x in employees),"active_companies":sum(x.is_active for x in companies)},"employees":[{"name":x.full_name,"today":totals(db,x.id,start=today,end=today),"week":totals(db,x.id,start=ws,end=we),"month":totals(db,x.id,start=today.replace(day=1),end=today)} for x in employees],"companies":[{"name":x.name,"today":totals(db,company_id=x.id,start=today,end=today),"week":totals(db,company_id=x.id,start=ws,end=we),"month":totals(db,company_id=x.id,start=today.replace(day=1),end=today)} for x in companies],"recent":[serialize_entry(x) | {"employee":x.employee.full_name,"company":x.company.name,"engagement":x.engagement.name if x.engagement else None,"engagement_code":x.engagement.code if x.engagement else None} for x in filtered_entries(db)[:10]]}

@app.get("/admin/time-entries")
def admin_time_entries(employee_id:int|None=None, company_id:int|None=None, start:date|None=None, end:date|None=None, db:Session=Depends(get_db), user:User=Depends(admin_user)):
    return [{**serialize_entry(x), "employee": x.employee.full_name, "company": x.company.name} for x in filtered_entries(db, employee_id, company_id, start, end)]

@app.put("/admin/time-entries/{entry_id}", dependencies=[Depends(csrf)])
def admin_edit_time_entry(entry_id: int, payload: EntryIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return serialize_entry(update_entry(db, user, entry_id, **payload.model_dump()))

@app.get("/admin/employees")
def employees(db:Session=Depends(get_db), user:User=Depends(admin_user)): return [{"id":x.id,"full_name":x.full_name,"username":x.username,"role":x.role,"is_active":x.is_active,"created_at":x.created_at,"updated_at":x.updated_at} for x in db.scalars(select(User).order_by(User.full_name))]
@app.post("/admin/employees", dependencies=[Depends(csrf)])
def add_employee(payload:EmployeeIn,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    if db.scalar(select(User).where(User.username==payload.username.strip())): raise HTTPException(409,"Username already exists")
    obj=User(full_name=payload.full_name.strip(),username=payload.username.strip(),password_hash=hash_password(payload.initial_password),role=payload.role,is_active=payload.is_active,must_change_password=True);db.add(obj);db.flush();audit(db,actor,"CREATE_USER","user",obj.id,after={"username":obj.username,"role":obj.role.value});db.commit();return {"id":obj.id}
@app.put("/admin/employees/{user_id}", dependencies=[Depends(csrf)])
def edit_employee(user_id:int,payload:EmployeeIn,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    obj=db.get(User,user_id)
    if not obj: raise HTTPException(404,"Employee not found")
    other=db.scalar(select(User).where(User.username==payload.username.strip(),User.id!=user_id))
    if other: raise HTTPException(409,"Username already exists")
    before={"full_name":obj.full_name,"username":obj.username,"role":obj.role.value,"is_active":obj.is_active};obj.full_name,obj.username,obj.role,obj.is_active=payload.full_name.strip(),payload.username.strip(),payload.role,payload.is_active;audit(db,actor,"UPDATE_USER","user",obj.id,before,{"full_name":obj.full_name,"username":obj.username,"role":obj.role.value,"is_active":obj.is_active});db.commit();return {"id":obj.id}
@app.post("/admin/employees/{user_id}/{state}", dependencies=[Depends(csrf)])
def employee_state(user_id:int,state:str,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    if state not in {"activate","deactivate"}: raise HTTPException(404)
    obj=db.get(User,user_id)
    if not obj: raise HTTPException(404,"Employee not found")
    obj.is_active=state=="activate";audit(db,actor,"%s_USER"%state.upper(),"user",obj.id,after={"is_active":obj.is_active});db.commit();return {"id":obj.id,"is_active":obj.is_active}
@app.post("/admin/employees/{user_id}/reset-password", dependencies=[Depends(csrf)])
def reset_password(user_id:int,payload:ResetIn,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    obj=db.get(User,user_id)
    if not obj: raise HTTPException(404,"Employee not found")
    require_password(payload.new_password);obj.password_hash=hash_password(payload.new_password);obj.must_change_password=True;audit(db,actor,"RESET_PASSWORD","user",obj.id);db.commit();return {"message":"Password reset; user must change it after login"}

@app.get("/admin/companies")
def companies(db:Session=Depends(get_db), user:User=Depends(admin_user)): return [{"id":x.id,"name":x.name,"code":x.code,"is_active":x.is_active,"created_at":x.created_at,"updated_at":x.updated_at} for x in db.scalars(select(Company).order_by(Company.name))]
@app.post("/admin/companies", dependencies=[Depends(csrf)])
def add_company(payload:CompanyIn,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    obj=Company(name=payload.name.strip(),code=payload.code.strip() if payload.code else None,is_active=payload.is_active);db.add(obj)
    try: db.flush()
    except Exception: db.rollback(); raise HTTPException(409,"Company name or code already exists")
    audit(db,actor,"CREATE_COMPANY","company",obj.id,after={"name":obj.name,"code":obj.code});db.commit();return {"id":obj.id}
@app.put("/admin/companies/{company_id}", dependencies=[Depends(csrf)])
def edit_company(company_id:int,payload:CompanyIn,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    obj=db.get(Company,company_id)
    if not obj: raise HTTPException(404,"Company not found")
    before={"name":obj.name,"code":obj.code,"is_active":obj.is_active};obj.name,obj.code,obj.is_active=payload.name.strip(),payload.code.strip() if payload.code else None,payload.is_active
    try: db.flush()
    except Exception: db.rollback(); raise HTTPException(409,"Company name or code already exists")
    audit(db,actor,"UPDATE_COMPANY","company",obj.id,before,{"name":obj.name,"code":obj.code,"is_active":obj.is_active});db.commit();return {"id":obj.id}
@app.post("/admin/companies/{company_id}/{state}", dependencies=[Depends(csrf)])
def company_state(company_id:int,state:str,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    if state not in {"activate","deactivate"}: raise HTTPException(404)
    obj=db.get(Company,company_id)
    if not obj: raise HTTPException(404,"Company not found")
    obj.is_active=state=="activate";audit(db,actor,"%s_COMPANY"%state.upper(),"company",obj.id,after={"is_active":obj.is_active});db.commit();return {"id":obj.id,"is_active":obj.is_active}

@app.get("/admin/engagements")
def engagements(company_id: int|None=None, db: Session=Depends(get_db), user: User=Depends(admin_user)):
    stmt = select(Engagement).order_by(Engagement.name)
    if company_id: stmt = stmt.where(Engagement.company_id == company_id)
    return [{"id":x.id,"company_id":x.company_id,"company":x.company.name,"name":x.name,"code":x.code,"is_active":x.is_active,"created_at":x.created_at,"updated_at":x.updated_at} for x in db.scalars(stmt)]
@app.post("/admin/engagements", dependencies=[Depends(csrf)])
def add_engagement(payload: EngagementIn, db: Session=Depends(get_db), actor: User=Depends(admin_user)):
    company = db.get(Company, payload.company_id)
    if not company: raise HTTPException(422, "Select a company")
    obj=Engagement(company_id=payload.company_id,name=payload.name.strip(),code=payload.code.strip(),is_active=payload.is_active); db.add(obj)
    try: db.flush()
    except Exception: db.rollback(); raise HTTPException(409,"Engagement code already exists")
    audit(db,actor,"CREATE_ENGAGEMENT","engagement",obj.id,after={"company_id":obj.company_id,"name":obj.name,"code":obj.code});db.commit();return {"id":obj.id}
@app.put("/admin/engagements/{engagement_id}", dependencies=[Depends(csrf)])
def edit_engagement(engagement_id: int, payload: EngagementIn, db: Session=Depends(get_db), actor: User=Depends(admin_user)):
    obj=db.get(Engagement,engagement_id)
    if not obj: raise HTTPException(404,"Engagement not found")
    if not db.get(Company, payload.company_id): raise HTTPException(422,"Select a company")
    before={"company_id":obj.company_id,"name":obj.name,"code":obj.code,"is_active":obj.is_active};obj.company_id,obj.name,obj.code,obj.is_active=payload.company_id,payload.name.strip(),payload.code.strip(),payload.is_active
    try: db.flush()
    except Exception: db.rollback(); raise HTTPException(409,"Engagement code already exists")
    audit(db,actor,"UPDATE_ENGAGEMENT","engagement",obj.id,before,{"company_id":obj.company_id,"name":obj.name,"code":obj.code,"is_active":obj.is_active});db.commit();return {"id":obj.id}
@app.post("/admin/engagements/{engagement_id}/{state}", dependencies=[Depends(csrf)])
def engagement_state(engagement_id:int,state:str,db:Session=Depends(get_db),actor:User=Depends(admin_user)):
    if state not in {"activate","deactivate"}: raise HTTPException(404)
    obj=db.get(Engagement,engagement_id)
    if not obj: raise HTTPException(404,"Engagement not found")
    obj.is_active=state=="activate";audit(db,actor,"%s_ENGAGEMENT"%state.upper(),"engagement",obj.id,after={"is_active":obj.is_active});db.commit();return {"id":obj.id,"is_active":obj.is_active}

def filters(employee_id,company_id,start,end,week,month): return (*report_filter(start,end,week,month), employee_id,company_id)
def metadata(start,end,employee_id,company_id):
    tz=ZoneInfo(settings.app_timezone); return {"Generated at":datetime.now(tz).strftime("%d %b %Y, %H:%M %Z"),"Date range":f"{start or 'All'} to {end or 'All'}","Employee":str(employee_id or "All"),"Company":str(company_id or "All")}
@app.get("/admin/reports")
def reports(employee_id:int|None=None,company_id:int|None=None,start:date|None=None,end:date|None=None,week:str|None=None,month:str|None=None,db:Session=Depends(get_db),user:User=Depends(admin_user)):
    start,end,employee_id,company_id=filters(employee_id,company_id,start,end,week,month); rows=filtered_entries(db,employee_id,company_id,start,end)
    by_employee={};by_company={}
    for row in rows: by_employee[row.employee.full_name]=by_employee.get(row.employee.full_name,Decimal("0"))+row.hours;by_company[row.company.name]=by_company.get(row.company.name,Decimal("0"))+row.hours
    return {"total_hours":str(sum((x.hours for x in rows),Decimal("0"))),"employee_totals":[{"employee":k,"hours":str(v)} for k,v in by_employee.items()],"company_totals":[{"company":k,"hours":str(v)} for k,v in by_company.items()],"detailed":[serialize_entry(x) | {"employee":x.employee.full_name,"company":x.company.name} for x in rows]}
@app.get("/admin/reports/export/csv")
def report_csv(employee_id:int|None=None,company_id:int|None=None,start:date|None=None,end:date|None=None,week:str|None=None,month:str|None=None,db:Session=Depends(get_db),user:User=Depends(admin_user)):
    start,end,employee_id,company_id=filters(employee_id,company_id,start,end,week,month); data=export_csv(filtered_entries(db,employee_id,company_id,start,end),metadata(start,end,employee_id,company_id));return Response(data,media_type="text/csv",headers={"Content-Disposition":"attachment; filename=stellartrack-report.csv"})
@app.get("/admin/reports/export/excel")
def report_excel(employee_id:int|None=None,company_id:int|None=None,start:date|None=None,end:date|None=None,week:str|None=None,month:str|None=None,db:Session=Depends(get_db),user:User=Depends(admin_user)):
    start,end,employee_id,company_id=filters(employee_id,company_id,start,end,week,month); data=export_xlsx(filtered_entries(db,employee_id,company_id,start,end),metadata(start,end,employee_id,company_id));return Response(data,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=stellartrack-report.xlsx"})
@app.get("/admin/audit-logs")
def audit_logs(actor_id:int|None=None,action:str|None=None,entity_type:str|None=None,start:datetime|None=None,end:datetime|None=None,db:Session=Depends(get_db),user:User=Depends(admin_user)):
    stmt=select(AuditLog).order_by(AuditLog.timestamp.desc())
    if actor_id:stmt=stmt.where(AuditLog.actor_id==actor_id)
    if action:stmt=stmt.where(AuditLog.action==action)
    if entity_type:stmt=stmt.where(AuditLog.entity_type==entity_type)
    if start:stmt=stmt.where(AuditLog.timestamp>=start)
    if end:stmt=stmt.where(AuditLog.timestamp<=end)
    return [{"id":x.id,"actor_id":x.actor_id,"action":x.action,"entity_type":x.entity_type,"entity_id":x.entity_id,"timestamp":x.timestamp,"before_data":x.before_data,"after_data":x.after_data} for x in db.scalars(stmt)]

@app.on_event("startup")
def create_tables_for_development():
    if settings.environment == "development": Base.metadata.create_all(engine)

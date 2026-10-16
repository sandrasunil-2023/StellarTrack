from datetime import date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.main import app
from app.models import Company, Role, User
from app.services import hash_password
from app.services import kolkata_today

@pytest.fixture()
def client(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path}/test.db",connect_args={"check_same_thread":False}); Base.metadata.create_all(engine); Local=sessionmaker(bind=engine)
    def override():
        db=Local()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override
    with Local() as db:
        db.add_all([User(full_name="Admin",username="admin",password_hash=hash_password("long-password"),role=Role.ADMIN),User(full_name="Employee",username="employee",password_hash=hash_password("long-password"),role=Role.EMPLOYEE),Company(name="Active Co",code="ACT")]);db.commit()
    with TestClient(app) as c: yield c
    app.dependency_overrides.clear()
def auth(client, username):
    r=client.post("/auth/login",json={"username":username,"password":"long-password"});return r.json()["csrf_token"]
def test_employee_cannot_access_admin(client):
    auth(client,"employee");assert client.get("/admin/dashboard").status_code==403
def test_time_entry_and_ownership(client):
    token=auth(client,"employee");headers={"X-CSRF-Token":token};entry={"company_id":1,"work_date":str(date.today()),"hours":"2.25","description":"Reconciliation"}
    r=client.post("/employee/time-entries",json=entry,headers=headers);assert r.status_code==200;assert r.json()["hours"]=="2.25"
    assert client.post("/employee/time-entries",json=entry|{"hours":"25"},headers=headers).status_code==422
    assert client.put("/employee/time-entries/1", json=entry, headers=headers).status_code == 403

def test_employee_dashboard_has_weekly_company_and_engagement_grid(client):
    admin_token=auth(client,"admin")
    engagement=client.post("/admin/engagements",json={"company_id":1,"name":"Audit","code":"AUD-01","is_active":True},headers={"X-CSRF-Token":admin_token})
    assert engagement.status_code == 200
    employee_token=auth(client,"employee")
    entry={"company_id":1,"engagement_id":engagement.json()["id"],"work_date":str(kolkata_today()),"hours":"3.5","description":"Audit work"}
    assert client.post("/employee/time-entries",json=entry,headers={"X-CSRF-Token":employee_token}).status_code == 200
    dashboard=client.get("/employee/dashboard").json()
    assert len(dashboard["week_dates"]) == 7
    expected_daily=["" for _ in range(7)]
    expected_daily[kolkata_today().weekday()]="3.5"
    assert dashboard["weekly_rows"] == [{"company":"Active Co","company_code":"ACT","engagement":"Audit","engagement_code":"AUD-01","daily":expected_daily,"total":"3.5"}]

import getpass
from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.models import Role, User
from app.services import hash_password, require_password

def main():
    Base.metadata.create_all(engine); name=input("Full name: ").strip(); username=input("Username: ").strip(); password=getpass.getpass("Password: "); require_password(password)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username==username)): raise SystemExit("Username already exists.")
        db.add(User(full_name=name,username=username,password_hash=hash_password(password),role=Role.ADMIN)); db.commit()
    print("Administrator created.")
if __name__ == "__main__": main()

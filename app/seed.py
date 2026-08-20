import os

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ProductionLine, Role, User, UserLineAssignment
from app.security import hash_password


SEED_PASSWORD_ENV_VAR = "SPTS_SEED_PASSWORD"


def get_seed_password() -> str:
    password = os.getenv(SEED_PASSWORD_ENV_VAR)

    if not password:
        raise RuntimeError(
            f"{SEED_PASSWORD_ENV_VAR} is required before seeding users."
        )

    return password


def get_or_create_role(db: Session, role_name: str) -> Role:
    role = db.query(Role).filter(Role.name == role_name).first()

    if role:
        return role

    role = Role(name=role_name)

    db.add(role)
    db.commit()
    db.refresh(role)

    print(f"Created role: {role_name}")

    return role


def get_or_create_line(
    db: Session,
    line_code: str,
    line_name: str,
) -> ProductionLine:
    line = (
        db.query(ProductionLine)
        .filter(ProductionLine.line_code == line_code)
        .first()
    )

    if line:
        return line

    line = ProductionLine(
        line_code=line_code,
        line_name=line_name,
        is_active=True,
    )

    db.add(line)
    db.commit()
    db.refresh(line)

    print(f"Created production line: {line_code}")

    return line


def get_or_create_user(
    db: Session,
    username: str,
    password: str,
    role: Role,
    full_name: str,
    email: str | None = None,
) -> User:
    user = db.query(User).filter(User.username == username).first()

    if user:
        return user

    user = User(
        username=username,
        password_hash=hash_password(password),
        full_name=full_name,
        email=email,
        role_id=role.id,
        is_active=True,
        must_change_password=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    print(f"Created user: {username}")

    return user


def assign_user_to_line(
    db: Session,
    user: User,
    line: ProductionLine,
) -> None:
    existing_assignment = (
        db.query(UserLineAssignment)
        .filter(
            UserLineAssignment.user_id == user.id,
            UserLineAssignment.production_line_id == line.id,
        )
        .first()
    )

    if existing_assignment:
        return

    assignment = UserLineAssignment(
        user_id=user.id,
        production_line_id=line.id,
    )

    db.add(assignment)
    db.commit()

    print(
        f"Assigned user {user.username} "
        f"to production line {line.line_code}"
    )


def seed_database() -> None:
    seed_password = get_seed_password()
    db = SessionLocal()

    try:
        line_role = get_or_create_role(
            db,
            "LINE_WORKSTATION",
        )

        supervisor_role = get_or_create_role(
            db,
            "SUPERVISOR",
        )

        manager_role = get_or_create_role(
            db,
            "MANAGER",
        )

        administrator_role = get_or_create_role(
            db,
            "ADMINISTRATOR",
        )

        line_1 = get_or_create_line(
            db,
            line_code="LINE-01",
            line_name="Production Line 1",
        )

        line_user = get_or_create_user(
            db,
            username="line1",
            password=seed_password,
            role=line_role,
            full_name="Production Line 1 Workstation",
        )

        get_or_create_user(
            db,
            username="supervisor1",
            password=seed_password,
            role=supervisor_role,
            full_name="Production Supervisor",
        )

        get_or_create_user(
            db,
            username="manager1",
            password=seed_password,
            role=manager_role,
            full_name="Production Manager",
        )

        get_or_create_user(
            db,
            username="admin1",
            password=seed_password,
            role=administrator_role,
            full_name="System Administrator",
        )

        assign_user_to_line(
            db,
            user=line_user,
            line=line_1,
        )

        print("Database seed completed successfully.")

    except Exception as error:
        db.rollback()
        print(f"Database seed failed: {error}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)

    users = relationship("User", back_populates="role")


class ProductionLine(Base):
    __tablename__ = "production_lines"

    id = Column(Integer, primary_key=True, index=True)
    line_code = Column(String(50), unique=True, nullable=False, index=True)
    line_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    user_assignments = relationship(
        "UserLineAssignment",
        back_populates="production_line",
        cascade="all, delete-orphan",
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=True, index=True)

    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)

    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    role = relationship("Role", back_populates="users")

    line_assignments = relationship(
        "UserLineAssignment",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserLineAssignment(Base):
    __tablename__ = "user_line_assignments"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    production_line_id = Column(
        Integer,
        ForeignKey("production_lines.id"),
        nullable=False,
    )

    assigned_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    user = relationship(
        "User",
        back_populates="line_assignments",
    )

    production_line = relationship(
        "ProductionLine",
        back_populates="user_assignments",
    )
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.security import create_access_token, verify_password
from app.dependencies import get_current_user


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str
    must_change_password: bool


def get_database():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


@router.post("/login", response_model=LoginResponse)
def login(
    login_data: LoginRequest,
    db: Session = Depends(get_database),
):
    user = (
        db.query(User)
        .filter(User.username == login_data.username)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not verify_password(
        login_data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    access_token = create_access_token(
    subject=user.username,
    additional_claims={
        "role": user.role.name,
    },
)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        username=user.username,
        role=user.role.name,
        must_change_password=user.must_change_password,
    )

@router.get("/me")
def read_current_user(
    current_user: User = Depends(get_current_user),
):
    return {
        "username": current_user.username,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "role": current_user.role.name,
        "is_active": current_user.is_active,
        "must_change_password": current_user.must_change_password,
    }
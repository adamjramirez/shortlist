"""Auth routes — signup, login, me."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.auth import create_token, hash_password, verify_password
from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.models import User
from shortlist.api.schemas import AuthResponse, LoginRequest, SignupRequest, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup(req: SignupRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=req.email, password_hash=hash_password(req.password))
    session.add(user)
    await session.flush()
    token = create_token(user.id)
    return AuthResponse(token=token, email=user.email, user_id=user.id)


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user.id)
    return AuthResponse(token=token, email=user.email, user_id=user.id)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return UserResponse(id=user.id, email=user.email)

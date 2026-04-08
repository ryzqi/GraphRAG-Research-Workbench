from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

AsyncSessionDep: TypeAlias = Annotated[AsyncSession, Depends(get_db_session)]

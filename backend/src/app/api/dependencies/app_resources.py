from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Depends, Request

from app.bootstrap.app_resources import AppResources, require_app_resources


def get_app_resources(request: Request) -> AppResources:
    return require_app_resources(request.app)


AppResourcesDep: TypeAlias = Annotated[AppResources, Depends(get_app_resources)]

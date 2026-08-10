from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse

from src.agent.security.auth import get_current_user

router = APIRouter()


@router.get("/openapi.json", include_in_schema=False)
def openapi_route(request: Request, _user_id: str = Depends(get_current_user)):
    return JSONResponse(request.app.openapi())


@router.get("/docs", include_in_schema=False)
def docs_route(
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    _user_id: str = Depends(get_current_user),
):
    response = get_swagger_ui_html(openapi_url="/openapi.json", title="Minimal Agent - Swagger UI")
    if api_key:
        response.set_cookie("agent_session", api_key, httponly=True, samesite="lax")
    return response


@router.get("/redoc", include_in_schema=False)
def redoc_route(
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    _user_id: str = Depends(get_current_user),
):
    response = get_redoc_html(openapi_url="/openapi.json", title="Minimal Agent - ReDoc")
    if api_key:
        response.set_cookie("agent_session", api_key, httponly=True, samesite="lax")
    return response

import os
import httpx
import time
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from fastmcp import Context
from utils.log_utils import setup_logger

load_dotenv()
logger = setup_logger(__name__)


async def get_api_credentials(ctx: Context) -> Optional[Dict[str, str]]:
    """
    Retrieves NextGen API credentials, prioritizing request headers with a fallback
    to environment variables.
    """
    headers = dict((k.decode(), v.decode()) for k, v in ctx.request_context.request.scope["headers"])
    creds = {
        "BASE_URL": headers.get("x-nextgen-base-url") or os.getenv("NEXTGEN_BASE_URL"),
        "AUTH_URL": headers.get("x-nextgen-auth-url") or os.getenv("NEXTGEN_AUTH_URL"),
        "CLIENT_ID": headers.get("x-nextgen-client-id") or os.getenv("NEXTGEN_CLIENT_ID"),
        "CLIENT_SECRET": headers.get("x-nextgen-client-secret") or os.getenv("NEXTGEN_CLIENT_SECRET"),
        "SITE_ID": headers.get("x-nextgen-site-id") or os.getenv("NEXTGEN_SITE_ID"),
        "ENTERPRISE_ID": headers.get("x-nextgen-enterprise-id") or os.getenv("NEXTGEN_ENTERPRISE_ID"),
        "PRACTICE_ID": headers.get("x-nextgen-practice-id") or os.getenv("NEXTGEN_PRACTICE_ID"),
        "LOCATION_ID": headers.get("x-nextgen-location-id") or os.getenv("NEXTGEN_DEFAULT_LOCATION_ID"),
    }
    return creds


async def get_access_token(ctx: Context, creds: Dict[str, str]) -> Optional[str]:
    """
    Retrieves a NextGen API access token using provided credentials.
    """
    token = getattr(ctx.session, "access_token", None)
    token_expiration = getattr(ctx.session, "token_expiration", 0)

    if token and time.time() < token_expiration - 60:
        logger.info("Using cached access token.")
        return token

    logger.info("Access token is expired or not found. Fetching a new one.")

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": creds.get("CLIENT_ID"),
        "client_secret": creds.get("CLIENT_SECRET"),
        "site_id": creds.get("SITE_ID"),
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(creds.get("AUTH_URL"), headers=headers, data=data)
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)
            ctx.session.access_token = access_token
            ctx.session.token_expiration = time.time() + expires_in
            logger.info(f"Successfully fetched new access token, expires in {expires_in} seconds.")
            return access_token

    except Exception as e:
        logger.error(f"Failed to fetch access token: {str(e)}")
        return None


async def get_session_id(ctx: Context, creds: Dict[str, str]) -> Optional[str]:
    """
    Dynamically retrieves a NextGen session ID using provided credentials.
    """
    session_id = getattr(ctx.session, "x_ng_sessionid", None)
    if session_id:
        logger.info("Using cached session ID.")
        return session_id

    logger.info("Session ID not found. Fetching a new one via login-defaults.")
    access_token = await get_access_token(ctx, creds)
    if not access_token:
        logger.error("Cannot fetch session ID without an access token.")
        return None

    login_defaults_url = f"{creds.get('BASE_URL')}/users/me/login-defaults"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {"enterpriseId": creds.get("ENTERPRISE_ID"), "practiceId": creds.get("PRACTICE_ID")}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(login_defaults_url, headers=headers, json=payload)
            response.raise_for_status()

            new_session_id = response.headers.get("x-ng-sessionid")
            if new_session_id:
                logger.info("Successfully fetched and cached new session ID.")
                ctx.session.x_ng_sessionid = new_session_id
                return new_session_id
            else:
                logger.error("'x-ng-sessionid' not found in login-defaults response headers.")
                return None
    except Exception as e:
        logger.error(f"Failed to fetch session ID from login-defaults: {str(e)}")
        return None


async def make_api_request(
    ctx: Context,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Makes an authenticated API request to the NextGen Enterprise API.
    """
    creds = await get_api_credentials(ctx)
    if not creds:
        return {"success": False, "message": "Could not load API credentials."}

    access_token = await get_access_token(ctx, creds)
    session_id = await get_session_id(ctx, creds)

    if not access_token or not session_id:
        return {"success": False, "message": "Failed to authenticate or establish a session with NextGen API."}

    request_headers = {
        "Authorization": f"Bearer {access_token}",
        "x-ng-sessionid": session_id,
        "Accept": "application/json",
    }
    if method in ["POST", "PUT", "PATCH"]:
        request_headers["Content-Type"] = "application/json"

    full_url = f"{creds.get('BASE_URL')}/{endpoint}"
    logger.info(f"Making API request: {method} {full_url}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=full_url,
                headers=request_headers,
                params=params,
                json=json_data,
            )
            response.raise_for_status()
            response_body = {}
            if response.status_code not in [201, 204] and response.text:
                response_body = response.json()
        logger.info(f"API request to NextGen successful with status {response.status_code}.")
        success_message = {"body": response_body, "headers": dict(response.headers), "status_code": response.status_code}
        return {"success": True, "message": success_message}

    except httpx.HTTPStatusError as e:
        error_text = e.response.text.lower()
        if "session" in error_text:
            if hasattr(ctx.session, "x_ng_sessionid"):
                delattr(ctx.session, "x_ng_sessionid")
                logger.warning(
                    "Invalid session error detected. Clearing cached session ID to force a refresh on the next call."
                )

        logger.error(f"API request failed with status {e.response.status_code}: {e.response.text}")
        return {"success": False, "message": f"API Error: {e.response.status_code} - {e.response.text}"}
    except Exception as e:
        logger.error(f"An unexpected error occurred during API request: {str(e)}")
        return {"success": False, "message": "An unexpected error occurred. Please try again later."}

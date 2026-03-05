# Microsoft Entra ID Authentication — Backend OAuth2 Code Flow

## Context

The OIT Helpdesk Dashboard currently has **no authentication** — all API endpoints are publicly accessible. We need to add Microsoft Entra ID (Azure AD) login so only whitelisted users (by email) can access the dashboard. The backend handles the full OAuth2 authorization code flow and sets an HttpOnly session cookie.

## Prerequisites — Entra Portal Setup

Before any code changes, register an app in [Entra ID Portal](https://entra.microsoft.com):

1. **App registrations** → **New registration**
   - Name: `OIT Helpdesk Dashboard`
   - Supported account types: "Accounts in this organizational directory only" (single tenant)
   - Redirect URI: **Web** → `http://localhost:3002/api/auth/callback`
2. Note the **Application (client) ID** and **Directory (tenant) ID**
3. **Certificates & secrets** → **New client secret** → copy the **Value**
4. **API permissions** → verify `Microsoft Graph > User.Read` (delegated) is present
5. **Token configuration** → **Add optional claim** → Token type: **ID** → check `email` and `preferred_username`

---

## Files to Change

| File | Action | What |
|------|--------|------|
| `backend/requirements.txt` | MODIFY | Add `authlib>=1.3.0`, `httpx>=0.27.0` |
| `backend/config.py` | MODIFY | Add 5 new env var constants |
| `backend/.env` | MODIFY | Add Entra credentials + `APP_SECRET_KEY` + `ALLOWED_USERS` |
| `backend/auth.py` | CREATE | Session store, OAuth client, `is_allowed_user()`, `require_auth` dependency |
| `backend/routes_auth.py` | CREATE | `/api/auth/login`, `/callback`, `/me`, `/logout` |
| `backend/main.py` | MODIFY | Add SessionMiddleware, AuthMiddleware, auth router |
| `nginx.conf` | MODIFY | Increase proxy buffer sizes for auth headers |
| `frontend/src/lib/api.ts` | MODIFY | Add 401 → redirect to login, add `getMe()` and `logout()` |
| `frontend/src/components/Layout.tsx` | MODIFY | Show user name + logout button in sidebar footer |

---

## Step 1: Backend Dependencies

Add to `backend/requirements.txt`:
```
authlib>=1.3.0
httpx>=0.27.0
```

## Step 2: Config (`backend/config.py`)

Add after existing vars:
```python
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET: str = os.getenv("ENTRA_CLIENT_SECRET", "")
ALLOWED_USERS: str = os.getenv("ALLOWED_USERS", "")  # comma-separated emails, empty = all
APP_SECRET_KEY: str = os.getenv("APP_SECRET_KEY", "change-me-in-production")
```

## Step 3: Auth Module (`backend/auth.py` — new file)

- **In-memory session store**: `dict[session_id → {email, name, expires_at}]`, 8-hour TTL
- `create_session(email, name) → session_id` (random 32-byte token)
- `get_session(session_id) → dict | None` (checks expiry)
- `delete_session(session_id)`
- `is_allowed_user(email) → bool` — checks `ALLOWED_USERS` whitelist (empty = allow all)
- **authlib OAuth client** registered as `"entra"` using OIDC discovery URL:
  `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration`
  Scopes: `openid email profile`

## Step 4: Auth Routes (`backend/routes_auth.py` — new file)

| Route | Method | Description |
|-------|--------|-------------|
| `/api/auth/login` | GET | Builds Entra authorize URL, redirects browser there |
| `/api/auth/callback` | GET | Exchanges code for tokens, validates ID token, checks whitelist, creates session, sets cookie, redirects to `/` |
| `/api/auth/me` | GET | Returns `{email, name}` if session valid, else 401 |
| `/api/auth/logout` | POST | Deletes session, clears cookie, redirects to `/` |

Cookie: `session_id`, HttpOnly, SameSite=Lax, Path=/, max_age=8h

## Step 5: Wire Into Main App (`backend/main.py`)

Add three middleware layers (order matters — Starlette applies in reverse):

```python
# Added in this order (innermost first):
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY)  # authlib needs this for OAuth state
app.add_middleware(AuthMiddleware)                                 # protects /api/* routes
app.add_middleware(CORSMiddleware, ...)                           # existing, stays outermost
```

**AuthMiddleware** logic:
- Only intercepts `/api/*` paths
- Exempts: `/api/health`, `/api/auth/login`, `/api/auth/callback`, `/api/auth/me`, `/api/auth/logout`
- Checks `session_id` cookie → `get_session()` → 401 if missing/expired

Include `auth_router` alongside existing routers.

## Step 6: Nginx Buffer Sizes (`nginx.conf`)

Add to the `/api/` location block:
```nginx
proxy_buffer_size 16k;
proxy_buffers 4 16k;
```

## Step 7: Frontend 401 Handling (`frontend/src/lib/api.ts`)

- In `fetchJSON` and `postJSON`: if `res.status === 401`, redirect to `/api/auth/login`
- Also add 401 check in `exportReport` (uses raw fetch)
- Add `UserInfo` interface + `api.getMe()` and `api.logout()` methods

## Step 8: User Display (`frontend/src/components/Layout.tsx`)

Replace the static "OIT Dashboard v0.1" footer with:
- Query `api.getMe()` via TanStack Query
- If user is logged in: show name, email, and Logout button
- If not: show original "OIT Dashboard v0.1" text

---

## Login Flow (End-to-End)

1. User visits `http://localhost:3002/` → React loads
2. Any API call hits AuthMiddleware → 401 (no cookie)
3. Frontend `fetchJSON` catches 401 → redirects to `/api/auth/login`
4. Backend builds Entra authorize URL → 302 to Microsoft login
5. User authenticates (or SSO kicks in automatically)
6. Entra redirects to `/api/auth/callback?code=...`
7. Backend exchanges code → validates ID token → checks whitelist → creates session → sets HttpOnly cookie → 302 to `/`
8. All subsequent API calls include cookie → AuthMiddleware passes them through

**Container restart**: Sessions are in-memory, so users re-login — but Entra SSO makes this near-instant (no password re-entry).

---

## Verification

```bash
# 1. Install new deps
cd backend && pip install authlib httpx

# 2. Verify backend starts
python -c "from auth import oauth; print('auth module OK')"
python -c "from routes_auth import router; print('routes OK')"

# 3. Frontend build
cd frontend && npx tsc --noEmit && npm run build

# 4. Docker redeploy
docker compose up -d --build

# 5. Test auth flow
# Visit http://localhost:3002 → should redirect to Microsoft login
# After login → dashboard loads, sidebar shows user info
# Click Logout → returns to login screen

# 6. Test health endpoint stays public
curl http://localhost:3002/api/health  # should return {"status":"ok"} without auth
```

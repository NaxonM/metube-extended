import asyncio
import time
import inspect
from collections import defaultdict
from aiohttp import web
from aiohttp_session import setup as setup_session, get_session, new_session
from aiohttp_session.nacl_storage import NaClCookieStorage
import logging
import socketio

from users import UserStore

log = logging.getLogger(__name__)

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Login</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
        :root {{
            color-scheme: dark;
            --bg-start: #0f1724;
            --bg-end: #141c2b;
            --card-bg: rgba(22, 30, 44, 0.85);
            --accent: #4cc4ff;
            --accent-hover: #69d4ff;
            --text-primary: #f8fafc;
            --text-muted: #c7d2fe;
            --danger: #f87171;
            --border: rgba(148, 163, 184, 0.2);
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at top, var(--bg-start) 0%, var(--bg-end) 60%, #0a101d 100%);
            font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            color: var(--text-primary);
            padding: 24px;
        }}
        .login-wrapper {{
            width: min(420px, 100%);
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 18px;
            box-shadow: 0 30px 60px rgba(15, 23, 42, 0.45);
            backdrop-filter: blur(16px);
            padding: 36px;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 24px;
        }}
        .brand-badge {{
            width: 42px;
            height: 42px;
            border-radius: 12px;
            background: linear-gradient(135deg, rgba(76,196,255,0.25), rgba(76,196,255,0.05));
            display: grid;
            place-items: center;
            color: var(--accent);
            font-weight: 600;
            letter-spacing: 0.02em;
        }}
        .brand h2 {{
            font-size: 1.6rem;
            font-weight: 600;
            margin: 0;
        }}
        .brand span {{
            display: block;
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-top: 4px;
        }}
        form {{ display: grid; gap: 18px; }}
        label {{
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
        }}
        input[type=text], input[type=password] {{
            width: 100%;
            padding: 12px 14px;
            border-radius: 10px;
            border: 1px solid var(--border);
            background: rgba(15, 23, 42, 0.55);
            color: var(--text-primary);
            font-size: 0.95rem;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        input[type=text]:focus, input[type=password]:focus {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(76, 196, 255, 0.25);
        }}
        .actions {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin-top: 8px;
        }}
        .actions small {{
            color: var(--text-muted);
        }}
        input[type=submit] {{
            width: 100%;
            padding: 12px;
            border-radius: 10px;
            border: none;
            background: linear-gradient(135deg, rgba(76,196,255,0.85), rgba(76,196,255,0.65));
            color: #0b1221;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.2s ease;
        }}
        input[type=submit]:hover {{
            transform: translateY(-1px);
            background: linear-gradient(135deg, rgba(76,196,255,1), rgba(76,196,255,0.75));
            box-shadow: 0 12px 24px rgba(76,196,255,0.15);
        }}
        input[type=submit]:active {{
            transform: translateY(0);
        }}
        .error {{
            color: var(--danger);
            background: rgba(248, 113, 113, 0.12);
            border: 1px solid rgba(248, 113, 113, 0.35);
            padding: 10px 12px;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 4px;
        }}
        @media (max-width: 520px) {{
            .login-wrapper {{
                padding: 28px;
                border-radius: 16px;
            }}
        }}
    </style>
</head>
<body>
    <div class="login-wrapper">
        <div class="brand">
            <div class="brand-badge">MX</div>
            <div>
                <h2>Welcome back</h2>
                <span>Sign in to continue to MeTubeEX</span>
            </div>
        </div>
        <form action="" method="post">
            {error_message}
            <div>
                <label for="username">Username</label>
                <input type="text" id="username" name="username" autocomplete="username" required>
            </div>
            <div>
                <label for="password">Password</label>
                <input type="password" id="password" name="password" autocomplete="current-password" required>
            </div>
            <div class="actions">
                <small>Need access? Contact your administrator.</small>
            </div>
            <input type="submit" value="Sign in">
        </form>
    </div>
</body>
</html>
"""

# In-memory store for rate limiting
rate_limit_store = defaultdict(list)

def parse_rate_limit(limit_str):
    """Parses a rate limit string like '10/minute' into attempts and seconds."""
    parts = limit_str.split('/')
    if len(parts) != 2:
        return 10, 60  # Default

    try:
        attempts = int(parts[0])
        period_str = parts[1]

        if period_str == "minute":
            seconds = 60
        elif period_str == "hour":
            seconds = 3600
        else:
            seconds = 60 # Default

        return attempts, seconds
    except ValueError:
        return 10, 60 # Default

@web.middleware
async def rate_limit_middleware(request, handler):
    # Only apply to the login POST request
    if request.path.endswith('/login') and request.method == 'POST':
        # Use the remote's IP address for rate limiting
        ip = request.remote
        if not ip:
            return await handler(request)

        config = request.app['config']
        attempts, period = parse_rate_limit(config.LOGIN_RATELIMIT)

        # Clean up old timestamps
        current_time = time.monotonic()
        rate_limit_store[ip] = [t for t in rate_limit_store[ip] if t > current_time - period]

        # Check if the limit is exceeded
        if len(rate_limit_store[ip]) >= attempts:
            log.warning(f"Rate limit exceeded for IP {ip}")
            raise web.HTTPTooManyRequests(text="Too many login attempts. Please try again later.")

        # Record the new attempt
        rate_limit_store[ip].append(current_time)

    return await handler(request)

async def login_page(request, error=""):
    return web.Response(text=LOGIN_HTML.format(error_message=f'<p class="error">{error}</p>' if error else ''), content_type='text/html')

async def login_handler(request):
    if request.method == 'GET':
        session = await get_session(request)
        if session.get('authenticated'):
            return web.HTTPFound(request.app['config'].URL_PREFIX)
        return await login_page(request)

    if request.method == 'POST':
        data = await request.post()
        username = data.get('username')
        password = data.get('password')

        config = request.app['config']
        user_store: UserStore = request.app['user_store']

        user = user_store.validate_credentials(username, password)
        if user:
            session = await new_session(request)
            session['authenticated'] = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            log.info(f"Successful login for user '{username}'")
            user_store.record_login(user['id'])
            # Clear rate limit attempts on successful login
            if request.remote in rate_limit_store:
                del rate_limit_store[request.remote]
            return web.HTTPFound(request.app['config'].URL_PREFIX)
        else:
            log.warning(f"Failed login attempt for user '{username}'")
            return await login_page(request, "Invalid username or password")

    return web.HTTPMethodNotAllowed(method=request.method, allowed_methods=['GET', 'POST'])

async def logout_handler(request):
    session = await get_session(request)
    session.invalidate()
    log.info("User logged out.")
    return web.HTTPFound(request.app['config'].URL_PREFIX + 'login')

@web.middleware
async def auth_middleware(request, handler):
    session = await get_session(request)
    config = request.app['config']

    is_authenticated = session.get('authenticated', False)

    public_paths = [
        config.URL_PREFIX + 'login',
        config.URL_PREFIX + 'logout',
        config.URL_PREFIX + 'robots.txt'
    ]

    if request.path in public_paths:
        return await handler(request)

    if is_authenticated:
        return await handler(request)

    log.info(f"Unauthenticated request to {request.path}, redirecting to login.")
    return web.HTTPFound(config.URL_PREFIX + 'login')


def _invoke_connect_handler(handler, sid, environ, auth=None):
    """Invoke a socket.io connect handler with the appropriate signature."""
    params = inspect.signature(handler).parameters
    expects_auth = len(params) >= 3

    if asyncio.iscoroutinefunction(handler):
        if expects_auth:
            return handler(sid, environ, auth)
        return handler(sid, environ)

    if expects_auth:
        return handler(sid, environ, auth)
    return handler(sid, environ)


def setup_auth(app, sio, config, user_store: UserStore):
    if not config.SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be set to enable authentication")

    log.info("Authentication is enabled.")

    app['config'] = config
    app['user_store'] = user_store

    try:
        secret_key = bytes.fromhex(config.SECRET_KEY)
        if len(secret_key) != 32:
            raise ValueError("SECRET_KEY must be 32 bytes (64 hex characters).")
    except (ValueError, TypeError) as e:
        log.error(f"Invalid SECRET_KEY: {e}.")
        raise

    storage = NaClCookieStorage(secret_key)
    setup_session(app, storage)

    app.middlewares.append(rate_limit_middleware)
    app.middlewares.append(auth_middleware)

    app.router.add_route('GET', config.URL_PREFIX + 'login', login_handler)
    app.router.add_route('POST', config.URL_PREFIX + 'login', login_handler)
    app.router.add_route('GET', config.URL_PREFIX + 'logout', logout_handler)

    namespace_handlers = {}
    for namespace, handlers in sio.handlers.items():
        if not isinstance(handlers, dict):  # Compatibility with older versions
            continue
        original_connect = handlers.get('connect')
        if original_connect:
            namespace_handlers[namespace] = original_connect

    if not namespace_handlers:
        log.warning("No socket.io connect handlers registered; socket authentication wrapper not applied.")
        return

    for namespace, original_connect in namespace_handlers.items():
        async def auth_connect_handler(sid, environ, auth=None, _original=original_connect, _namespace=namespace):
            request = environ.get('aiohttp.request')
            if request is None:
                log.warning("Socket connection missing aiohttp.request context. Disconnecting.")
                raise socketio.exceptions.ConnectionRefusedError('Authentication required')

            session = await get_session(request)
            if not session.get('authenticated'):
                log.warning(f"Unauthenticated socket.io connection attempt from {request.remote}. Disconnecting.")
                raise socketio.exceptions.ConnectionRefusedError('Authentication required')

            request['user'] = {
                'id': session.get('user_id'),
                'username': session.get('username'),
                'role': session.get('role')
            }

            result = _invoke_connect_handler(_original, sid, environ, auth)
            if asyncio.iscoroutine(result):
                return await result
            return result

        sio.on('connect', namespace=namespace)(auth_connect_handler)
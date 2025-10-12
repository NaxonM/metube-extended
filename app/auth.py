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

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MeTubeEX | Login</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            color-scheme: dark;
            --bg-primary: #10172a;
            --bg-secondary: #04070f;
            --card-bg: rgba(15, 23, 42, 0.82);
            --card-border: rgba(148, 163, 184, 0.18);
            --text-strong: #f8fafc;
            --text-subtle: rgba(226, 232, 240, 0.72);
            --accent: #4cc4ff;
            --accent-soft: rgba(76, 196, 255, 0.14);
            --danger: #ef4444;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            min-height: 100dvh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: clamp(16px, 5vw, 32px);
            font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            color: var(--text-strong);
            background:
                radial-gradient(120% 120% at 15% 0%, rgba(76, 196, 255, 0.18) 0%, transparent 55%),
                radial-gradient(140% 140% at 85% 0%, rgba(129, 140, 248, 0.24) 0%, transparent 62%),
                linear-gradient(160deg, var(--bg-primary) 0%, var(--bg-secondary) 65%, #060812 100%);
        }}
        .auth-shell {{
            width: min(960px, 100%);
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            gap: clamp(24px, 5vw, 48px);
            align-items: stretch;
        }}
        .auth-hero {{
            display: none;
            position: relative;
            padding: clamp(32px, 6vw, 48px);
            border-radius: clamp(18px, 4vw, 28px);
            border: 1px solid rgba(76, 196, 255, 0.12);
            background:
                linear-gradient(145deg, rgba(20, 30, 53, 0.75) 0%, rgba(11, 19, 37, 0.6) 100%),
                linear-gradient(135deg, rgba(76, 196, 255, 0.22), rgba(76, 196, 255, 0));
            box-shadow: 0 40px 90px -45px rgba(15, 23, 42, 0.9);
            backdrop-filter: blur(18px);
        }}
        .auth-hero h1 {{
            margin: 0;
            font-size: clamp(2rem, 4vw, 2.45rem);
            font-weight: 600;
            letter-spacing: -0.01em;
        }}
        .auth-hero p {{
            margin: 18px 0 0;
            color: var(--text-subtle);
            line-height: 1.6;
            max-width: 36ch;
        }}
        .auth-hero-features {{
            margin-top: 28px;
            display: grid;
            gap: 12px;
        }}
        .auth-hero-features span {{
            display: inline-flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            border-radius: 12px;
            background: var(--accent-soft);
            color: var(--text-subtle);
        }}
        .auth-card {{
            width: min(440px, 100%);
            margin: 0 auto;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: clamp(18px, 4vw, 26px);
            box-shadow: 0 30px 70px -40px rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(18px);
            padding: clamp(28px, 6vw, 44px);
            display: grid;
            gap: clamp(22px, 3vw, 30px);
        }}
        .auth-brand {{
            display: flex;
            align-items: center;
            gap: clamp(14px, 3vw, 18px);
        }}
        .auth-badge {{
            width: clamp(44px, 7vw, 52px);
            aspect-ratio: 1;
            border-radius: 16px;
            display: grid;
            place-items: center;
            font-weight: 600;
            letter-spacing: 0.08em;
            background:
                linear-gradient(135deg, rgba(76, 196, 255, 0.32), rgba(76, 196, 255, 0.08)),
                linear-gradient(325deg, rgba(28, 37, 73, 0.85), rgba(13, 21, 39, 0.95));
            color: var(--accent);
        }}
        .auth-brand h2 {{
            margin: 0;
            font-size: clamp(1.45rem, 3vw, 1.75rem);
            font-weight: 600;
        }}
        .auth-brand span {{
            display: block;
            margin-top: 6px;
            font-size: 0.95rem;
            color: var(--text-subtle);
        }}
        form {{
            display: grid;
            gap: clamp(18px, 3vw, 24px);
        }}
        .field {{
            display: grid;
            gap: 10px;
        }}
        label {{
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-subtle);
        }}
        input[type=text],
        input[type=password] {{
            width: 100%;
            padding: 14px 16px;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(9, 13, 24, 0.72);
            color: var(--text-strong);
            font-size: 1rem;
            transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
        }}
        input[type=text]:focus,
        input[type=password]:focus {{
            outline: none;
            border-color: rgba(76, 196, 255, 0.55);
            background: rgba(13, 20, 35, 0.85);
            box-shadow: 0 0 0 3px rgba(76, 196, 255, 0.22);
        }}
        .auth-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            justify-content: space-between;
            font-size: 0.9rem;
            color: var(--text-subtle);
        }}
        .auth-submit {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            padding: 14px;
            border-radius: 12px;
            border: none;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            color: #071021;
            background: linear-gradient(135deg, rgba(76, 196, 255, 0.92), rgba(76, 196, 255, 0.72));
            box-shadow: 0 18px 35px rgba(76, 196, 255, 0.18);
            transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
        }}
        .auth-submit:hover {{
            transform: translateY(-1px);
            background: linear-gradient(135deg, rgba(76, 196, 255, 1), rgba(76, 196, 255, 0.82));
            box-shadow: 0 22px 40px rgba(76, 196, 255, 0.26);
        }}
        .auth-submit:active {{
            transform: translateY(0);
        }}
        .error {{
            padding: 12px 14px;
            border-radius: 12px;
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.32);
            color: #fca5a5;
            font-size: 0.95rem;
            text-align: center;
        }}
        @media (min-width: 960px) {{
            .auth-shell {{
                grid-template-columns: 1.1fr 0.9fr;
            }}
            .auth-hero {{
                display: block;
            }}
        }}
        @media (max-width: 640px) {{
            body {{
                padding: 16px;
            }}
            .auth-card {{
                padding: 26px;
                border-radius: 20px;
            }}
            .auth-meta {{
                flex-direction: column;
                align-items: flex-start;
            }}
        }}
    </style>
</head>
<body>
    <div class="auth-shell">
        <section class="auth-hero">
            <h1>Effortless downloads. Modern control.</h1>
            <p>Send jobs to yt-dlp or gallery-dl, monitor every stage of the queue, and stay in sync with the redesigned MeTubeEX dashboard.</p>
            <div class="auth-hero-features">
                <span>⚡ Smart backend selection</span>
                <span>🔐 Encrypted credentials & cookie profiles</span>
                <span>📦 Gallery-ready archives with telemetry</span>
            </div>
        </section>
        <section class="auth-card">
            <header class="auth-brand">
                <div class="auth-badge">MX</div>
                <div>
                    <h2>Sign in to MeTubeEX</h2>
                    <span>Enter your credentials to reach the dashboard</span>
                </div>
            </header>
            <form action="" method="post">
                {error_message}
                <div class="field">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username" autocomplete="username" required>
                </div>
                <div class="field">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" autocomplete="current-password" required>
                </div>
                <div class="auth-meta">
                    <span>Authorized access only.</span>
                    <span>Contact your admin if you need an account.</span>
                </div>
                <button class="auth-submit" type="submit">Continue</button>
            </form>
        </section>
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
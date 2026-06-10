# Shared slowapi limiter.
# Keys requests by Supabase user_id (sub claim) when a JWT is present, otherwise by IP.
# Behind a CDN / mobile CGNAT, IPs are heavily shared, so JWT-keying is much fairer.
import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

import config


def per_user_or_ip(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(
                auth[7:],
                config.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
                # We don't care about expiry for the *limit key* — even an expired token
                # still identifies the same user.
                options={"verify_exp": False},
            )
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except jwt.InvalidTokenError:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=per_user_or_ip)

"""JWT authentication and password hashing; no trusted client user ID headers."""
from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import JWT_SECRET
from app.database import reader

password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer()


def make_token(user_id: int) -> str:
    payload = {'sub': str(user_id), 'exp': datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> int:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        user_id = int(payload['sub'])
        with reader() as conn:
            user = conn.execute('SELECT id FROM users WHERE id=%s', (user_id,)).fetchone()
        if not user:
            raise ValueError('User not found')
        return user_id
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail='Invalid or expired access token',
                            headers={'WWW-Authenticate': 'Bearer'})

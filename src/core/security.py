from authx import AuthX, AuthXConfig
from pwdlib import PasswordHash
from src.core.settings import settings

_ADMIN_ACCESS_TOKEN_VALIDITY_1_DAY = 60 * 60 * 24
_ADMIN_REFRESH_TOKEN_VALIDITY_7_DAYS = 60 * 60 * 24 * 7

password_hash = PasswordHash.recommended()

def verify_password(plain_password, hashed_password):
    return password_hash.verify(plain_password, hashed_password)

def get_password_hash(password):
    return password_hash.hash(password)

config = AuthXConfig(
    JWT_SECRET_KEY=settings.JWT_SECRET_KEY,
    JWT_TOKEN_LOCATION=["headers"],
    JWT_ACCESS_TOKEN_EXPIRES= _ADMIN_ACCESS_TOKEN_VALIDITY_1_DAY,
    JWT_REFRESH_TOKEN_EXPIRES= _ADMIN_REFRESH_TOKEN_VALIDITY_7_DAYS
)

authX = AuthX(config=config)
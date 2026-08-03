from pydantic import BaseModel


class AuthURLResponse(BaseModel):
    url: str
    state: str


class TokenResponse(BaseModel):
    token: str
    email: str

from pydantic import BaseModel, EmailStr, Field, field_validator


def check_password_strength(v: str) -> str:
    if not v or v.strip() == "":
        raise ValueError("Password cannot be empty or whitespace")
    return v


class UserRegister(BaseModel):
    email: EmailStr

    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    invite_token: str | None = Field(default=None, max_length=200)
    accept_terms: bool = Field(default=False, validate_default=True)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return check_password_strength(v)

    @field_validator("accept_terms")
    @classmethod
    def _terms_accepted(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("You must accept the Terms of Service and the Privacy Policy")
        return v


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    # Same rules as registration.
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return check_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    # Audit CRIT-9: 8-char minimum on register. Aligned with change-password.
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        # Reject passwords that are nothing but whitespace.
        if not v or v.strip() == "":
            raise ValueError("Password cannot be empty or whitespace")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

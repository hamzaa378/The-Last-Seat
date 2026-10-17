from typing import Literal
from pydantic import BaseModel, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr = Field(examples=['student@example.com'])
    password: str = Field(min_length=8, max_length=128, examples=['ExamplePassword123!'])


class ReservationRequest(BaseModel):
    seat_number: int | None = Field(default=None, ge=1,
                                    description='Leave empty to automatically choose the first available seat.',
                                    examples=[10])


class PaymentRequest(BaseModel):
    outcome: Literal['success', 'failure', 'delayed_success', 'delayed_failure'] = 'success'
    delay_seconds: int | None = Field(default=None, ge=0, le=120)

from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BusinessType = Literal["poultry", "livestock", "crop", "fish", "produce", "mixed", "other"]
MovementType = Literal["stock_in", "stock_out", "sale", "loss", "adjustment"]

class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignupIn(StrictInput):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    business_name: str = Field(min_length=2, max_length=160)
    business_type: BusinessType
    @field_validator("name", "business_name")
    @classmethod
    def trim_names(cls, v):
        v = v.strip()
        if len(v) < 2: raise ValueError("Must contain at least 2 non-space characters")
        return v
    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@") or "." not in v.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address")
        return v

class LoginIn(StrictInput):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    @field_validator("email")
    @classmethod
    def normalize_email(cls, v): return v.strip().lower()

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    business_name: str
    business_type: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class ItemCreate(StrictInput):
    name: str = Field(min_length=1, max_length=140)
    category: str = Field(default="General", min_length=1, max_length=80)
    unit: str = Field(default="unit", min_length=1, max_length=32)
    opening_quantity: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=3)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=3)
    notes: str | None = Field(default=None, max_length=2000)
    @field_validator("name", "category", "unit")
    @classmethod
    def trim_required_strings(cls, v):
        v = v.strip()
        if not v: raise ValueError("This field cannot be blank")
        return v

class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; name: str; category: str; unit: str; quantity: Decimal; unit_cost: Decimal; reorder_level: Decimal; notes: str | None; created_at: datetime

class MovementCreate(StrictInput):
    item_id: int
    movement_type: MovementType
    quantity: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reason: str | None = Field(default=None, max_length=240)
    reference: str | None = Field(default=None, max_length=100)
    @model_validator(mode="after")
    def validate_quantity(self):
        if self.movement_type != "adjustment" and self.quantity <= 0: raise ValueError("Quantity must be greater than zero")
        return self

class MovementOut(BaseModel):
    id: int; item_id: int; item_name: str; unit: str; movement_type: str; quantity: Decimal; balance_after: Decimal; reason: str | None; reference: str | None; created_at: datetime

class DashboardOut(BaseModel):
    item_count: int; low_stock_count: int; total_stock_value: Decimal; recent_movements: list[MovementOut]

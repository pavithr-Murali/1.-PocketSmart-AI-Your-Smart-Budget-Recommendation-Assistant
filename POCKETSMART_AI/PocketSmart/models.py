"""Input schemas for the three planners."""
from typing import Optional
from pydantic import BaseModel, Field


class HomeBudgetInput(BaseModel):
    total_budget: float = Field(gt=0, le=1e9)
    num_lights: int = Field(0, ge=0, le=200)
    num_fans: int = Field(0, ge=0, le=100)
    num_furniture: int = Field(0, ge=0, le=200)
    num_dining_tables: int = Field(0, ge=0, le=50)
    has_living_room: bool = True
    has_kitchen: bool = True
    has_bedroom: bool = False
    additional_requirements: Optional[str] = Field(None, max_length=500)


class PartyBudgetInput(BaseModel):
    total_budget: float = Field(gt=0, le=1e9)
    num_guests: int = Field(ge=1, le=5000)
    party_type: str = Field("birthday", max_length=50)
    venue_type: Optional[str] = Field(None, max_length=100)
    needs_catering: bool = True
    needs_decoration: bool = True
    needs_entertainment: bool = True
    additional_requirements: Optional[str] = Field(None, max_length=500)


class JewelryBudgetInput(BaseModel):
    total_budget: float = Field(gt=0, le=1e9)
    occasion: str = Field(min_length=1, max_length=100)
    preferences: Optional[str] = Field(None, max_length=500)

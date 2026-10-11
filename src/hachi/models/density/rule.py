"""The thinning rules as dependency-free contracts, so serving profiles can name them."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract


class ThinningRule(Contract):
    metric: Literal["heart_rate"] = "heart_rate"
    slot_seconds: Annotated[int, Field(gt=0, le=3600)]
    keep: Literal["earliest_start_per_utc_slot"] = "earliest_start_per_utc_slot"
    pipeline_suffix: Annotated[str, Field(pattern=r"^[A-Za-z0-9._+-]{1,24}$")]

    @model_validator(mode="after")
    def _tiles(self) -> Self:
        if 3600 % self.slot_seconds:
            raise ValueError("slots must tile the hour")
        return self

    @property
    def slots_per_hour(self) -> int:
        return 3600 // self.slot_seconds


class AppleMinuteThinning(ThinningRule):
    """Amendment 1: re-bin exactly like the Apple serving helper (apple_health.hourly).

    Coverage is distinct sampled start minutes / 60, and a bin is null only when it holds no
    sample; density gates live in the feature policy, as they do for served Apple features.
    """

    coverage: Literal["distinct_sampled_minutes_per_60"]

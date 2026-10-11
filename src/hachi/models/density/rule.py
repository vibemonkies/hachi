"""The thinning rule as a dependency-free contract, so serving profiles can name it."""

from typing import Annotated, Literal

from pydantic import Field

from hachi.contracts.base import Contract


class ThinningRule(Contract):
    metric: Literal["heart_rate"] = "heart_rate"
    slot_seconds: Annotated[int, Field(gt=0, le=3600)]
    keep: Literal["earliest_start_per_utc_slot"] = "earliest_start_per_utc_slot"
    pipeline_suffix: Annotated[str, Field(pattern=r"^[A-Za-z0-9._+-]{1,24}$")]

    @property
    def slots_per_hour(self) -> int:
        if 3600 % self.slot_seconds:
            raise ValueError("slots must tile the hour")
        return 3600 // self.slot_seconds

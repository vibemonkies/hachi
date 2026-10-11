import pytest

from hachi.data.apple_health import ImportConfig


@pytest.fixture
def config():
    return ImportConfig(
        dataset_id="synthetic-apple",
        subject_id="synthetic-001",
        declared_tz_name="America/Los_Angeles",
        data_mode="synthetic",
    )

"""Contract-based CPU evaluation primitives. Real-cohort issue #7 acceptance is pending."""

from .artifacts import document_sha256, write_comparison_packet, write_packet
from .comparison import ComparisonResult, compare_forecasts
from .forecast import (
    EvaluationConfig,
    EvaluationResult,
    ForecastEstimate,
    ForecastInput,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
    evaluate_forecast,
)
from .splits import partition_participants, rolling_origins

__all__ = [
    "ComparisonResult",
    "EvaluationConfig",
    "EvaluationResult",
    "ForecastEstimate",
    "ForecastInput",
    "Predictor",
    "PredictorFactory",
    "TrainingPrefix",
    "compare_forecasts",
    "document_sha256",
    "evaluate_forecast",
    "partition_participants",
    "rolling_origins",
    "write_comparison_packet",
    "write_packet",
]

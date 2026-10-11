"""Contract-based CPU evaluation primitives. Real-cohort issue #7 acceptance is pending."""

from .artifacts import document_sha256, write_comparison_packet, write_packet
from .comparison import ComparisonResult, compare_forecasts
from .features import (
    ForecastObservation,
    HourlyFeature,
    HourlyFeaturePolicy,
    HourlyFeatureView,
    hourly_features,
)
from .folds import NestedFold, NestedFoldConfig, NestedFoldPlan, nested_participant_folds
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
    "ForecastObservation",
    "HourlyFeature",
    "HourlyFeaturePolicy",
    "HourlyFeatureView",
    "NestedFold",
    "NestedFoldConfig",
    "NestedFoldPlan",
    "Predictor",
    "PredictorFactory",
    "TrainingPrefix",
    "compare_forecasts",
    "document_sha256",
    "evaluate_forecast",
    "hourly_features",
    "nested_participant_folds",
    "partition_participants",
    "rolling_origins",
    "write_comparison_packet",
    "write_packet",
]

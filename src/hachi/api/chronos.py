"""Serve a pinned Chronos-2 artifact (#10/#12) through the GX10, with the evaluator's adapter.

The API builds `ForecastInput` exactly as `evaluate_forecast` does; this wrapper then calls
the same committed functions #10's validation runs used: `build_request` turns the causal
hourly history into one context request, the GX10 runs `inference.py` under `gpu-run`,
and `estimates` maps the verified quantiles to median and q0.1-q0.9 intervals.

An artifact with a longer context (#12's selected `ctx720`) keeps the 48 h harness history
and builds its request with #12's `extended_builder` over the subject's `ContextIndex`, so
the context the GPU sees is the one #12 evaluated.
"""

from dataclasses import dataclass
from datetime import datetime

from hachi.evaluation import ForecastEstimate, ForecastInput
from hachi.evaluation.context import ContextIndex
from hachi.models.chronos import ChronosConfig, build_request, estimates
from hachi.models.chronos.adapter import ContextRequest, extended_builder
from hachi.models.chronos.artifacts import ChronosArtifact

from .gpu import GpuUnavailable, Gx10Target, chronos_quantiles

ENTRY_POINT = "hachi.models.chronos.artifacts.load_artifact"


@dataclass(frozen=True)
class ChronosServed:
    """A zero-shot Chronos-2 artifact; `predict` runs one GX10 job per forecast."""

    artifact: ChronosArtifact
    target: Gx10Target | None

    fit_as_of: datetime | None = None  # zero-shot: nothing was fitted on the cohort

    @property
    def config(self) -> ChronosConfig:
        return self.artifact.chronos

    @property
    def model_id(self) -> str:
        return self.artifact.model_id

    def context_request(
        self, request: ForecastInput, context: ContextIndex | None = None
    ) -> ContextRequest | None:
        """The exact request a forecast sends to the GX10, or None when the model abstains.

        `context` is the subject's index, required when the artifact has a longer context.
        """
        if self.artifact.context_policy is None:
            return build_request(request, self.config)
        if context is None:
            raise ValueError("this artifact's longer context needs the subject's context index")
        build = extended_builder(
            self.config,
            context,
            context_hours=self.config.context_hours,
            harness_lookback_hours=self.artifact.harness_lookback_hours,
            covariates=self.artifact.past_covariates,
        )
        return build(request)

    def predict(
        self, request: ForecastInput, context: ContextIndex | None = None
    ) -> tuple[ForecastEstimate | None, ...]:
        built = self.context_request(request, context)
        if built is None:  # too little context: abstain, as the evaluator does
            return (None,) * len(request.targets)
        if self.target is None:
            raise GpuUnavailable("this API instance has no GX10 connection configured")
        quantiles = chronos_quantiles(self.target, self.config.model, built.row())
        output, _ = estimates(quantiles.rows, quantiles.levels, built.steps, self.config)
        return output

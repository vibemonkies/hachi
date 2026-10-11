"""Pure transition checks shared by append and full-chain verification."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from hachi.contracts.base import local_day_bounds
from hachi.evaluation.serialization import document_sha256

from .specification import FollowUp, Prediction, Protocol, Receipt, Registration


class ProspectiveRefused(ValueError):
    """Fixed messages contain no paths, subject identities, or prediction values."""


def require_transition(receipts: list[Receipt], receipt: Receipt) -> None:
    body, payload = receipt.body, receipt.body.payload
    if body.sequence != len(receipts) or body.previous_sha256 != (
        receipts[-1].sha256 if receipts else None
    ):
        raise ProspectiveRefused("receipt order or predecessor differs")
    if receipt.sha256 != document_sha256(body):
        raise ProspectiveRefused("receipt content differs from its hash")
    if receipts and body.logged_at_utc <= receipts[-1].body.logged_at_utc:
        raise ProspectiveRefused("local receipt clock must strictly increase")
    if not receipts:
        if not isinstance(payload, Registration) or payload.protocol.data_mode != "synthetic":
            raise ProspectiveRefused("preparation requires a synthetic protocol first")
        return
    first = receipts[0].body.payload
    assert isinstance(first, Registration)
    protocol = first.protocol
    if isinstance(payload, Registration):
        raise ProspectiveRefused("a version change requires a new prospective journal")
    if isinstance(payload, Prediction):
        _prediction(protocol, receipts, receipt, payload)
    else:
        _follow_up(receipts, receipt, payload)


def _prediction(
    protocol: Protocol, receipts: list[Receipt], receipt: Receipt, prediction: Prediction
) -> None:
    request, result = prediction.request.root, prediction.result.root
    now = receipt.body.logged_at_utc
    if result.data_mode != "synthetic" or result.replay is not None:
        raise ProspectiveRefused("preparation refuses real or replayed results")
    if prediction.protocol_sha256 != document_sha256(protocol) or (
        prediction.system_sha256 != document_sha256(protocol.system)
        or result.git_sha != protocol.system.git_sha
    ):
        raise ProspectiveRefused("protocol or system identity differs")
    if (request.subject_id, request.as_of, request.task) != (
        result.subject_id,
        result.as_of,
        result.task,
    ):
        raise ProspectiveRefused("canonical result does not answer its request")
    if not receipts[0].body.logged_at_utc < request.as_of <= result.generated_at_utc <= now:
        raise ProspectiveRefused("prediction was not generated after registration and cutoff")
    if now - request.as_of > timedelta(seconds=protocol.max_recording_delay_seconds):
        raise ProspectiveRefused("prediction backfill or late recording refused")
    if not now < prediction.window_start_utc < prediction.window_end_utc:
        raise ProspectiveRefused("prediction must be saved before its outcome window starts")
    prior_predictions = [r.body.payload for r in receipts if isinstance(r.body.payload, Prediction)]
    if any(
        p.result.root.report_id == result.report_id
        or document_sha256(p.request) == document_sha256(prediction.request)
        or (p.request.root.subject_id, p.request.root.task, p.window_start_utc)
        == (request.subject_id, request.task, prediction.window_start_utc)
        for p in prior_predictions
    ):
        raise ProspectiveRefused("prediction already exists for this report or window")
    # Canonical requests do not carry a timezone. Pin it in the protocol instead.
    day = request.as_of.astimezone(ZoneInfo(protocol.tz_name)).date() + timedelta(days=1)
    if (prediction.window_start_utc, prediction.window_end_utc) != local_day_bounds(
        day, protocol.tz_name
    ):
        raise ProspectiveRefused("outcome window differs from the prechosen next local day")
    if result.status == "ok":
        if request.task != "physiology_forecast" or result.task != "physiology_forecast":
            raise ProspectiveRefused(
                "successful clinical tasks await endpoint and freeze acceptance"
            )
        if request.resolution != "day" or result.forecast.resolution != "day":
            raise ProspectiveRefused("preparation supports next-local-day forecasts only")
        if result.forecast.tz_name != protocol.tz_name:
            raise ProspectiveRefused("forecast timezone differs from protocol")
        if result.provenance.artifact != protocol.system.artifact or (
            result.provenance.dataset_snapshot != prediction.dataset_snapshot
        ):
            raise ProspectiveRefused("forecast artifact or input snapshot differs")
        metrics = {s.metric for s in result.forecast.series} | {
            m.metric for m in result.forecast.unavailable_metrics
        }
        if (
            request.metrics is None
            or metrics != set(request.metrics)
            or set(request.metrics) != {t.metric for t in protocol.targets}
        ):
            raise ProspectiveRefused("forecast must account for every explicitly requested metric")
        if any(
            (p.interval_start_utc, p.interval_end_utc)
            != (prediction.window_start_utc, prediction.window_end_utc)
            for s in result.forecast.series
            for p in s.points
        ):
            raise ProspectiveRefused("forecast intervals differ from prechosen window")
    elif result.status == "unavailable" and result.provenance is not None:
        provenance = result.provenance
        if (
            provenance.dataset_snapshot is not None
            and (provenance.dataset_snapshot != prediction.dataset_snapshot)
        ) or (provenance.artifact is not None and provenance.artifact != protocol.system.artifact):
            raise ProspectiveRefused("partial provenance differs from pinned system or data")


def _follow_up(receipts: list[Receipt], receipt: Receipt, follow_up: FollowUp) -> None:
    candidates = [r for r in receipts if r.sha256 == follow_up.prediction_sha256]
    if not candidates or not isinstance(candidates[0].body.payload, Prediction):
        raise ProspectiveRefused("follow-up requires an earlier pinned prediction")
    first = receipts[0].body.payload
    assert isinstance(first, Registration)
    aggregations = {t.metric: t.aggregation for t in first.protocol.targets}
    prediction_receipt = candidates[0]
    prediction = prediction_receipt.body.payload
    now = receipt.body.logged_at_utc
    if follow_up.outcome_snapshot.dataset_id != prediction.dataset_snapshot.dataset_id:
        raise ProspectiveRefused("follow-up must extend the same source dataset")
    if follow_up.data_mode != "synthetic":
        raise ProspectiveRefused("preparation refuses real follow-up")
    if any(
        isinstance(r.body.payload, FollowUp)
        and r.body.payload.prediction_sha256 == follow_up.prediction_sha256
        for r in receipts
    ):
        raise ProspectiveRefused("follow-up already finalized; no overwrite or backfill")
    if not prediction_receipt.body.logged_at_utc < follow_up.recorded_at_utc <= now:
        raise ProspectiveRefused("follow-up recording must follow saved prediction")
    observation_start = (
        prediction_receipt.body.logged_at_utc
        if follow_up.status == "right_censored"
        else prediction.window_start_utc
    )
    if (
        not observation_start
        <= follow_up.observed_through_utc
        <= min(now, prediction.window_end_utc)
        or follow_up.recorded_at_utc < follow_up.observed_through_utc
    ):
        raise ProspectiveRefused("follow-up observation or recording time differs from window")
    if follow_up.status == "observed":
        if follow_up.observed_through_utc != prediction.window_end_utc:
            raise ProspectiveRefused("observed follow-up requires the complete target window")
        if not follow_up.aggregates or follow_up.missing_reason is not None:
            raise ProspectiveRefused("observed follow-up requires canonical measured aggregates")
        result = prediction.result.root
        if result.status != "ok" or result.task != "physiology_forecast":
            raise ProspectiveRefused("unavailable or failed predictions cannot be scored")
        expected = {s.metric for s in result.forecast.series}
        if len(follow_up.aggregates) != len(expected) or (
            {a.metric for a in follow_up.aggregates} != expected
        ):
            raise ProspectiveRefused("follow-up must retain every forecast target including nulls")
        for aggregate in follow_up.aggregates:
            if (
                aggregate.subject_id != prediction.request.root.subject_id
                or aggregate.dataset_id != follow_up.outcome_snapshot.dataset_id
                or aggregate.resolution != "day"
                or aggregate.aggregation != aggregations[aggregate.metric]
                or aggregate.tz_name != result.forecast.tz_name
                or (aggregate.interval_start_utc, aggregate.interval_end_utc)
                != (prediction.window_start_utc, prediction.window_end_utc)
            ):
                raise ProspectiveRefused("measured aggregate differs from subject or target window")
    elif follow_up.aggregates or follow_up.missing_reason is None:
        raise ProspectiveRefused(
            "missing or censored follow-up needs a reason and no invented data"
        )
    if follow_up.status == "missing" and now < prediction.window_end_utc:
        raise ProspectiveRefused("missing follow-up is finalized only after the target window")

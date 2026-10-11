import zipfile
from datetime import date

from hachi.models.baselines.stanford.source import phase1_members, read_native_nights


def test_native_parser_quarantines_bad_points_and_excludes_other_stream_variants(tmp_path):
    archive = tmp_path / "generated.zip"
    root = "COVID-19-Wearables/"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(
            root + "ABC1234_hr.csv",
            "user,datetime,heartrate\n"
            "ABC1234,2020-01-01 00:00:15,60\n"
            "ABC1234,2020-01-01 00:01:15,nan\n"
            "WRONG00,2020-01-01 00:02:15,200\n"
            "ABC1234,2020-01-01 00:03:15+00:00,70\n"
            "ABC1234,2020-01-01 12:00:15,120\n",
        )
        z.writestr(
            root + "ABC1234_steps.csv",
            "user,datetime,steps\n"
            "ABC1234,2020-01-01 00:00:00,0\n"
            "ABC1234,2020-01-01 00:01:00,0\n"
            "ABC1234,2020-01-01 00:01:30,0\n"
            "ABC1234,2020-01-01 07:00:00,0\n",
        )
        z.writestr(root + "ABC1234_hr_longterm.csv", "unread variant")
    members = phase1_members(archive)
    view = read_native_nights(archive, members, "ABC1234", date(2020, 1, 1), date(2020, 1, 1))
    assert len(view.heart_rate[date(2020, 1, 1)]) == 1
    assert len(view.steps[date(2020, 1, 1)]) == 3
    assert view.counts["heart_rate_quarantined_value_or_alignment"] == 1
    assert view.counts["heart_rate_quarantined_subject_mismatch"] == 1
    assert view.counts["heart_rate_quarantined_timestamp"] == 1
    assert view.counts["steps_quarantined_value_or_alignment"] == 1
    assert all("longterm" not in n for n in view.members)
    unavailable = read_native_nights(
        archive, members, "ABSENT0", date(2020, 1, 1), date(2020, 1, 1)
    )
    assert unavailable.counts == {"excluded_no_standard_pair": 1}

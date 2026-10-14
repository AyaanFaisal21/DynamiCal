import pytest

from dynamical.ingest.triage import triage

EXPECTED = {
    "01_eventbrite_confirmation": "extract",
    "02_newsletter_promo": "skip",
    "03_friend_dinner": "extract",
    "04_gcal_invite": "ics",
    "05_course_exam": "extract",
    "06_org_mass_invite": "skip",
    "07_canvas_assignment": "extract",
    "08_health_appointment": "extract",
    "09_dept_colloquium": "extract",
}


@pytest.mark.parametrize("name,decision", sorted(EXPECTED.items()))
def test_decisions(load, settings, name, decision):
    result = triage(load(name), settings)
    assert result.decision == decision, f"{name}: score {result.score}, reasons {result.reasons}"


def test_hints(load, settings):
    exam = triage(load("05_course_exam"), settings)
    assert exam.hints["trusted_sender"] is True
    assert exam.hints["bulk"] is True  # it came through a list
    invite = triage(load("04_gcal_invite"), settings)
    assert invite.hints["ics_method"] == "REQUEST"
    assert invite.hints["direct_to_me"] is True
    promo = triage(load("02_newsletter_promo"), settings)
    assert promo.score <= -4
    assert any("promotions" in r for r in promo.reasons)


def test_empty_body_is_skipped(load, settings):
    mail = load("03_friend_dinner")
    mail.body_text = "   "
    assert triage(mail, settings).decision == "skip"

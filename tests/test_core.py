from datetime import date
from certificate_validator.compare import compare
from certificate_validator.models import Record
from certificate_validator.normalize import company_match, project_match


def rec(no, cert, day, project="A 공사", company="주식회사 한빛건설", revised=None):
    return Record(no, cert, day, revised, project, company, "시료")


def test_normalization_allows_common_notation_difference():
    assert company_match("주식회사 호영산업개발", "(주)호영산업개발")[0]
    assert project_match("평리로72길 일원 하수관로 정비공사", "평리로72길일원하수관로정비공사")[0]


def test_normal_issue_matches_register_issue_date():
    d = date(2026, 8, 31)
    csi = [rec("AC-1", "IS-2026-100000-00", d)]
    mgmt = [rec("AC-1", "IS-2026-100000-00", d)]
    reg = [rec("AC-1", "IS-2026-100000-00", d)]
    rows = compare(csi, mgmt, reg)
    assert rows[0].status == "정상"


def test_revision_uses_revised_issue_date():
    first = date(2026, 8, 12)
    revised = date(2026, 8, 31)
    csi = [rec("AC-2", "IS-2026-140572-01", revised)]
    mgmt = [rec("AC-2", "IS-2026-140572-01", revised)]
    reg = [rec("AC-2", "IS-2026-140572-01", first, revised=revised)]
    rows = compare(csi, mgmt, reg)
    assert rows[0].status == "정상"


def test_missing_management_certificate_is_error():
    d = date(2026, 8, 31)
    csi = [rec("AC-3", "IS-2026-152070-00", d)]
    mgmt = [rec("AC-3", "", d)]
    reg = [rec("AC-3", "IS-2026-152070-00", d)]
    row = compare(csi, mgmt, reg)[0]
    assert row.status == "오류"
    assert "관리프로그램 성적서번호 누락" in row.error_fields


def test_extra_non_csi_issue_is_review_not_error():
    d = date(2026, 7, 30)
    rows = compare([], [rec("AC-OLD", "IS-2026-1-00", d)], [])
    assert rows[0].status == "확인 필요"

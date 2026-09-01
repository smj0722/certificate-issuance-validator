from __future__ import annotations
from collections import Counter
from .models import ComparisonRow, Record, is_revised
from .normalize import company_match, project_match


def _index(records: list[Record]) -> tuple[dict[str, Record], set[str]]:
    counts = Counter(r.receipt_no for r in records)
    duplicates = {k for k, v in counts.items() if v > 1}
    return {r.receipt_no: r for r in records}, duplicates


def compare(csi_records: list[Record], management_records: list[Record], register_records: list[Record]) -> list[ComparisonRow]:
    csi, dup_csi = _index(csi_records)
    mgmt, dup_mgmt = _index(management_records)
    reg, dup_reg = _index(register_records)
    result: list[ComparisonRow] = []

    for receipt, source in csi.items():
        m = mgmt.get(receipt)
        r = reg.get(receipt)
        errors: list[str] = []
        reasons: list[str] = []
        warnings: list[str] = []

        if receipt in dup_csi or receipt in dup_mgmt or receipt in dup_reg:
            errors.append("접수번호 중복")
            reasons.append("같은 접수번호가 한 파일 안에서 중복되었습니다.")

        if m is None:
            errors.append("관리프로그램 누락")
            reasons.append("CSI 발급건이 관리프로그램 발행리스트에 없습니다.")
        if r is None:
            errors.append("접수대장 누락")
            reasons.append("CSI 발급건이 접수대장 건설 시트에 없습니다.")

        for label, target in (("관리프로그램", m), ("접수대장", r)):
            if target is None:
                continue
            ok, _, _ = project_match(source.project_name, target.project_name)
            if not ok:
                warnings.append(f"{label} 공사명")
                reasons.append(f"{label} 공사명이 CSI와 크게 다릅니다.")
            ok, _, _ = company_match(source.company_name, target.company_name)
            if source.company_name and target.company_name and not ok:
                warnings.append(f"{label} 업체")
                reasons.append(f"{label} 업체명이 CSI와 크게 다릅니다.")

        if m is not None:
            if not m.certificate_no:
                errors.append("관리프로그램 성적서번호 누락")
                reasons.append("관리프로그램 성적서번호가 비어 있습니다.")
            elif m.certificate_no != source.certificate_no:
                errors.append("관리프로그램 성적서번호")
                reasons.append("관리프로그램 성적서번호가 CSI와 다릅니다.")
            if m.issue_date != source.issue_date:
                errors.append("관리프로그램 발급일자")
                reasons.append("관리프로그램 발행일이 CSI와 다릅니다.")

        if r is not None:
            if not r.certificate_no:
                errors.append("접수대장 성적서번호 누락")
                reasons.append("접수대장 성적서번호가 비어 있습니다.")
            elif r.certificate_no != source.certificate_no:
                errors.append("접수대장 성적서번호")
                reasons.append("접수대장 성적서번호가 CSI와 다릅니다.")
            target_date = r.revised_issue_date if is_revised(source.certificate_no) else r.issue_date
            date_label = "수정발급일자" if is_revised(source.certificate_no) else "발급일자"
            if target_date != source.issue_date:
                errors.append(f"접수대장 {date_label}")
                reasons.append(f"접수대장 {date_label}가 CSI와 다릅니다.")

        if errors:
            status = "오류"
            fields = errors + [w for w in warnings if w not in errors]
        elif warnings:
            status = "확인 필요"
            fields = warnings
        else:
            status = "정상"
            fields = []

        result.append(ComparisonRow(receipt, status, fields, reasons, source, m, r))

    # 접수대장은 누적 대장이므로 전체 역방향 비교를 하면 과거 발급분이 수천 건 잡힌다.
    # 관리프로그램의 현재 발행목록과 CSI 발급일 범위에 해당하는 접수대장 건만 확인 후보로 본다.
    csi_dates = {x.issue_date for x in csi_records if x.issue_date}
    extra_receipts = set(mgmt) - set(csi)
    for receipt, rr in reg.items():
        if receipt in csi:
            continue
        effective_date = rr.revised_issue_date if is_revised(rr.certificate_no) and rr.revised_issue_date else rr.issue_date
        if effective_date in csi_dates and (rr.certificate_no or effective_date):
            extra_receipts.add(receipt)

    for receipt in sorted(extra_receipts):
        m, r = mgmt.get(receipt), reg.get(receipt)
        result.append(ComparisonRow(
            receipt_no=receipt,
            status="확인 필요",
            error_fields=["CSI에 없는 발급정보"],
            reasons=["이번 CSI 발급대장에는 없지만 같은 발급 범위의 관리프로그램 또는 접수대장에 발급정보가 있습니다. 이전 발급분 또는 잘못 입력된 건인지 확인하세요."],
            csi=None,
            management=m,
            register=r,
        ))

    priority = {"오류": 0, "확인 필요": 1, "정상": 2}
    result.sort(key=lambda x: (priority[x.status], x.receipt_no))
    return result

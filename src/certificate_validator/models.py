from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

Status = Literal["정상", "오류", "확인 필요"]

@dataclass(slots=True)
class Record:
    receipt_no: str
    certificate_no: str = ""
    issue_date: date | None = None
    revised_issue_date: date | None = None
    project_name: str = ""
    company_name: str = ""
    sample_name: str = ""
    note: str = ""
    source_path: Path | None = None

@dataclass(slots=True)
class ComparisonRow:
    receipt_no: str
    status: Status
    error_fields: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    csi: Record | None = None
    management: Record | None = None
    register: Record | None = None

    @property
    def issue_date_summary(self) -> str:
        if not self.csi:
            return "확인 필요"
        bad = []
        if self.management and self.management.issue_date != self.csi.issue_date:
            bad.append("관리")
        if self.register:
            target = self.register.revised_issue_date if is_revised(self.csi.certificate_no) else self.register.issue_date
            if target != self.csi.issue_date:
                bad.append("접수대장")
        return "일치" if not bad else f"{', '.join(bad)} 불일치"

    @property
    def certificate_summary(self) -> str:
        if not self.csi:
            return "확인 필요"
        bad = []
        if self.management and self.management.certificate_no != self.csi.certificate_no:
            bad.append("관리")
        if self.register and self.register.certificate_no != self.csi.certificate_no:
            bad.append("접수대장")
        return "일치" if not bad else f"{', '.join(bad)} 불일치"


def is_revised(certificate_no: str) -> bool:
    if not certificate_no:
        return False
    tail = certificate_no.rsplit("-", 1)[-1]
    return tail.isdigit() and tail != "00"

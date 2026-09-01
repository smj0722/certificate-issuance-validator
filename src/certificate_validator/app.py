from __future__ import annotations
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QMessageBox, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QFrame, QAbstractItemView, QTextBrowser,
    QProgressBar, QSplitter, QStyledItemDelegate, QStyle
)

from . import __version__
from .compare import compare
from .exporter import export_results
from .io_utils import find_register, newest_management_file
from .models import is_revised
from .parsers import classify_file, parse_csi, parse_management, parse_register
from .settings import append_history, load_settings, save_settings
from .updater import check_update


class DropZone(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self.setMinimumHeight(170)
        self.setMaximumHeight(210)
        layout = QVBoxLayout(self)
        title = QLabel("CSI 발급대장과 발행리스트를 여기에 드래그")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("두 파일을 한 번에 놓아도 자동으로 구분합니다.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setObjectName("muted")
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addStretch()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        self.window().accept_files(paths)


class NoFocusDelegate(QStyledItemDelegate):
    """선택 배경은 유지하고 현재 셀의 편집 커서처럼 보이는 포커스 테두리만 제거한다."""

    def paint(self, painter: QPainter, option, index):
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class CopyTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setTextElideMode(Qt.ElideNone)
        self.setItemDelegate(NoFocusDelegate(self))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        index = self.indexAt(pos)
        if index.isValid() and not self.selectionModel().isSelected(index):
            self.clearSelection()
            self.setCurrentCell(index.row(), index.column())
            self.item(index.row(), index.column()).setSelected(True)
        if not self.selectedItems():
            return
        menu = QMenu(self)
        act = QAction("복사", self)
        act.triggered.connect(self.copy_selection)
        menu.addAction(act)
        menu.exec(self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        super().keyPressEvent(event)

    def copy_selection(self):
        selected = self.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(i.row() for i in selected))
        cols = sorted(set(i.column() for i in selected))
        text_rows = []
        for r in rows:
            vals = []
            for c in cols:
                item = self.item(r, c)
                vals.append(item.text() if item else "")
            text_rows.append("\t".join(vals))
        QApplication.clipboard().setText("\n".join(text_rows))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.csi_path: Path | None = None
        self.management_path: Path | None = None
        self.register_path: Path | None = find_register(self.settings["register_root"])
        self.rows = []
        self.excluded_general = 0
        self.setWindowTitle(f"성적서 발급검증 v{__version__}")
        self.resize(1100, 610)
        self._build()
        self._refresh_status()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("성적서 발급검증")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        up = QPushButton("업데이트 확인")
        up.clicked.connect(self.update_check)
        header.addWidget(up)
        outer.addLayout(header)

        self.drop = DropZone(self)
        outer.addWidget(self.drop)

        self.status = QLabel()
        self.status.setObjectName("statusCard")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.status)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("progressLabel")
        self.progress_label.hide()
        outer.addWidget(self.progress_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.addStretch()
        browse = QPushButton("파일 선택")
        browse.clicked.connect(self.browse_files)
        buttons.addWidget(browse)
        self.start_btn = QPushButton("검사 시작")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.run_check)
        buttons.addWidget(self.start_btn)
        outer.addLayout(buttons)

    def accept_files(self, paths: list[Path]):
        errors = []
        for p in paths:
            try:
                kind = classify_file(p)
                if kind == "csi":
                    self.csi_path = p
                elif kind == "management":
                    self.management_path = p
                    self.settings["last_download_dir"] = str(p.parent)
                elif kind == "register":
                    self.register_path = p
            except Exception as e:
                errors.append(f"{p.name}: {e}")
        save_settings(self.settings)
        self._refresh_status()
        if errors:
            QMessageBox.warning(self, "파일 확인", "\n".join(errors))

    def _refresh_status(self):
        def mark(p, label):
            return f"✅ {label}: {p.name}" if p else f"⚠️ {label}: 없음"

        reg = (
            f"✅ 접수대장: {self.register_path}"
            if self.register_path
            else f"⚠️ 접수대장: {self.settings['register_root']}에서 찾지 못함"
        )
        self.status.setText("\n".join([
            mark(self.csi_path, "CSI 발급대장"),
            mark(self.management_path, "발행리스트"),
            reg,
        ]))
        self.start_btn.setEnabled(bool(self.csi_path and self.management_path and self.register_path))

    def browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "파일 선택",
            self.settings["last_download_dir"],
            "Excel (*.xlsx *.xls *.xlsm)",
        )
        if files:
            self.accept_files([Path(x) for x in files])

    def _progress_step(self, value: int, text: str):
        self.progress_label.setText(text)
        self.progress.setValue(value)
        self.progress_label.show()
        self.progress.show()
        QApplication.processEvents()

    def run_check(self):
        self.start_btn.setEnabled(False)
        try:
            self._progress_step(10, "1/4  CSI 발급대장을 읽는 중...")
            csi = parse_csi(self.csi_path)

            self._progress_step(35, "2/4  발행리스트를 읽는 중...")
            mgmt, self.excluded_general = parse_management(self.management_path)

            self._progress_step(60, "3/4  접수대장을 읽는 중...")
            self.register_path = find_register(self.settings["register_root"]) or self.register_path
            reg = parse_register(self.register_path)

            self._progress_step(82, "4/4  세 파일을 비교하는 중...")
            self.rows = compare(csi, mgmt, reg)
            self._progress_step(100, "검사 완료. 결과를 여는 중...")
        except Exception as e:
            self.progress_label.setText("검사 중 오류가 발생했습니다.")
            QMessageBox.critical(self, "검사 실패", str(e))
            self._refresh_status()
            return
        finally:
            self.start_btn.setEnabled(bool(self.csi_path and self.management_path and self.register_path))

        counts = {s: sum(1 for x in self.rows if x.status == s) for s in ("정상", "오류", "확인 필요")}
        append_history({
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "csi": self.csi_path.name,
            "management": self.management_path.name,
            "compared": len(csi),
            "normal": counts["정상"],
            "error": counts["오류"],
            "review": counts["확인 필요"],
            "excluded_general": self.excluded_general,
        })
        self.show_results(counts, len(csi))

    def _make_tab(self, rows, full=False):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        table = CopyTable()
        detail = QTextBrowser()
        detail.setObjectName("detail")
        detail.setMinimumHeight(250)
        detail.setPlaceholderText("행을 선택하면 CSI · 관리프로그램 · 접수대장 원본값을 비교해 보여줍니다.")

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(table)
        splitter.addWidget(detail)
        splitter.setSizes([430, 310])
        layout.addWidget(splitter, 1)

        if full:
            self._fill_all(table, rows)
        else:
            self._fill_review(table, rows)
        table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._show_detail(detail, rows, r))
        if rows:
            table.setCurrentCell(0, 0)
            self._show_detail(detail, rows, 0)
        return widget

    def show_results(self, counts, compared):
        win = QMainWindow(self)
        win.setWindowTitle("검사 결과")
        win.resize(1380, 920)
        root = QWidget()
        win.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(16, 16, 16, 16)

        summary = QLabel(
            f"비교 {compared}건   |   정상 {counts['정상']}건   |   오류 {counts['오류']}건   |   "
            f"확인 필요 {counts['확인 필요']}건   |   일반접수 제외 {self.excluded_general}건"
        )
        summary.setObjectName("summary")
        lay.addWidget(summary)

        tabs = QTabWidget()
        lay.addWidget(tabs, 1)
        review_rows = [r for r in self.rows if r.status != "정상"]
        tabs.addTab(self._make_tab(review_rows, full=False), "확인 필요")
        tabs.addTab(self._make_tab(self.rows, full=True), "전체 비교")

        actions = QHBoxLayout()
        actions.addStretch()
        export = QPushButton("엑셀로 저장")
        export.clicked.connect(lambda: self.export(review_rows))
        actions.addWidget(export)
        rerun = QPushButton("재검사")
        rerun.setObjectName("primary")
        rerun.clicked.connect(lambda: self.rerun(win))
        actions.addWidget(rerun)
        lay.addLayout(actions)

        win.show()
        self.result_window = win

    def _set_status_item(self, table, row_index, status):
        item = QTableWidgetItem(status)
        if status == "오류":
            item.setBackground(Qt.GlobalColor.red)
            item.setForeground(Qt.GlobalColor.white)
        elif status == "확인 필요":
            item.setBackground(Qt.GlobalColor.yellow)
        table.setItem(row_index, 0, item)

    @staticmethod
    def _certificate_value(rec):
        if not rec or not rec.certificate_no:
            return "없음"
        return rec.certificate_no

    def _fill_review(self, table, rows):
        headers = [
            "상태",
            "접수번호",
            "CSI 성적서번호",
            "관리프로그램 성적서번호",
            "접수대장 성적서번호",
            "오류항목",
        ]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for rr, row in enumerate(rows):
            vals = [
                row.status,
                row.receipt_no,
                self._certificate_value(row.csi),
                self._certificate_value(row.management),
                self._certificate_value(row.register),
                " · ".join(row.error_fields),
            ]
            self._set_status_item(table, rr, row.status)
            for c, v in enumerate(vals[1:], start=1):
                table.setItem(rr, c, QTableWidgetItem(v))

        table.setColumnWidth(0, 72)
        table.setColumnWidth(1, 145)
        table.setColumnWidth(2, 190)
        table.setColumnWidth(3, 205)
        table.setColumnWidth(4, 195)
        table.setColumnWidth(5, 360)

    def _fill_all(self, table, rows):
        headers = ["상태", "접수번호", "공사명", "업체", "발급일", "성적서번호"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for rr, row in enumerate(rows):
            base = row.csi or row.management or row.register
            vals = [
                row.status,
                row.receipt_no,
                base.project_name if base else "",
                base.company_name if base else "",
                row.issue_date_summary,
                row.certificate_summary,
            ]
            self._set_status_item(table, rr, row.status)
            for c, v in enumerate(vals[1:], start=1):
                table.setItem(rr, c, QTableWidgetItem(v))
        table.setColumnWidth(0, 72)
        table.setColumnWidth(1, 145)
        table.setColumnWidth(2, 380)
        table.setColumnWidth(3, 250)
        table.setColumnWidth(4, 180)
        table.setColumnWidth(5, 240)

    def _show_detail(self, detail, rows, row_index):
        if row_index < 0 or row_index >= len(rows):
            detail.clear()
            return
        row = rows[row_index]

        def v(rec, field):
            if not rec:
                return "—"
            value = getattr(rec, field)
            if value is None:
                return "—"
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value) or "—"

        revision = bool(row.csi and is_revised(row.csi.certificate_no))
        register_date = "revised_issue_date" if revision else "issue_date"
        register_date_label = "수정발급일자" if revision else "발급일자"
        html = f"""
        <b>{row.receipt_no}</b> &nbsp; <span>{row.status}</span><br><br>
        <table cellspacing='0' cellpadding='7' width='100%'>
          <tr><th align='left'>항목</th><th align='left'>CSI 원본</th><th align='left'>관리프로그램</th><th align='left'>접수대장</th></tr>
          <tr><td>성적서번호</td><td>{v(row.csi,'certificate_no')}</td><td>{v(row.management,'certificate_no')}</td><td>{v(row.register,'certificate_no')}</td></tr>
          <tr><td>발급일자</td><td>{v(row.csi,'issue_date')}</td><td>{v(row.management,'issue_date')}</td><td>{v(row.register,register_date)} ({register_date_label})</td></tr>
          <tr><td>공사명</td><td>{v(row.csi,'project_name')}</td><td>{v(row.management,'project_name')}</td><td>{v(row.register,'project_name')}</td></tr>
          <tr><td>업체</td><td>{v(row.csi,'company_name')}</td><td>{v(row.management,'company_name')}</td><td>{v(row.register,'company_name')}</td></tr>
          <tr><td>시료명</td><td>{v(row.csi,'sample_name')}</td><td>{v(row.management,'sample_name')}</td><td>{v(row.register,'sample_name')}</td></tr>
        </table>
        <br><b>판정 사유</b>: {' / '.join(row.reasons) if row.reasons else '없음'}
        """
        detail.setHtml(html)

    def rerun(self, result_window):
        candidate = newest_management_file(self.settings["last_download_dir"])
        if (
            candidate and self.management_path and candidate != self.management_path
            and candidate.stat().st_mtime > self.management_path.stat().st_mtime
        ):
            ans = QMessageBox.question(
                self,
                "새 발행리스트 발견",
                f"더 최신 발행리스트가 있습니다.\n\n{candidate.name}\n\n이 파일로 재검사할까요?",
            )
            if ans == QMessageBox.Yes:
                self.management_path = candidate
        self.register_path = find_register(self.settings["register_root"]) or self.register_path
        result_window.close()
        self._refresh_status()
        self.run_check()

    def export(self, rows):
        p, _ = QFileDialog.getSaveFileName(
            self,
            "결과 저장",
            str(Path.home() / "Downloads" / "성적서_발급검증_결과.xlsx"),
            "Excel (*.xlsx)",
        )
        if not p:
            return
        export_results(p, rows, include_all=True)
        QMessageBox.information(self, "저장 완료", p)

    def update_check(self):
        try:
            available, latest, url = check_update()
            if available:
                if QMessageBox.question(
                    self,
                    "업데이트",
                    f"새 버전 v{latest}이 있습니다.\nGitHub Release 페이지를 열까요?",
                ) == QMessageBox.Yes:
                    webbrowser.open(url)
            else:
                QMessageBox.information(self, "업데이트", f"현재 v{__version__}이 최신 버전입니다.")
        except Exception:
            QMessageBox.information(
                self,
                "업데이트 확인",
                "현재 저장소가 비공개이거나 네트워크에 연결할 수 없어 최신 버전을 확인하지 못했습니다.",
            )


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget { font-family: 'Segoe UI', 'Malgun Gothic'; font-size: 10pt; background:#F4F6F8; color:#202124; }
        QLabel#title { font-size:22pt; font-weight:700; }
        QLabel#muted { color:#6B7280; }
        QLabel#progressLabel { color:#475569; padding-left:2px; }
        QFrame#dropZone { background:white; border:2px dashed #B8C0CC; border-radius:14px; }
        QLabel#dropTitle { font-size:14pt; font-weight:600; background:transparent; }
        QLabel#statusCard, QLabel#summary { background:white; border:1px solid #DFE3E8; border-radius:10px; padding:12px; }
        QTextBrowser#detail { background:white; border:1px solid #DFE3E8; border-radius:8px; padding:8px; }
        QProgressBar { background:white; border:1px solid #D5DBE3; border-radius:5px; height:8px; }
        QProgressBar::chunk { background:#2563EB; border-radius:4px; }
        QPushButton { background:white; border:1px solid #CCD3DB; border-radius:8px; padding:8px 14px; }
        QPushButton:hover { background:#EEF2F6; }
        QPushButton#primary { background:#2563EB; color:white; border:none; font-weight:600; }
        QPushButton#primary:disabled { background:#A8B6C8; }
        QTabWidget::pane { background:white; border:1px solid #DFE3E8; }
        QTableWidget { background:white; gridline-color:#E5E7EB; selection-background-color:#DCEAFE; selection-color:#111827; outline:0; }
        QHeaderView::section { background:#EEF2F6; padding:7px; border:none; border-right:1px solid #DDE2E7; font-weight:600; }
        QSplitter::handle { background:#E2E8F0; height:5px; }

        QScrollBar:vertical {
            background:#F5F7FA;
            width:12px;
            margin:2px;
            border:none;
            border-radius:6px;
        }
        QScrollBar::handle:vertical {
            background:#B8C2CF;
            min-height:34px;
            border-radius:5px;
        }
        QScrollBar::handle:vertical:hover { background:#94A3B8; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height:0px;
            border:none;
            background:transparent;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }

        QScrollBar:horizontal {
            background:#F5F7FA;
            height:12px;
            margin:2px;
            border:none;
            border-radius:6px;
        }
        QScrollBar::handle:horizontal {
            background:#B8C2CF;
            min-width:34px;
            border-radius:5px;
        }
        QScrollBar::handle:horizontal:hover { background:#94A3B8; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width:0px;
            border:none;
            background:transparent;
        }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }
    """)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

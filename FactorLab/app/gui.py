# -*- coding: utf-8 -*-
"""Factor Reproduction Studio — desktop GUI (PySide6), clean unified version.

Matches this project's scanner/evaluator/executor exactly. Real factors run via
the Project root + Module path fields on the Backtest page (same as CLI's
--project-root / --module-path). Heavy work runs in a worker thread.
"""
from __future__ import annotations
import os
import sys
import traceback
import pandas as pd

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QStackedWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QSpinBox,
    QHeaderView, QMessageBox
)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core import (scanner, dependency, translator, static_check, executor,
                  data_doctor, evaluator, report)
from llm import client

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
OUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CLEAN_PANEL = os.path.join(DATA_DIR, "clean_panel.parquet")

QSS = """
QMainWindow, QWidget { background:#f5f5f7; color:#1d1d1f;
  font-family:-apple-system,'Segoe UI','PingFang SC',sans-serif; font-size:14px; }
#sidebar { background:#ececef; border:none; outline:none; }
#sidebar::item { padding:11px 18px; border-radius:8px; margin:2px 8px; }
#sidebar::item:selected { background:#0071e3; color:white; }
#title { font-size:24px; font-weight:700; }
QPushButton { background:#0071e3; color:white; border:none; border-radius:980px;
  padding:9px 18px; font-weight:500; }
QPushButton:hover { background:#0058b8; }
QPushButton#ghost { background:#e8e8ed; color:#1d1d1f; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {
  background:white; border:1px solid #d2d2d7; border-radius:9px; padding:7px 10px; }
QPlainTextEdit, QTextEdit { font-family:'SF Mono',Menlo,Consolas,monospace; font-size:13px; }
#drop { background:white; border:2px dashed #c7c7cc; border-radius:14px;
  padding:26px; color:#86868b; }
QTableWidget { background:white; border:1px solid #e3e3e6; border-radius:10px; gridline-color:#eee; }
QHeaderView::section { background:#f5f5f7; border:none; padding:8px; color:#86868b; }
"""


class DropLabel(QLabel):
    dropped = Signal(list)

    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("drop")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setWordWrap(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.dropped.emit([u.toLocalFile() for u in e.mimeData().urls()])


class Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


class Studio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factor Reproduction Studio")
        self.resize(1180, 800)
        self.state = {"index": {}, "rows": [], "factor": None, "rec": None,
                      "df": None, "deps": [], "helper_src": "", "ref": "",
                      "tr": {}, "static": "", "report_path": None}
        self._thread = None
        self._worker = None

        root = QWidget(); self.setCentralWidget(root)
        lay = QHBoxLayout(root); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        self.nav = QListWidget(); self.nav.setObjectName("sidebar"); self.nav.setFixedWidth(210)
        for name in ["Home", "Import files", "Data", "Factor scanner",
                     "Translation", "Backtest & report", "API settings"]:
            self.nav.addItem(QListWidgetItem(name))
        self.nav.currentRowChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        lay.addWidget(self.nav)

        self.stack = QStackedWidget(); lay.addWidget(self.stack, 1)
        for page in [self._home(), self._import(), self._data(), self._scanner(),
                     self._translate(), self._backtest(), self._settings()]:
            self.stack.addWidget(page)
        self.nav.setCurrentRow(0)
        self.setStyleSheet(QSS)

    def _page(self, title):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(34, 30, 34, 30); v.setSpacing(12)
        t = QLabel(title); t.setObjectName("title"); v.addWidget(t)
        return w, v

    def _home(self):
        w, v = self._page("Factor Reproduction Studio")
        v.addWidget(QLabel(
            "1.  API settings 填 DeepSeek key\n"
            "2.  Import files 拖入因子库、算子文件、数据文件\n"
            "3.  Data 转换成干净面板(自动清洗极端值)\n"
            "4.  Factor scanner 扫描并选一个因子\n"
            "5.  Translation 用 AI 翻译、看代码、静态检查\n"
            "6.  Backtest & report 填项目根目录/模块路径(真实因子需要),Run 出报告"))
        v.addStretch()
        self.lblProv = QLabel(); self._refresh_prov(); v.addWidget(self.lblProv)
        return w

    def _import(self):
        w, v = self._page("Import files")
        self.dropFactors = DropLabel("Drop factor library .py or folder here")
        self.dropHelpers = DropLabel("Drop operator/helper files or folder here")
        self.dropData = DropLabel("Drop data file (.csv / .parquet / .xlsx) here")
        self.dropFactors.dropped.connect(lambda p: self._set_path("factors", p))
        self.dropHelpers.dropped.connect(lambda p: self._set_path("helpers", p))
        self.dropData.dropped.connect(lambda p: self._set_data(p[0]))
        for d in (self.dropFactors, self.dropHelpers, self.dropData):
            v.addWidget(d)
        v.addStretch()
        return w

    def _data(self):
        w, v = self._page("Data")
        self.dataInfo = QLabel("No data imported yet."); v.addWidget(self.dataInfo)
        self.dataPreview = QTableWidget(); v.addWidget(self.dataPreview, 1)
        v.addWidget(QLabel("Column mapping (your column → standard)"))
        self.mapTable = QTableWidget(0, 2)
        self.mapTable.setHorizontalHeaderLabels(["Your column", "Standard column"])
        self.mapTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self.mapTable)
        b = QPushButton("Convert and save clean data (auto-clean extremes)")
        b.clicked.connect(self._convert_data); v.addWidget(b, 0, Qt.AlignLeft)
        return w

    def _scanner(self):
        w, v = self._page("Factor scanner")
        b = QPushButton("Scan factor library"); b.clicked.connect(self._scan)
        v.addWidget(b, 0, Qt.AlignLeft)
        self.scanStatus = QLabel(""); v.addWidget(self.scanStatus)
        self.factorTable = QTableWidget(0, 5)
        self.factorTable.setHorizontalHeaderLabels(["Function", "File", "Lines", "Fields", "Helpers"])
        self.factorTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.factorTable.cellClicked.connect(self._pick_factor)
        v.addWidget(self.factorTable, 1)
        v.addWidget(QLabel("Dependency tree"))
        self.depTree = QPlainTextEdit(); self.depTree.setReadOnly(True); self.depTree.setFixedHeight(110)
        v.addWidget(self.depTree)
        return w

    def _translate(self):
        w, v = self._page("Translation")
        self.trFactor = QLabel("Select a function in the scanner first."); v.addWidget(self.trFactor)
        row = QHBoxLayout()
        self.btnTr = QPushButton("Translate with AI"); self.btnTr.clicked.connect(self._do_translate)
        self.btnChk = QPushButton("Run static check"); self.btnChk.setObjectName("ghost")
        self.btnChk.clicked.connect(self._do_check)
        row.addWidget(self.btnTr); row.addWidget(self.btnChk); row.addStretch(); v.addLayout(row)
        v.addWidget(QLabel("AI logic summary"))
        self.trLogic = QTextEdit(); self.trLogic.setReadOnly(True); self.trLogic.setFixedHeight(80)
        v.addWidget(self.trLogic)
        v.addWidget(QLabel("Translated compute_factor(df) — editable"))
        self.codeEdit = QPlainTextEdit(); v.addWidget(self.codeEdit, 1)
        self.chkLabel = QLabel(""); v.addWidget(self.chkLabel)
        return w

    def _backtest(self):
        w, v = self._page("Backtest & report")
        row = QHBoxLayout()
        row.addWidget(QLabel("Holding (days)"))
        self.holdSpin = QSpinBox(); self.holdSpin.setRange(1, 120); self.holdSpin.setValue(5)
        row.addWidget(self.holdSpin)
        self.btnRun = QPushButton("Run backtest & build report"); self.btnRun.clicked.connect(self._do_backtest)
        row.addWidget(self.btnRun); row.addStretch(); v.addLayout(row)

        v.addWidget(QLabel("Project root (真实因子需要;简单单文件因子留空)"))
        self.projectRootEdit = QLineEdit()
        self.projectRootEdit.setPlaceholderText(r"C:\Users\...\agentmatrix-research-main")
        v.addWidget(self.projectRootEdit)
        v.addWidget(QLabel("Module path (因子所在真实模块;简单单文件因子留空)"))
        self.modulePathEdit = QLineEdit()
        self.modulePathEdit.setPlaceholderText("research_core.factor_lab.libraries.gtja191.factors")
        v.addWidget(self.modulePathEdit)

        self.btResult = QTextEdit(); self.btResult.setReadOnly(True); v.addWidget(self.btResult, 1)
        row2 = QHBoxLayout()
        self.btnOpen = QPushButton("Open HTML report"); self.btnOpen.setObjectName("ghost")
        self.btnOpen.clicked.connect(self._open_report)
        self.btnFolder = QPushButton("Open output folder"); self.btnFolder.setObjectName("ghost")
        self.btnFolder.clicked.connect(lambda: self._open(OUT_DIR))
        row2.addWidget(self.btnOpen); row2.addWidget(self.btnFolder); row2.addStretch(); v.addLayout(row2)
        return w

    def _settings(self):
        w, v = self._page("API settings")
        cfg = client.load_config(); self.cfgFields = {}
        def field(label, key, ph=""):
            v.addWidget(QLabel(label)); e = QLineEdit(cfg.get(key, "")); e.setPlaceholderText(ph)
            if key.endswith("api_key"):
                e.setEchoMode(QLineEdit.Password)
            self.cfgFields[key] = e; v.addWidget(e)
        field("DeepSeek API key", "deepseek_api_key", "leave blank if unused")
        field("DeepSeek base URL", "deepseek_base_url")
        field("DeepSeek model", "deepseek_model")
        field("OpenAI API key", "openai_api_key", "optional")
        field("OpenAI model", "openai_model")
        field("Anthropic API key", "anthropic_api_key", "optional")
        field("Anthropic model", "anthropic_model")
        row = QHBoxLayout()
        bSave = QPushButton("Save settings"); bSave.clicked.connect(self._save_settings)
        bTest = QPushButton("Test DeepSeek"); bTest.setObjectName("ghost")
        bTest.clicked.connect(lambda: self._test("deepseek"))
        row.addWidget(bSave); row.addWidget(bTest); row.addStretch(); v.addLayout(row)
        self.cfgMsg = QLabel(""); v.addWidget(self.cfgMsg); v.addStretch()
        return w

    # ---- actions ---- #
    def _refresh_prov(self):
        provs = client.available()
        self.lblProv.setText("AI providers ready: " + (", ".join(provs) if provs
                             else "none — enter an API key in API settings"))

    def _set_path(self, kind, paths):
        self.state[kind + "_paths"] = paths
        lbl = self.dropFactors if kind == "factors" else self.dropHelpers
        lbl.setText(f"{kind} loaded:\n" + "\n".join(paths))

    def _set_data(self, path):
        try:
            raw = data_doctor.load_raw_data(path)
        except Exception as e:
            QMessageBox.warning(self, "Data", str(e)); return
        self.state["raw_data"] = raw; self.state["data_path"] = path
        self.dataInfo.setText(f"Imported {path}\n{raw.shape[0]} rows, columns: "
                              + ", ".join(map(str, raw.columns)))
        self._preview(raw)
        raw_to_std = data_doctor.suggest_mapping(raw)
        self.mapTable.setRowCount(len(raw.columns))
        for i, c in enumerate(raw.columns):
            self.mapTable.setItem(i, 0, QTableWidgetItem(str(c)))
            self.mapTable.setItem(i, 1, QTableWidgetItem(raw_to_std.get(c, "")))
        self.nav.setCurrentRow(2)

    def _preview(self, df):
        head = df.head(20)
        self.dataPreview.setColumnCount(len(head.columns)); self.dataPreview.setRowCount(len(head))
        self.dataPreview.setHorizontalHeaderLabels([str(c) for c in head.columns])
        for i in range(len(head)):
            for j in range(len(head.columns)):
                self.dataPreview.setItem(i, j, QTableWidgetItem(str(head.iloc[i, j])))

    def _convert_data(self):
        path = self.state.get("data_path")
        if not path:
            QMessageBox.warning(self, "Data", "Import a data file first."); return
        mapping = {}
        for i in range(self.mapTable.rowCount()):
            r, s = self.mapTable.item(i, 0), self.mapTable.item(i, 1)
            if r and s and s.text().strip():
                mapping[s.text().strip()] = r.text().strip()
        try:
            df, summary = data_doctor.standardize_data(path, output_path=CLEAN_PANEL,
                                                       column_mapping=mapping, hold_days_check=5)
            self.state["df"] = df
            QMessageBox.information(self, "Data",
                f"Clean panel saved.\nRows: {df.shape[0]}  Codes: {df['code'].nunique()}\n"
                f"Extreme rows removed: {summary['extreme_rows_removed']}\n{CLEAN_PANEL}")
        except Exception as e:
            QMessageBox.warning(self, "Data", str(e))

    def _scan(self):
        fpaths = self.state.get("factors_paths", [])
        paths = fpaths + self.state.get("helpers_paths", [])
        if not paths:
            QMessageBox.warning(self, "Scan", "Import a factor library first."); return
        res = scanner.scan_paths(paths)
        self.state["index"] = res["index"]
        froots = [os.path.normcase(os.path.abspath(p)) for p in fpaths]

        def in_factor(fp):
            f = os.path.normcase(os.path.abspath(fp))
            for r in froots:
                if os.path.isfile(r) and f == r:
                    return True
                if os.path.isdir(r):
                    try:
                        if os.path.commonpath([f, r]) == r:
                            return True
                    except ValueError:
                        pass
            return False

        rows = [r for r in res["flat"] if in_factor(r["file"])] or res["flat"]
        rows.sort(key=lambda x: (x["file"], x["start_line"]))
        self.state["rows"] = rows
        self.factorTable.setRowCount(len(rows))
        for i, r in enumerate(rows):
            deps, _ = dependency.trace(r["name"], self.state["index"])
            cells = [r.get("unique_name", r["name"]), os.path.basename(r["file"]),
                     f"{r['start_line']}-{r['end_line']}", ", ".join(map(str, r["fields"][:6])),
                     ", ".join(deps)]
            for j, c in enumerate(cells):
                self.factorTable.setItem(i, j, QTableWidgetItem(str(c)))
        self.scanStatus.setText(f"Found {len(rows)} candidate functions.")

    def _pick_factor(self, row, _col):
        rows = self.state.get("rows", [])
        if row < 0 or row >= len(rows):
            return
        rec = rows[row]; idx = self.state["index"]
        deps, edges = dependency.trace(rec["name"], idx)
        self.state.update({"factor": rec.get("unique_name", rec["name"]), "rec": rec,
                           "deps": deps, "helper_src": dependency.helper_sources(idx, deps),
                           "ref": dependency.reference_text(rec["name"], idx, deps)})
        self.depTree.setPlainText(dependency.ascii_tree(rec["name"], edges))
        self.trFactor.setText(f"Function: {self.state['factor']}   "
                              f"({os.path.basename(rec['file'])})   "
                              f"helpers: {', '.join(deps) or 'none'}")
        self.codeEdit.setPlainText("")

    def _do_translate(self):
        if not self.state.get("rec"):
            QMessageBox.warning(self, "Translate", "Pick a function first."); return
        if not client.available():
            QMessageBox.warning(self, "Translate", "Enter an API key in Settings."); return
        rec = self.state["rec"]; name = self.state["factor"]
        self.btnTr.setText("Translating…"); self.btnTr.setEnabled(False)
        def job():
            return translator.translate(name, rec["source"], self.state["ref"])
        self._run_async(job, self._after_translate)

    def _after_translate(self, tr):
        self.btnTr.setText("Translate with AI"); self.btnTr.setEnabled(True)
        if tr.get("sentinel"):
            self.trLogic.setText("AI returned: " + tr["sentinel"]); return
        self.state["tr"] = tr
        self.trLogic.setText(tr.get("factor_logic", ""))
        self.codeEdit.setPlainText(tr.get("final_code", ""))
        self._do_check()

    def _do_check(self):
        code = self.codeEdit.toPlainText()
        if not code.strip():
            return
        rec = self.state.get("rec") or {}
        chk = static_check.check(code, rec.get("source", ""), set(self.state["deps"]))
        self.state["static"] = chk["status"]
        msg = "Static check: " + chk["status"]
        if chk.get("issues"):
            msg += "  —  " + "; ".join(chk["issues"])
        self.chkLabel.setText(msg)

    def _do_backtest(self):
        df = self.state.get("df")
        if df is None and os.path.exists(CLEAN_PANEL):
            df = pd.read_parquet(CLEAN_PANEL)
            df["date"] = pd.to_datetime(df["date"]); df["code"] = df["code"].astype(str)
            df = df.sort_values(["code", "date"]).reset_index(drop=True); self.state["df"] = df
        if df is None:
            QMessageBox.warning(self, "Backtest", "Convert/import data first (Data page)."); return
        code = self.codeEdit.toPlainText().strip()
        if not code:
            QMessageBox.warning(self, "Backtest", "No translated code to run."); return
        self._do_check()
        hold = self.holdSpin.value()
        proot = self.projectRootEdit.text().strip()
        mpath = self.modulePathEdit.text().strip()
        self.btnRun.setText("Running…"); self.btnRun.setEnabled(False)
        def job():
            factor = executor.run(code, self.state["helper_src"], df,
                                  project_roots=[proot] if proot else None,
                                  module_path=mpath if mpath else None)
            ev = evaluator.evaluate(df, factor, hold_days=hold)
            path = report.generate(ev, self.state.get("tr", {}), self.state["factor"],
                                   code, self.state.get("static", "n/a"), OUT_DIR)
            return ev, path
        self._run_async(job, self._after_backtest)

    def _after_backtest(self, result):
        self.btnRun.setText("Run backtest & build report"); self.btnRun.setEnabled(True)
        ev, path = result
        self.state["report_path"] = path
        self.btResult.setText(
            f"Coverage {ev['coverage']:.1%}\nIC mean {ev['ic']['mean']:.4f} (t {ev['ic']['t_stat']:.2f})\n"
            f"RankIC {ev['rank_ic']['mean']:.4f}\nICIR {ev['ic']['ir']:.3f}\n"
            f"Long-short {ev['ls_total_return']:.1%}\nMax drawdown {ev['max_drawdown']:.1%}\n"
            f"Evidence: {ev['evidence']}\n\nReport: {path}")

    def _open_report(self):
        p = self.state.get("report_path")
        if p and os.path.exists(p):
            self._open(p)
        else:
            QMessageBox.information(self, "Report", "Run a backtest first.")

    def _open(self, path):
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(path))

    def _save_settings(self):
        cfg = client.load_config()
        for k, e in self.cfgFields.items():
            cfg[k] = e.text().strip()
        client.save_config(cfg); self._refresh_prov()
        self.cfgMsg.setText("Saved to config.local.json")

    def _test(self, provider):
        self._save_settings()
        ok, msg = client.test_key(provider)
        self.cfgMsg.setText(("OK " if ok else "FAIL ") + msg)

    def _fail(self, msg):
        for b, t in [(getattr(self, "btnTr", None), "Translate with AI"),
                     (getattr(self, "btnRun", None), "Run backtest & build report")]:
            if b:
                b.setEnabled(True); b.setText(t)
        QMessageBox.critical(self, "Error", msg)

    def _run_async(self, fn, on_done):
        self._thread = QThread(); self._worker = Worker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(on_done)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._fail)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("-apple-system", 10))
    win = Studio(); win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

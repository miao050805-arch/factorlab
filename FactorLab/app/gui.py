# -*- coding: utf-8 -*-
"""Factor Reproduction Studio — clean, no-AI-translation edition.

What changed vs. the old GUI
----------------------------
* The AI no longer rewrites factor code. Picking a factor *mechanically*
  extracts the real function (renamed to compute_factor) with its body
  preserved byte-for-byte — see core/extractor.py.
* The AI is used ONLY for an optional plain-language explanation, to help a
  human reviewer. It can never change the runnable code.
* Backtest / evaluation / report / data cleaning all reuse your existing
  backend modules unchanged.

Drop-in: replace app/gui.py with this file, and add core/extractor.py.
Run:  python -m app.gui    (or  python app/gui.py)
"""
from __future__ import annotations
import os
import sys
import traceback
import pandas as pd

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QTextOption
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QStackedWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QSpinBox,
    QHeaderView, QMessageBox, QFrame, QSizePolicy
)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core import (scanner, dependency, static_check, executor,
                  data_doctor, evaluator, report, extractor)
from llm import client

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
OUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CLEAN_PANEL = os.path.join(DATA_DIR, "clean_panel.parquet")

ACCENT = "#2563eb"

QSS = f"""
* {{ font-family: -apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; }}
QMainWindow, QWidget {{ background:#f5f6f8; color:#111827; font-size:14px; }}

#sidebar {{ background:#ffffff; border:none; border-right:1px solid #e9ebef; outline:none; }}
#sidebar::item {{ padding:11px 16px; border-radius:10px; margin:3px 12px; color:#4b5563; }}
#sidebar::item:hover {{ background:#f1f3f7; }}
#sidebar::item:selected {{ background:{ACCENT}; color:#ffffff; }}
#brand {{ font-size:16px; font-weight:800; color:#111827; padding:20px 20px 6px 22px; }}
#brandsub {{ font-size:11px; color:#9ca3af; padding:0 22px 14px 22px; }}

#title {{ font-size:23px; font-weight:800; color:#0f172a; }}
#subtitle {{ font-size:13px; color:#6b7280; }}
#section {{ font-size:12px; font-weight:700; color:#6b7280; text-transform:uppercase; letter-spacing:.4px; }}

#card {{ background:#ffffff; border:1px solid #e9ebef; border-radius:14px; }}

QPushButton {{ background:{ACCENT}; color:#fff; border:none; border-radius:10px;
  padding:9px 18px; font-weight:600; }}
QPushButton:hover {{ background:#1d4ed8; }}
QPushButton:disabled {{ background:#a9bdf0; color:#eef2ff; }}
QPushButton#ghost {{ background:#eef1f5; color:#374151; }}
QPushButton#ghost:hover {{ background:#e3e7ee; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {{
  background:#fff; border:1px solid #d8dce3; border-radius:10px; padding:8px 11px;
  selection-background-color:{ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{ border:1px solid {ACCENT}; }}
QPlainTextEdit, QTextEdit {{ font-family:'SF Mono',Menlo,Consolas,'Cascadia Mono',monospace; font-size:13px; }}

#drop {{ background:#fbfcfe; border:2px dashed #cdd3dd; border-radius:14px;
  padding:22px; color:#8a93a3; font-size:13px; }}

QTableWidget {{ background:#fff; border:1px solid #e9ebef; border-radius:12px; gridline-color:#f0f1f4; }}
QTableWidget::item {{ padding:4px 6px; }}
QTableWidget::item:selected {{ background:#e8effe; color:#0f172a; }}
QHeaderView::section {{ background:#f7f8fa; border:none; padding:9px 8px; color:#6b7280; font-weight:600; }}

QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:#cfd4dc; border-radius:5px; min-height:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
"""

PILL = {
    "ok":   "background:#e7f6ec; color:#1a7f37; padding:4px 11px; border-radius:999px; font-weight:600;",
    "warn": "background:#fdf1dc; color:#9a6700; padding:4px 11px; border-radius:999px; font-weight:600;",
    "err":  "background:#fdecec; color:#b42318; padding:4px 11px; border-radius:999px; font-weight:600;",
    "info": "background:#eef1f5; color:#4b5563; padding:4px 11px; border-radius:999px; font-weight:600;",
}


# --------------------------------------------------------------------------- #
class DropLabel(QLabel):
    dropped = Signal(list)

    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("drop")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setWordWrap(True)
        self.setMinimumHeight(96)

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


def card(*widgets, spacing=10, margins=(16, 16, 16, 16)):
    """Wrap widgets in a rounded white card."""
    f = QFrame(); f.setObjectName("card")
    v = QVBoxLayout(f); v.setContentsMargins(*margins); v.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, (QHBoxLayout, QVBoxLayout)):
            v.addLayout(w)
        else:
            v.addWidget(w)
    return f


def section(text):
    l = QLabel(text); l.setObjectName("section"); return l


# --------------------------------------------------------------------------- #
class Studio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factor Reproduction Studio")
        self.resize(1240, 840)
        self.state = {"index": {}, "rows": [], "factor": None, "rec": None,
                      "df": None, "deps": [], "helper_src": "", "extract": {},
                      "summary": "", "static": "", "report_path": None}
        self._thread = None
        self._worker = None

        root = QWidget(); self.setCentralWidget(root)
        lay = QHBoxLayout(root); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # sidebar
        side = QWidget(); side.setObjectName("sidebar"); side.setFixedWidth(228)
        sv = QVBoxLayout(side); sv.setContentsMargins(0, 0, 0, 0); sv.setSpacing(0)
        b = QLabel("Factor Studio"); b.setObjectName("brand"); sv.addWidget(b)
        bs = QLabel("reproduce · review · backtest"); bs.setObjectName("brandsub"); sv.addWidget(bs)
        self.nav = QListWidget(); self.nav.setObjectName("sidebar")
        for name in ["  Home", "  Import files", "  Data", "  Scan & extract",
                     "  Review", "  Backtest & report", "  API settings"]:
            self.nav.addItem(QListWidgetItem(name))
        self.nav.currentRowChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        sv.addWidget(self.nav, 1)
        lay.addWidget(side)

        self.stack = QStackedWidget(); lay.addWidget(self.stack, 1)
        for page in [self._home(), self._import(), self._data(), self._scanner(),
                     self._review(), self._backtest(), self._settings()]:
            self.stack.addWidget(page)
        self.nav.setCurrentRow(0)
        self.setStyleSheet(QSS)

    # ---- page scaffold ---- #
    def _page(self, title, subtitle=""):
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(34, 28, 34, 28); v.setSpacing(14)
        t = QLabel(title); t.setObjectName("title"); v.addWidget(t)
        if subtitle:
            s = QLabel(subtitle); s.setObjectName("subtitle"); v.addWidget(s)
        return w, v

    # ---- Home ---- #
    def _home(self):
        w, v = self._page("Factor Reproduction Studio",
                          "Extract factors as-written. The AI never rewrites your code.")
        steps = QLabel(
            "1.   API settings — (optional) add a key if you want AI explanations.\n"
            "2.   Import files — drop your factor library, your operator/helper files, and a data file.\n"
            "3.   Data — map columns and build a clean panel (auto-cleans extremes).\n"
            "4.   Scan & extract — scan the library, pick a factor; its real code is\n"
            "       extracted automatically (renamed to compute_factor, body unchanged).\n"
            "5.   Review — read the extracted code, optionally get a plain-language\n"
            "       explanation, run a static check, edit if you want.\n"
            "6.   Backtest & report — run and open the HTML report.")
        steps.setStyleSheet("font-size:14px; color:#374151; line-height:160%;")
        note = QLabel("No code is ever generated or altered by a model. "
                      "Extraction is a pure rename; helpers are bundled from your own files.")
        note.setWordWrap(True); note.setStyleSheet("color:#6b7280;")
        v.addWidget(card(steps, note, spacing=14, margins=(22, 20, 22, 20)))
        v.addStretch()
        self.lblProv = QLabel(); self.lblProv.setStyleSheet("color:#6b7280;")
        self._refresh_prov(); v.addWidget(self.lblProv)
        return w

    # ---- Import ---- #
    def _import(self):
        w, v = self._page("Import files",
                          "Factor library = the .py with your alphas. Helpers = your operators / shared functions.")
        self.dropFactors = DropLabel("Drop factor library  .py  or folder here")
        self.dropHelpers = DropLabel("Drop operator / helper files or folder here")
        self.dropData = DropLabel("Drop data file  (.csv / .parquet / .xlsx)  here")
        self.dropFactors.dropped.connect(lambda p: self._set_path("factors", p))
        self.dropHelpers.dropped.connect(lambda p: self._set_path("helpers", p))
        self.dropData.dropped.connect(lambda p: self._set_data(p[0]))
        v.addWidget(card(section("FACTOR LIBRARY"), self.dropFactors))
        v.addWidget(card(section("OPERATORS / HELPERS"), self.dropHelpers))
        v.addWidget(card(section("DATA"), self.dropData))
        v.addStretch()
        return w

    # ---- Data ---- #
    def _data(self):
        w, v = self._page("Data", "Map your columns to the standard schema, then build a clean panel.")
        self.dataInfo = QLabel("No data imported yet."); self.dataInfo.setStyleSheet("color:#6b7280;")
        self.dataPreview = QTableWidget()
        v.addWidget(card(self.dataInfo, self.dataPreview, spacing=10), 1)
        self.mapTable = QTableWidget(0, 2)
        self.mapTable.setHorizontalHeaderLabels(["Your column", "Standard column"])
        self.mapTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        btn = QPushButton("Build clean panel (auto-clean extremes)")
        btn.clicked.connect(self._convert_data)
        row = QHBoxLayout(); row.addWidget(btn); row.addStretch()
        v.addWidget(card(section("COLUMN MAPPING  (your → standard)"), self.mapTable, row))
        return w

    # ---- Scanner ---- #
    def _scanner(self):
        w, v = self._page("Scan & extract", "Pick a factor — its real code is extracted instantly, no AI.")
        top = QHBoxLayout()
        b = QPushButton("Scan factor library"); b.clicked.connect(self._scan)
        self.scanStatus = QLabel(""); self.scanStatus.setStyleSheet("color:#6b7280; margin-left:10px;")
        top.addWidget(b); top.addWidget(self.scanStatus); top.addStretch()
        v.addLayout(top)
        self.factorTable = QTableWidget(0, 5)
        self.factorTable.setHorizontalHeaderLabels(["Function", "File", "Lines", "Fields", "Helpers"])
        hh = self.factorTable.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        self.factorTable.setSelectionBehavior(QTableWidget.SelectRows)
        self.factorTable.cellClicked.connect(self._pick_factor)
        v.addWidget(card(self.factorTable), 1)
        self.depTree = QPlainTextEdit(); self.depTree.setReadOnly(True); self.depTree.setFixedHeight(120)
        v.addWidget(card(section("DEPENDENCY TREE"), self.depTree))
        return w

    # ---- Review ---- #
    def _review(self):
        w, v = self._page("Review", "Read the extracted code. Optionally get a plain-language explanation.")
        self.trFactor = QLabel("Pick a factor in “Scan & extract” first.")
        self.trFactor.setStyleSheet("color:#374151; font-weight:600;")
        self.missingPill = QLabel(""); self.missingPill.setVisible(False)
        hdr = QHBoxLayout(); hdr.addWidget(self.trFactor); hdr.addStretch(); hdr.addWidget(self.missingPill)

        row = QHBoxLayout()
        self.btnExplain = QPushButton("Explain in plain language (AI)")
        self.btnExplain.setObjectName("ghost"); self.btnExplain.clicked.connect(self._do_explain)
        self.btnChk = QPushButton("Run static check"); self.btnChk.setObjectName("ghost")
        self.btnChk.clicked.connect(self._do_check)
        row.addWidget(self.btnExplain); row.addWidget(self.btnChk); row.addStretch()

        self.trLogic = QTextEdit(); self.trLogic.setReadOnly(True); self.trLogic.setFixedHeight(96)
        self.trLogic.setPlaceholderText("Plain-language explanation appears here (optional, AI, read-only).")

        self.codeEdit = QPlainTextEdit()
        self.codeEdit.setWordWrapMode(QTextOption.NoWrap)
        self.chkLabel = QLabel(""); self.chkLabel.setVisible(False)

        v.addWidget(card(hdr, row, spacing=12))
        v.addWidget(card(section("PLAIN-LANGUAGE EXPLANATION"), self.trLogic))
        v.addWidget(card(section("EXTRACTED  compute_factor(df)  — editable"),
                         self.codeEdit, self.chkLabel, spacing=10), 1)
        return w

    # ---- Backtest ---- #
    def _backtest(self):
        w, v = self._page("Backtest & report", "Run the extracted factor and build the HTML report.")
        row = QHBoxLayout()
        lab = QLabel("Holding (days)"); lab.setStyleSheet("color:#374151;")
        self.holdSpin = QSpinBox(); self.holdSpin.setRange(1, 120); self.holdSpin.setValue(5)
        self.holdSpin.setFixedWidth(90)
        self.btnRun = QPushButton("Run backtest & build report"); self.btnRun.clicked.connect(self._do_backtest)
        row.addWidget(lab); row.addWidget(self.holdSpin); row.addSpacing(16)
        row.addWidget(self.btnRun); row.addStretch()

        self.projectRootEdit = QLineEdit()
        self.projectRootEdit.setPlaceholderText(r"C:\Users\...\agentmatrix-research-main   (真实因子需要; 简单单文件因子留空)")
        self.modulePathEdit = QLineEdit()
        self.modulePathEdit.setPlaceholderText("research_core.factor_lab.libraries.gtja191.factors   (留空则用打包好的 helper)")

        v.addWidget(card(row, spacing=10))
        v.addWidget(card(section("PROJECT ROOT  (optional)"), self.projectRootEdit,
                         section("MODULE PATH  (optional)"), self.modulePathEdit))
        self.btResult = QTextEdit(); self.btResult.setReadOnly(True)
        v.addWidget(card(section("RESULT"), self.btResult), 1)
        r2 = QHBoxLayout()
        self.btnOpen = QPushButton("Open HTML report"); self.btnOpen.setObjectName("ghost")
        self.btnOpen.clicked.connect(self._open_report)
        self.btnFolder = QPushButton("Open output folder"); self.btnFolder.setObjectName("ghost")
        self.btnFolder.clicked.connect(lambda: self._open(OUT_DIR))
        r2.addWidget(self.btnOpen); r2.addWidget(self.btnFolder); r2.addStretch()
        v.addLayout(r2)
        return w

    # ---- Settings ---- #
    def _settings(self):
        w, v = self._page("API settings", "Optional — only needed for AI plain-language explanations.")
        cfg = client.load_config(); self.cfgFields = {}
        box = QVBoxLayout(); box.setSpacing(8)

        def field(label, key, ph=""):
            box.addWidget(section(label.upper()))
            e = QLineEdit(cfg.get(key, "")); e.setPlaceholderText(ph)
            if key.endswith("api_key"):
                e.setEchoMode(QLineEdit.Password)
            self.cfgFields[key] = e; box.addWidget(e)

        field("DeepSeek API key", "deepseek_api_key", "leave blank if unused")
        field("DeepSeek base URL", "deepseek_base_url")
        field("DeepSeek model", "deepseek_model")
        field("OpenAI API key", "openai_api_key", "optional")
        field("OpenAI model", "openai_model")
        field("Anthropic API key", "anthropic_api_key", "optional")
        field("Anthropic model", "anthropic_model")
        v.addWidget(card(box), 1)

        row = QHBoxLayout()
        bSave = QPushButton("Save settings"); bSave.clicked.connect(self._save_settings)
        bTest = QPushButton("Test DeepSeek"); bTest.setObjectName("ghost")
        bTest.clicked.connect(lambda: self._test("deepseek"))
        self.cfgMsg = QLabel(""); self.cfgMsg.setStyleSheet("color:#6b7280; margin-left:10px;")
        row.addWidget(bSave); row.addWidget(bTest); row.addWidget(self.cfgMsg); row.addStretch()
        v.addLayout(row)
        return w

    # ================= actions ================= #
    def _refresh_prov(self):
        provs = client.available()
        txt = ("AI providers ready: " + ", ".join(provs)) if provs \
            else "No AI provider configured — extraction & backtest still work fully without it."
        self.lblProv.setText(txt)

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
        self.dataInfo.setText(f"Imported {path}\n{raw.shape[0]} rows · columns: "
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
                     f"{r['start_line']}-{r['end_line']}",
                     ", ".join(map(str, r["fields"][:6])), ", ".join(deps)]
            for j, c in enumerate(cells):
                self.factorTable.setItem(i, j, QTableWidgetItem(str(c)))
        self.scanStatus.setText(f"Found {len(rows)} candidate functions.")

    def _pick_factor(self, row, _col):
        rows = self.state.get("rows", [])
        if row < 0 or row >= len(rows):
            return
        rec = rows[row]; idx = self.state["index"]
        deps, edges = dependency.trace(rec["name"], idx)
        helper_src = dependency.helper_sources(idx, deps)
        ex = extractor.extract(rec, helper_src)
        missing = extractor.unresolved_helpers(rec, idx)
        self.state.update({"factor": rec.get("unique_name", rec["name"]), "rec": rec,
                           "deps": deps, "helper_src": helper_src, "extract": ex,
                           "summary": "", "missing": missing})

        self.depTree.setPlainText(dependency.ascii_tree(rec["name"], edges))
        # populate Review page
        self.trFactor.setText(f"{ex['factor_name']}   ·   {os.path.basename(rec['file'])}   ·   "
                              f"helpers: {', '.join(deps) or 'none'}")
        self.codeEdit.setPlainText(ex["final_code"])
        self.trLogic.setPlainText("")
        self.chkLabel.setVisible(False)
        if missing:
            self.missingPill.setText("⚠ unresolved: " + ", ".join(missing))
            self.missingPill.setStyleSheet(PILL["warn"]); self.missingPill.setVisible(True)
        else:
            self.missingPill.setText("✓ all helpers resolved")
            self.missingPill.setStyleSheet(PILL["ok"]); self.missingPill.setVisible(True)
        self.nav.setCurrentRow(4)   # jump to Review
        self._do_check()

    def _do_explain(self):
        if not self.state.get("rec"):
            QMessageBox.warning(self, "Explain", "Pick a factor first."); return
        if not client.available():
            QMessageBox.information(self, "Explain",
                "No AI provider configured. Add a key in API settings to enable explanations.\n"
                "(Extraction and backtest work without it.)"); return
        rec = self.state["rec"]; helper_src = self.state["helper_src"]
        self.btnExplain.setText("Explaining…"); self.btnExplain.setEnabled(False)

        def job():
            return extractor.summarize(rec, helper_src, client)
        self._run_async(job, self._after_explain)

    def _after_explain(self, text):
        self.btnExplain.setText("Explain in plain language (AI)"); self.btnExplain.setEnabled(True)
        self.state["summary"] = text or ""
        self.trLogic.setPlainText(text or "(empty response)")

    def _do_check(self):
        code = self.codeEdit.toPlainText()
        if not code.strip():
            self.chkLabel.setVisible(False); return
        rec = self.state.get("rec") or {}
        try:
            chk = static_check.check(code, rec.get("source", ""), set(self.state.get("deps", [])))
            status = chk.get("status", "n/a"); issues = chk.get("issues", [])
        except Exception as e:
            status, issues = "error", [str(e)]
        self.state["static"] = status
        style = PILL["ok"] if str(status).lower().startswith(("ok", "pass")) else \
            (PILL["warn"] if issues else PILL["info"])
        msg = "Static check: " + str(status)
        if issues:
            msg += "  —  " + "; ".join(map(str, issues))
        self.chkLabel.setText(msg); self.chkLabel.setStyleSheet(style); self.chkLabel.setVisible(True)

    def _do_backtest(self):
        df = self.state.get("df")
        if df is None and os.path.exists(CLEAN_PANEL):
            df = pd.read_parquet(CLEAN_PANEL)
            df["date"] = pd.to_datetime(df["date"]); df["code"] = df["code"].astype(str)
            df = df.sort_values(["code", "date"]).reset_index(drop=True); self.state["df"] = df
        if df is None:
            QMessageBox.warning(self, "Backtest", "Build/import data first (Data page)."); return
        code = self.codeEdit.toPlainText().strip()
        if not code:
            QMessageBox.warning(self, "Backtest", "No extracted code to run. Pick a factor first."); return
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
            tr = {"factor_logic": self.state.get("summary", ""),
                  "final_code": code,
                  "decomposition": "", "translation_notes": "",
                  "helpers_used": ", ".join(self.state.get("deps", [])),
                  "required_fields": ", ".join((self.state.get("rec") or {}).get("fields", []))}
            path = report.generate(ev, tr, self.state["factor"], code,
                                   self.state.get("static", "n/a"), OUT_DIR)
            return ev, path
        self._run_async(job, self._after_backtest)

    def _after_backtest(self, result):
        self.btnRun.setText("Run backtest & build report"); self.btnRun.setEnabled(True)
        ev, path = result
        self.state["report_path"] = path
        self.btResult.setText(
            f"Coverage {ev['coverage']:.1%}\n"
            f"IC mean {ev['ic']['mean']:.4f}  (t {ev['ic']['t_stat']:.2f})\n"
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
        self.cfgMsg.setText(("OK  " if ok else "FAIL  ") + msg)

    def _fail(self, msg):
        for b, t in [(getattr(self, "btnExplain", None), "Explain in plain language (AI)"),
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

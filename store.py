"""Local document and finding store for the CPQ review viewer."""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FILES = DATA / "files"
DB = DATA / "review.sqlite3"
KINDS = {"scenario", "prd"}
INITIAL_ACTIONS = {
    'Free Trial 기간·수량·상품이 다름': 'modify',
    'CPQ 진입 경로별 최초 설문 순서가 다름': 'modify',
    'SW 기능 카테고리와 레벨 체계가 다름': 'clarify',
    '최초 추천 UI가 Prompt Maker와 대화형 설문으로 다름': 'clarify',
    'My Quotes 예시가 삭제된 상품·상태를 표시': 'modify',
    '견적 CSV Export 동선이 시나리오에 보이지 않음': 'add',
    '수집 이벤트가 삭제된 구매 동선을 참조': 'modify',
    'Home의 개별 기능 선택 문구가 구매 단위와 다름': 'modify',
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    FILES.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS documents (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL CHECK(kind IN ('scenario','prd')),
      source TEXT NOT NULL,
      external_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      title TEXT NOT NULL,
      filename TEXT NOT NULL,
      file_path TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      page_count INTEGER NOT NULL,
      doc_status TEXT,
      imported_at TEXT NOT NULL,
      UNIQUE(kind, external_id, version),
      UNIQUE(kind, sha256)
    );
    CREATE INDEX IF NOT EXISTS idx_documents_identity ON documents(kind, external_id, version);
    CREATE TABLE IF NOT EXISTS pages (
      document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
      page_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      text TEXT NOT NULL,
      digest TEXT NOT NULL,
      PRIMARY KEY(document_id, page_number)
    );
    CREATE TABLE IF NOT EXISTS findings (
      id INTEGER PRIMARY KEY,
      category TEXT NOT NULL CHECK(category IN ('scenario_prd','prd_prd')),
      severity TEXT NOT NULL CHECK(severity IN ('high','medium','low')),
      title TEXT NOT NULL,
      summary TEXT NOT NULL,
      recommendation TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','reviewing','resolved')),
      reviewer_note TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS finding_evidence (
      finding_id INTEGER NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
      document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
      page_number INTEGER NOT NULL,
      excerpt TEXT NOT NULL,
      highlight_terms TEXT NOT NULL DEFAULT '[]',
      highlight_boxes TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY(finding_id, document_id, page_number)
    );
    """)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(finding_evidence)")}
    if "highlight_terms" not in columns:
        db.execute("ALTER TABLE finding_evidence ADD COLUMN highlight_terms TEXT NOT NULL DEFAULT '[]'")
    if "highlight_boxes" not in columns:
        db.execute("ALTER TABLE finding_evidence ADD COLUMN highlight_boxes TEXT NOT NULL DEFAULT '[]'")
    doc_columns = {r['name'] for r in db.execute('PRAGMA table_info(documents)')}
    if 'product' not in doc_columns:
        db.execute("ALTER TABLE documents ADD COLUMN product TEXT NOT NULL DEFAULT ''")
        db.execute("UPDATE documents SET product='CPQ' WHERE external_id='CPQ_SCENARIO' OR external_id IN ('IDRM-13795','IDRM-13995','IDRM-14201','IDRM-14344','IDRM-14453','IDRM-14471','IDRM-14473')")
        db.commit()
    finding_columns = {r['name'] for r in db.execute('PRAGMA table_info(findings)')}
    if 'action_type' not in finding_columns:
        db.execute("ALTER TABLE findings ADD COLUMN action_type TEXT NOT NULL DEFAULT 'clarify' CHECK(action_type IN ('modify','add','clarify'))")
        for title, action in INITIAL_ACTIONS.items():
            db.execute('UPDATE findings SET action_type=? WHERE title=?', (action,title))
        db.commit()
    return db


def clean_title(text: str, page: int) -> str:
    lines = [" ".join(x.split()) for x in text.splitlines() if x.strip()]
    for line in lines[:12]:
        if line.startswith(("Modified", "Deleted")):
            continue
        if re.match(r"^L\s*G\s*B\s*C\s*3\s*\.\s*0\b.*P\s*or\s*tal\s*&\s*CPQ", line, re.I):
            continue
        if line.startswith("[사업부장님 코멘트]"):
            continue
        if len(line) > 7:
            return line[:120]
    return f"페이지 {page}"


def derive_status(first_page: str) -> str | None:
    match = re.search(r"\bStatus:\s*(Accepted|Open|Rejected|Draft|Closed)\b", first_page)
    return match.group(1) if match else None


def import_pdf(
    db: sqlite3.Connection,
    source_path: Path,
    kind: str,
    external_id: str,
    source: str = "upload",
) -> tuple[int, bool]:
    if kind not in KINDS:
        raise ValueError("문서 유형이 올바르지 않습니다.")
    if not external_id.strip():
        raise ValueError("문서 ID가 필요합니다.")
    if source_path.stat().st_size > 120 * 1024 * 1024:
        raise ValueError("PDF는 120MB 이하만 업로드할 수 있습니다.")
    with source_path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError("PDF 파일이 아닙니다.")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    existing = db.execute("SELECT id FROM documents WHERE kind=? AND sha256=?", (kind, digest)).fetchone()
    if existing:
        return existing["id"], False

    reader = PdfReader(str(source_path))
    pages = []
    for page_number, page in enumerate(reader.pages, 1):
        raw = page.extract_text() or ""
        normalized = " ".join(raw.split())
        pages.append((page_number, clean_title(raw, page_number), raw,
                      hashlib.sha256("".join(normalized.split()).encode()).hexdigest()))
    if not pages:
        raise ValueError("페이지가 없는 PDF입니다.")
    version = db.execute(
        "SELECT COALESCE(MAX(version), 0)+1 AS n FROM documents WHERE kind=? AND external_id=?",
        (kind, external_id),
    ).fetchone()["n"]
    target = FILES / f"{kind}-{re.sub(r'[^A-Za-z0-9_-]', '_', external_id)[:60]}-v{version}-{digest[:12]}.pdf"
    shutil.copyfile(source_path, target)
    title = (pages[0][2].splitlines()[0] or external_id).strip()[:180]
    with db:
        cur = db.execute(
            """INSERT INTO documents
            (kind, source, external_id, version, title, filename, file_path, sha256,
             page_count, doc_status, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kind, source, external_id, version, title, source_path.name, str(target), digest,
             len(pages), derive_status(pages[0][2]) if kind == "prd" else None, now()),
        )
        db.executemany(
            "INSERT INTO pages(document_id,page_number,title,text,digest) VALUES (?,?,?,?,?)",
            ((cur.lastrowid, *row) for row in pages),
        )
    return cur.lastrowid, True


def document_rows(db: sqlite3.Connection, kind: str | None = None) -> list[dict]:
    if kind in KINDS:
        rows = db.execute("SELECT * FROM documents WHERE kind=? ORDER BY external_id,version DESC", (kind,))
    else:
        rows = db.execute("SELECT * FROM documents ORDER BY kind,external_id,version DESC")
    return [dict(row) for row in rows]


def public_document(row: dict) -> dict:
    return {key: row[key] for key in
            ("id", "kind", "source", "external_id", "version", "title", "filename",
             "sha256", "page_count", "doc_status", "imported_at", "product")}


def finding_rows(db: sqlite3.Connection) -> list[dict]:
    findings = []
    for row in db.execute("SELECT * FROM findings ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id"):
        finding = dict(row)
        evidence = db.execute("""SELECT e.page_number,e.excerpt,e.highlight_boxes,d.id AS document_id,d.kind,d.external_id,
            d.version,d.filename,d.doc_status FROM finding_evidence e
            JOIN documents d ON d.id=e.document_id WHERE e.finding_id=?
            ORDER BY CASE d.kind WHEN 'scenario' THEN 0 ELSE 1 END,d.external_id""", (row["id"],))
        import json
        finding["evidence"] = [{**dict(x), "highlight_boxes": json.loads(x["highlight_boxes"])} for x in evidence]
        findings.append(finding)
    return findings

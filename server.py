#!/usr/bin/env python3
"""Loopback-only CPQ scenario and PRD review server."""

from __future__ import annotations

import review_service
import workspace_service as ws
import difflib
import json
import os
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from store import ROOT, connect, document_rows, finding_rows, import_pdf, public_document, now


PORT = int(os.environ.get("CPQ_REVIEW_PORT", "8766"))
RENDER_LOCK = Lock()
RENDER_CACHE: dict[tuple[int, int], bytes] = {}


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "CPQReview/0.1"

    def respond(self, content: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Evidence rectangles use inline coordinates on trusted, server-generated spans.
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(content)

    def respond_json(self, value: object, status: int = 200) -> None:
        self.respond(json_bytes(value), "application/json; charset=utf-8", status)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("요청이 너무 큽니다.")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in {"/", "/index.html", "/app.css", "/app.js", "/workspace.js"}:
                name = "index.html" if path == "/" else path.lstrip("/")
                mime = {"index.html": "text/html; charset=utf-8", "app.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "workspace.js": "text/javascript; charset=utf-8"}[name]
                self.respond((ROOT / "static" / name).read_bytes(), mime)
                return
            with connect() as db:
                if path.startswith('/api/workspace'):
                    ws.setup(db)
                    q = parse_qs(parsed.query)
                    if path == '/api/workspace': self.respond_json(ws.overview(db))
                    elif path == '/api/workspace/notes': self.respond_json(ws.notes(db,q.get('q',[''])[0],q.get('product',[''])[0]))
                    elif path.startswith('/api/workspace/notes/'): self.respond_json(ws.get_note(db,path.rsplit('/',1)[1]))
                    elif path == '/api/workspace/history': self.respond_json(ws.history(db,int(q.get('offset',['0'])[0])))
                    elif path.startswith('/api/workspace/operations/'): self.respond_json(ws.get_operation(db,path.rsplit('/',1)[1]))
                    else: self.respond_json({'error':'찾을 수 없습니다.'},404)
                    return
                if path == "/api/dashboard":
                    documents = [public_document(x) for x in document_rows(db)]
                    findings = finding_rows(db)
                    self.respond_json({"documents": documents, "findings": findings, "run": review_service.status(db), "runs": review_service.runs(db)})
                    return
                if path == "/api/documents":
                    kind = parse_qs(parsed.query).get("kind", [None])[0]
                    self.respond_json([public_document(x) for x in document_rows(db, kind)])
                    return
                if path == "/api/annotations":
                    review_service.setup(db)
                    finding_id = int(parse_qs(parsed.query).get("finding_id", ["0"])[0])
                    self.respond_json([dict(r) for r in db.execute("SELECT * FROM annotations WHERE finding_id=? ORDER BY id", (finding_id,))])
                    return
                if path == "/api/findings":
                    self.respond_json(finding_rows(db))
                    return
                parts = path.strip("/").split("/")
                if len(parts) >= 3 and parts[:2] == ["api", "documents"]:
                    doc_id = int(parts[2])
                    row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
                    if not row:
                        self.respond_json({"error": "문서를 찾을 수 없습니다."}, 404)
                        return
                    if len(parts) == 3:
                        pages = db.execute("SELECT page_number,title FROM pages WHERE document_id=? ORDER BY page_number", (doc_id,))
                        self.respond_json({**public_document(dict(row)), "pages": [dict(x) for x in pages]})
                        return
                    if len(parts) == 4 and parts[3] == "changes":
                        previous = db.execute("""SELECT id,version FROM documents WHERE kind=? AND external_id=?
                            AND version<? ORDER BY version DESC LIMIT 1""", (row["kind"], row["external_id"], row["version"])).fetchone()
                        if not previous:
                            self.respond_json({"previous_version": None, "changes": []})
                            return
                        old = list(db.execute("SELECT page_number,digest,title FROM pages WHERE document_id=? ORDER BY page_number", (previous["id"],)))
                        new = list(db.execute("SELECT page_number,digest,title FROM pages WHERE document_id=? ORDER BY page_number", (doc_id,)))
                        matcher = difflib.SequenceMatcher(None, [x["digest"] for x in old], [x["digest"] for x in new], autojunk=False)
                        changes = []
                        for op, i1, i2, j1, j2 in matcher.get_opcodes():
                            if op == "equal":
                                continue
                            for offset in range(max(i2-i1, j2-j1)):
                                a = old[i1+offset] if i1+offset < i2 else None
                                b = new[j1+offset] if j1+offset < j2 else None
                                changes.append({"status": "added" if a is None else "removed" if b is None else "changed",
                                                "old_page": a["page_number"] if a else None,
                                                "new_page": b["page_number"] if b else None,
                                                "title": b["title"] if b else a["title"]})
                        self.respond_json({"previous_version": previous["version"], "changes": changes})
                        return
                    if len(parts) == 5 and parts[3] == "pages":
                        page_number = int(parts[4])
                        page = db.execute("SELECT * FROM pages WHERE document_id=? AND page_number=?", (doc_id, page_number)).fetchone()
                        if not page:
                            self.respond_json({"error": "페이지를 찾을 수 없습니다."}, 404)
                            return
                        self.respond_json(dict(page))
                        return
                    if len(parts) == 6 and parts[3] == "pages" and parts[5] == "image":
                        page_number = int(parts[4])
                        if not 1 <= page_number <= row["page_count"]:
                            raise ValueError("페이지 번호가 올바르지 않습니다.")
                        self.respond(render_page(row, page_number), "image/jpeg")
                        return
            self.respond_json({"error": "찾을 수 없습니다."}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, 500)

    def same_origin(self) -> bool:
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}:
            self.respond_json({'error': '이 웹앱에서만 변경할 수 있습니다.'}, 403)
            return False
        return True

    def do_POST(self) -> None:
        if not self.same_origin(): return
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith('/api/workspace/'):
                payload = self.read_json()
                actions = {'/api/workspace/baseline':ws.set_baseline, '/api/workspace/prepare':ws.prepare, '/api/workspace/review-note':ws.review_note, '/api/workspace/link':ws.register_link}
                with connect() as db:
                    ws.setup(db)
                    if parsed.path == '/api/workspace/execute': result=ws.execute(db,str(payload.get('id')))
                    elif parsed.path in actions: result=actions[parsed.path](db,payload)
                    else: self.respond_json({'error':'찾을 수 없습니다.'},404); return
                self.respond_json(result)
                return
            if parsed.path == "/api/analyze":
                payload = self.read_json()
                with connect() as db:
                    self.respond_json(review_service.analyze(db, payload))
                return
            if parsed.path == "/api/annotations":
                payload = self.read_json()
                with connect() as db:
                    self.respond_json(review_service.add_annotation(db, payload), 201)
                return
            if parsed.path != "/api/documents":
                self.respond_json({"error": "찾을 수 없습니다."}, 404)
                return
            params = parse_qs(parsed.query)
            kind = params.get("kind", [""])[0]
            external_id = params.get("external_id", [""])[0].strip()
            product = params.get("product", [""])[0]
            if product not in {"", "CPQ", "대시보드", "데이터", "콘텐츠", "디바이스"}:
                raise ValueError("프로덕트가 올바르지 않습니다.")
            filename = Path(params.get("filename", ["upload.pdf"])[0]).name
            if not filename.lower().endswith(".pdf"):
                raise ValueError("PDF만 업로드할 수 있습니다.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 120 * 1024 * 1024:
                raise ValueError("PDF는 120MB 이하만 업로드할 수 있습니다.")
            with tempfile.TemporaryDirectory(prefix="cpq-upload-") as folder:
                temp = Path(folder) / filename
                remaining = length
                with temp.open("wb") as stream:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("업로드가 완료되지 않았습니다.")
                        stream.write(chunk)
                        remaining -= len(chunk)
                with connect() as db:
                    doc_id, created = import_pdf(db, temp, kind, external_id, "upload")
                    if created and product:
                        db.execute("UPDATE documents SET product=? WHERE id=?", (product, doc_id))
                        db.commit()
                self.respond_json({"id": doc_id, "created": created}, 201 if created else 200)
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, 500)

    def do_PATCH(self) -> None:
        if not self.same_origin(): return
        try:
            parts = urlparse(self.path).path.strip("/").split("/")
            if len(parts) != 3 or parts[:2] != ["api", "findings"]:
                self.respond_json({"error": "찾을 수 없습니다."}, 404)
                return
            finding_id = int(parts[2])
            payload = self.read_json()
            if 'action_type' in payload:
                action_type = payload['action_type']
                if action_type not in {'modify', 'add', 'clarify'}:
                    raise ValueError('분류가 올바르지 않습니다.')
                with connect() as db:
                    cur = db.execute('UPDATE findings SET action_type=?,updated_at=? WHERE id=?', (action_type, now(), finding_id))
                    db.commit()
                self.respond_json({'ok': True} if cur.rowcount else {'error': '항목을 찾을 수 없습니다.'}, 200 if cur.rowcount else 404)
                return
            status = payload.get("status")
            note = payload.get("reviewer_note")
            if status not in {"open", "reviewing", "resolved"} or not isinstance(note, str) or len(note) > 5000:
                raise ValueError("검토 상태 또는 메모가 올바르지 않습니다.")
            with connect() as db:
                cur = db.execute("UPDATE findings SET status=?,reviewer_note=?,updated_at=? WHERE id=?",
                                 (status, note, now(), finding_id))
                db.commit()
            if not cur.rowcount:
                self.respond_json({"error": "항목을 찾을 수 없습니다."}, 404)
            else:
                self.respond_json({"ok": True})
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, 500)


def render_page(row, page_number: int) -> bytes:
    key = (row["id"], page_number)
    with RENDER_LOCK:
        if key in RENDER_CACHE:
            return RENDER_CACHE[key]
    executable = shutil.which("pdftoppm")
    if not executable:
        raise RuntimeError("pdftoppm을 찾을 수 없습니다.")
    with tempfile.TemporaryDirectory(prefix="cpq-render-") as folder:
        output = Path(folder) / "page"
        subprocess.run([executable, "-f", str(page_number), "-l", str(page_number),
                        "-scale-to", "1450", "-jpeg", "-jpegopt", "quality=80",
                        "-singlefile", row["file_path"], str(output)],
                       check=True, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        result = output.with_suffix(".jpg").read_bytes()
    with RENDER_LOCK:
        if len(RENDER_CACHE) >= 20:
            RENDER_CACHE.pop(next(iter(RENDER_CACHE)))
        RENDER_CACHE[key] = result
    return result


if __name__ == "__main__":
    with connect() as db:
        ws.setup(db)
        db.execute("UPDATE token_operations SET status='interrupted',error='서버 재시작으로 중단되었습니다. 실제 사용량이 없는 경우 확인이 필요합니다.' WHERE status IN ('queued','running')")
        db.commit()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"CPQ Review: http://127.0.0.1:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

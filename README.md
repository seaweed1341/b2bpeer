# CPQ 정합성 리뷰

LGBC 3.0 시나리오와 ALM PRD의 차이를 원본 PDF 페이지와 함께 검토하는 로컬 웹앱입니다.

## 실행

이 폴더에서 `./run.command`를 실행한 뒤 [http://127.0.0.1:8766](http://127.0.0.1:8766)을 엽니다. 종료는 터미널에서 `Ctrl+C`입니다. 서버는 로컬 주소에만 연결됩니다.

`pypdf`가 필요합니다. Codex 번들 Python이 있으면 실행 스크립트가 사용합니다. 다른 Python 환경에서는 `python3 -m pip install -r requirements.txt`를 실행하세요. PDF 페이지 이미지 표시에 `pdftoppm`이 필요합니다.

## 수집과 검토

- 시나리오와 PRD를 각각 등록합니다. 같은 문서 ID로 새 PDF를 수집하면 판본이 늘어납니다.
- PDF 원본은 `data/files/`에 복사하고, 메타데이터·페이지별 텍스트·검토 결과는 `data/review.sqlite3`에 저장합니다.
- 같은 파일 내용은 SHA-256 해시로 중복 수집하지 않습니다.
- 새 판본의 페이지 텍스트가 이전 판본과 달라진 위치를 후보로 표시합니다. 화면만 바뀐 내용은 직접 검토해야 합니다.
- 첫 검토 항목 8건은 PDF를 읽고 작성한 초기 결과이며 자동 의미 판정 결과가 아닙니다. 시나리오와 PRD 원본을 나란히 보여주고 검토 근거가 있는 PRD 문구를 강조합니다. 검토 상태와 메모를 저장할 수 있습니다.
- `IDRM-14471`은 `Rejected`, `IDRM-14453`은 `Open`으로 표시합니다. 유효 정책 판단 시 상태를 확인하세요.

원본 폴더에서 다시 수집하려면 다음 명령을 사용합니다.

```sh
python3 seed.py "/cpq.pdf와 almpdf가 있는/폴더"
```

## 구조와 확장 지점

`documents`는 `kind`(scenario/prd), `source`, `external_id`, `version`, `sha256`을 갖고 `pages`가 페이지별 텍스트를 보관합니다. `findings`와 `finding_evidence`는 검토 결과를 문서 판본·페이지에 연결합니다.

향후 ALM 수집기는 필터링한 요구사항을 `external_id`와 버전으로 정규화하여 이 저장소에 넣을 수 있습니다. Figma 수집기는 페이지·노드 ID를 원본 근거로 확장해야 합니다. 현재 Figma API, ALM API, Figma 플러그인 연동은 구현되지 않았습니다. 기존 판본 비교는 텍스트 변경 후보 수준입니다.

## API

- `GET /api/dashboard` — 문서 및 검토 항목
- `GET /api/documents` — 문서 목록
- `POST /api/documents?kind=prd&external_id=IDRM-...&filename=...` — PDF 바이너리 업로드
- `GET /api/documents/{id}` — 문서와 페이지 목록
- `GET /api/documents/{id}/changes` — 이전 판본 대비 텍스트 변경 페이지 후보
- `GET /api/documents/{id}/pages/{n}` — 페이지 텍스트
- `GET /api/documents/{id}/pages/{n}/image` — 원본 페이지 이미지
- `PATCH /api/findings/{id}` — 검토 상태와 메모

## Workspace beta: sources, knowledge, and token ledger

- Menus: Home, scenario/PRD comparison, PRD comparison, PRD interpretation, original document library, Knowledge Base Beta.
- Library tabs only upload and view originals. Existing document IDs create new immutable PDF versions.
- In Knowledge Base → Initial baseline / updates, explicitly record the currently registered source versions. This does not approve knowledge or run analysis. Use **full review** for the initial interpretation; subsequent **delta** plans compare against this saved baseline. Do not advance the baseline until the changes have been reviewed.
- Delta plans compare normalized page text, include old/deleted text, neighboring pages, and up to two lexical context candidates per selected document. Unchanged text with a different PDF hash prompts a full visual-review candidate. This is not a semantic impact guarantee or pixel diff.
- Execution starts with a persisted estimate. The range is a rough text-character heuristic, not exact model tokenization; PDF images are not sent. The output cap is 6,000 tokens. No-change and identical-result reuse avoid model calls.
- Knowledge markdown lives in `knowledge/`, with metadata/source references and searchable text in SQLite. Initial source-grounded CPQ guides are drafts. Human confirmation is explicit. New source versions mark dependent notes as outdated; existing annotations remain on their original PDF version.
- OpenAI is optional: configure `OPENAI_API_KEY` and `B2B_OPENAI_MODEL` in the server environment, then explicitly select OpenAI in the UI. The default remains local, zero GPT tokens. Never place keys in browser code. `B2B_MAX_INPUT_ESTIMATE` defaults to 500000 and rejects oversized estimated inputs. AI sends extracted page text plus bounded current, confirmed KB context; use a model with appropriate context capacity. No live API call was made during implementation validation.
- AI jobs run serially and produce **Markdown review drafts with source links**; they do not automatically replace the reviewed conflict table or approve KB knowledge. In local mode, conflict runs revalidate existing findings, and PRD interpretation assembles the compatible written guides. New PRDs need an AI call or human interpretation.
- Actual tokens are read only from the API `usage` response. Cached input is recorded separately and is already included in input tokens. Failed/interrupted requests with unknown usage remain unknown, never falsely zero. API errors are not automatically retried. A server restart marks unfinished jobs interrupted.
- History includes estimates, queued/running work, completed work, result reuse, failure and interruption; older pre-ledger runs are not retroactively assigned token counts. Use the refresh button to check progress. No scheduled sync or automatic polling runs.
- New ALM URLs are stored as pending references only. The app does not fetch them; upload the PDF until an authenticated ALM integration is configured.

Verification: `python3 -m unittest discover -s tests -v` (use the Python runtime in `run.command` if system Python lacks dependencies).

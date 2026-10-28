#!/usr/bin/env python3
"""Import the supplied source PDFs and the first human-reviewed findings."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from store import connect, import_pdf, now, INITIAL_ACTIONS
from highlights import refresh_seed_highlights


FINDINGS = [
    {
        "category": "scenario_prd", "severity": "high", "title": "Free Trial 기간·수량·상품이 다름",
        "summary": "시나리오는 6개월·최대 10대·Premium을 표시한다. 두 유효 PRD는 1개월·최대 3대·Mom-and-Pops로 정의한다.",
        "recommendation": "Free Trial 화면의 조건과 안내 문구를 최신 PRD 기준으로 수정하고, 헤더 진입 버튼을 확인한다.",
        "evidence": [("CPQ_SCENARIO", 15, "6 months / 10 licenses / Premium"),
                     ("IDRM-13795", 2, "Portal 3.0 헤더 Free Trial, 1 month, 최대 3대"),
                     ("IDRM-14344", 3, "Mom-and-Pops, 최대 3대 / 1개월")],
    },
    {
        "category": "scenario_prd", "severity": "high", "title": "CPQ 진입 경로별 최초 설문 순서가 다름",
        "summary": "시나리오는 디바이스 질문을 먼저 보여주고 솔루션으로 건너뛰기를 허용한다. PRD는 BC 유입 시 SW 설문 우선, OBS 유입 시 HW 설문 우선이며 최초 설문은 필수다.",
        "recommendation": "BC·OBS 및 지역별 최초 질문, 건너뛰기 가능 시점, 결과 진입 순서를 하나의 플로우로 확정한다.",
        "evidence": [("CPQ_SCENARIO", 37, "디바이스 Prompt Maker → 솔루션, 디바이스 생략 가능"),
                     ("CPQ_SCENARIO", 40, "디바이스 추천 건너뛰고 솔루션 추천받기"),
                     ("IDRM-14201", 7, "BC 경로 SW 설문 우선 / OBS 경로 HW 설문 우선")],
    },
    {
        "category": "scenario_prd", "severity": "high", "title": "SW 기능 카테고리와 레벨 체계가 다름",
        "summary": "시나리오 1.0.7은 운영·모니터링·콘텐츠·자동화·데이터 분석으로 재구성했다. PRD는 제어·모니터링·콘텐츠·배포·분석/자동화와 이에 따른 레벨·가격표를 정의한다.",
        "recommendation": "카테고리 이름과 기능 배치, 레벨 수, 가격표의 최종 기준을 확정한 뒤 양쪽 문서를 동기화한다.",
        "evidence": [("CPQ_SCENARIO", 67, "Modified v1.0.7 각 항목별 레벨 업데이트"),
                     ("IDRM-14201", 3, "제어 / 모니터링 / 콘텐츠 / 배포 / 분석·자동화"),
                     ("IDRM-14201", 4, "카테고리별 누적 단가 및 레벨")],
    },
    {
        "category": "scenario_prd", "severity": "medium", "title": "최초 추천 UI가 Prompt Maker와 대화형 설문으로 다름",
        "summary": "시나리오는 별도 Prompt Maker에서 선택값으로 프롬프트를 완성해 제출한다. PRD는 AI Assistant를 전체 폭으로 열고 Q-Reply·자연어 설문을 마친 뒤 3패널로 확장한다.",
        "recommendation": "Prompt Maker가 대화형 설문을 대체하는지, 또는 AI Assistant 진입 전 화면인지 명시한다.",
        "evidence": [("CPQ_SCENARIO", 38, "선택 결과로 AI Assistant 최초 입력 프롬프트 생성"),
                     ("IDRM-14201", 2, "초기 Left Panel 전체 폭, 이후 3-Panel Split"),
                     ("IDRM-14201", 7, "AI Assistant 설문 후 즉시 결과")],
    },
    {
        "category": "scenario_prd", "severity": "medium", "title": "My Quotes 예시가 삭제된 상품·상태를 표시",
        "summary": "시나리오의 견적 예시에 Shared 상태와 AI Complete Pack이 남아 있다. 최신 PRD는 견적 공유를 삭제하고 AI 상품을 단일 AI Pack으로 통합했다.",
        "recommendation": "My Quotes 목록·상세·비교 예시의 상태와 상품명을 최신 정책으로 교체한다.",
        "evidence": [("CPQ_SCENARIO", 25, "Shared / AI Complete Pack"),
                     ("IDRM-14344", 2, "견적 공유 삭제"),
                     ("IDRM-14344", 3, "AI Pack 단일화")],
    },
    {
        "category": "scenario_prd", "severity": "medium", "title": "견적 CSV Export 동선이 시나리오에 보이지 않음",
        "summary": "PRD는 북미·북미 외 모두에서 Export CSV를 허용한다. 시나리오의 Quotation 액션 화면에는 저장·구매·Contact Us만 표시한다.",
        "recommendation": "Export가 실제 제공 범위라면 Quotation 또는 My Quotes의 버튼과 완료 상태를 정의한다.",
        "evidence": [("CPQ_SCENARIO", 78, "견적 저장 / 바로 구매 / Contact Us"),
                     ("IDRM-14201", 5, "Export CSV 다운로드")],
    },
    {
        "category": "prd_prd", "severity": "high", "title": "수집 이벤트가 삭제된 구매 동선을 참조",
        "summary": "데이터 수집 PRD에는 견적 공유와 견적서의 장바구니 전송 이벤트가 남아 있다. CPQ·Portal PRD에서는 두 기능을 삭제했다.",
        "recommendation": "제공하지 않는 이벤트를 수집 목록에서 제거하거나, 실제 대체 구매 동선의 이벤트로 재정의한다.",
        "evidence": [("IDRM-14473", 3, "Req-07 견적 공유 / Req-11 장바구니 전송 이력"),
                     ("IDRM-14201", 5, "CPQ 장바구니 담기 삭제"),
                     ("IDRM-14344", 2, "견적 공유 삭제")],
    },
    {
        "category": "prd_prd", "severity": "medium", "title": "Home의 개별 기능 선택 문구가 구매 단위와 다름",
        "summary": "Portal PRD의 Home 카피는 개별 기능을 선택할 수 있다고 말한다. CPQ PRD는 카테고리별 레벨만 선택 가능하며 개별 기능 선택은 불가하다고 정의한다.",
        "recommendation": "Home 안내 문구를 레벨 단위 선택 정책에 맞춰 수정한다.",
        "evidence": [("IDRM-14344", 2, "Select individual features"),
                     ("IDRM-14201", 3, "개별 기능 선택 불가, 카테고리별 레벨 단위")],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path, help="cpq.pdf와 almpdf가 있는 폴더")
    args = parser.parse_args()
    source = args.source_dir.expanduser().resolve()
    scenario = source / "cpq.pdf"
    prds = sorted((source / "almpdf").glob("*.pdf"))
    if not scenario.is_file() or not prds:
        parser.error("cpq.pdf 또는 almpdf의 PRD PDF를 찾을 수 없습니다.")
    with connect() as db:
        imports = [(scenario, "scenario", "CPQ_SCENARIO")]
        for path in prds:
            match = re.search(r"IDRM-\d+", path.name)
            if not match:
                raise ValueError(f"ALM ID를 파일명에서 찾을 수 없습니다: {path.name}")
            imports.append((path, "prd", match.group()))
        for path, kind, external_id in imports:
            doc_id, created = import_pdf(db, path, kind, external_id, "local_seed")
            print(f"{'Imported' if created else 'Exists'} {external_id}: #{doc_id}", flush=True)
        if db.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0:
            for item in FINDINGS:
                stamp = now()
                cur = db.execute("""INSERT INTO findings(category,severity,title,summary,recommendation,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?)""", (item["category"], item["severity"], item["title"],
                    item["summary"], item["recommendation"], stamp, stamp))
                db.execute('UPDATE findings SET action_type=? WHERE id=?', (INITIAL_ACTIONS.get(item['title'], 'clarify'), cur.lastrowid))
                for external_id, page, excerpt in item["evidence"]:
                    doc = db.execute("SELECT id FROM documents WHERE external_id=? ORDER BY version DESC LIMIT 1", (external_id,)).fetchone()
                    db.execute("INSERT INTO finding_evidence(finding_id,document_id,page_number,excerpt) VALUES (?,?,?,?)",
                               (cur.lastrowid, doc["id"], page, excerpt))
            db.commit()
            print(f"Seeded {len(FINDINGS)} findings", flush=True)
        print(f"Located highlights for {refresh_seed_highlights(db)} evidence pages", flush=True)


if __name__ == "__main__":
    main()

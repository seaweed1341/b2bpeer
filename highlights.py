"""Locate reviewed evidence on source PDF pages for visual annotation."""

from __future__ import annotations

import json
import logging

import pdfplumber


logging.getLogger("pdfminer").setLevel(logging.ERROR)

SEED_TERMS = {
    ("Free Trial 기간·수량·상품이 다름", "IDRM-13795", 2): ["1 month free trial", "maximum of 3 trials"],
    ("Free Trial 기간·수량·상품이 다름", "IDRM-14344", 3): ["1 month free trial", "maximum of 3 trials"],
    ("CPQ 진입 경로별 최초 설문 순서가 다름", "IDRM-14201", 7): ["BC 경로", "SW 서베이 진행", "OBS 경로", "HW 서베이 진행"],
    ("SW 기능 카테고리와 레벨 체계가 다름", "IDRM-14201", 3): ["개별 기능 선택 불가", "카테고리별 레벨"],
    ("SW 기능 카테고리와 레벨 체계가 다름", "IDRM-14201", 4): ["카테고리별 누적 단가"],
    ("최초 추천 UI가 Prompt Maker와 대화형 설문으로 다름", "IDRM-14201", 2): ["초기 상태", "3-Panel Split"],
    ("최초 추천 UI가 Prompt Maker와 대화형 설문으로 다름", "IDRM-14201", 7): ["Left Panel(AI Assistant)"],
    ("My Quotes 예시가 삭제된 상품·상태를 표시", "IDRM-14344", 2): ["견적 공유"],
    ("My Quotes 예시가 삭제된 상품·상태를 표시", "IDRM-14344", 3): ["1,000 Credits per pack"],
    ("견적 CSV Export 동선이 시나리오에 보이지 않음", "IDRM-14201", 5): ["Export CSV"],
    ("수집 이벤트가 삭제된 구매 동선을 참조", "IDRM-14473", 3): ["견적서 공유하기", "장바구니로 보낸"],
    ("수집 이벤트가 삭제된 구매 동선을 참조", "IDRM-14201", 5): ["장바구니 담기"],
    ("수집 이벤트가 삭제된 구매 동선을 참조", "IDRM-14344", 2): ["견적 공유"],
    ("Home의 개별 기능 선택 문구가 구매 단위와 다름", "IDRM-14344", 2): ["Select individual features"],
    ("Home의 개별 기능 선택 문구가 구매 단위와 다름", "IDRM-14201", 3): ["개별 기능 선택 불가"],
}


def locate(file_path: str, page_number: int, terms: list[str]) -> list[dict]:
    boxes = []
    with pdfplumber.open(file_path) as pdf:
        page = pdf.pages[page_number - 1]
        for term in terms:
            for match in page.search(term, regex=False, case=False)[:5]:
                pad = 2
                x0, y0 = max(0, match["x0"] - pad), max(0, match["top"] - pad)
                x1, y1 = min(page.width, match["x1"] + pad), min(page.height, match["bottom"] + pad)
                boxes.append({"x": round(x0 / page.width * 100, 3),
                              "y": round(y0 / page.height * 100, 3),
                              "w": round((x1 - x0) / page.width * 100, 3),
                              "h": round((y1 - y0) / page.height * 100, 3)})
    return boxes


def refresh_seed_highlights(db) -> int:
    updated = 0
    for (title, external_id, page_number), terms in SEED_TERMS.items():
        row = db.execute("""SELECT e.finding_id,e.document_id,d.file_path FROM finding_evidence e
            JOIN findings f ON f.id=e.finding_id JOIN documents d ON d.id=e.document_id
            WHERE f.title=? AND d.external_id=? AND e.page_number=?""", (title, external_id, page_number)).fetchone()
        if not row:
            continue
        boxes = locate(row["file_path"], page_number, terms)
        db.execute("""UPDATE finding_evidence SET highlight_terms=?,highlight_boxes=?
            WHERE finding_id=? AND document_id=? AND page_number=?""",
            (json.dumps(terms, ensure_ascii=False), json.dumps(boxes), row["finding_id"], row["document_id"], page_number))
        updated += 1
    db.commit()
    return updated

"""Reviewed-source starter explanations, deliberately left as drafts."""
from store import connect
import workspace_service as ws

GUIDES=[
('guide-cpq','CPQ는 무엇을 하는 기능인가요?', [('IDRM-14201',2),('IDRM-14201',7)], '''# CPQ는 무엇을 하는 기능인가요?

CPQ는 고객에게 필요한 디바이스와 소프트웨어 기능을 골라 견적을 만드는 흐름입니다. Configure(구성), Price(가격), Quote(견적)의 약자입니다. [1]({s0})

## 처음 보는 담당자를 위한 설명

고객이 자신의 사업과 필요한 기능을 설명하면 추천을 받고, 장비와 소프트웨어 구성을 조정하면서 가격을 확인합니다. PRD에서는 대화 영역, 구성 영역, 견적 영역으로 나누어 설명합니다. [1]({s0})

## 고객은 어떻게 사용하나요?

최초 질문에 답하고 추천을 받은 뒤, 디바이스 수량과 기능 레벨을 조정합니다. 견적을 저장하거나 지역별 구매·문의 흐름으로 이어집니다. 첫 설문과 이후 추가 구성은 건너뛰기 정책이 다릅니다. [2]({s1})

## 담당자가 확인할 부분

시나리오의 Prompt Maker와 PRD의 대화형 설문이 동일한 설계인지 아직 확인이 필요합니다. 이 노트는 PRD를 설명하며 화면 설계의 최종 정답을 확정하지 않습니다.
'''),
('guide-level','SW 레벨과 프리셋', [('IDRM-14201',3)], '''# SW 레벨과 프리셋

## 레벨은 기능 묶음입니다

PRD에서는 소프트웨어 기능을 카테고리별 레벨로 선택합니다. 레벨 N을 선택하면 그 카테고리의 1~N 레벨 기능이 포함됩니다. 개별 기능을 하나씩 구매하는 방식으로 이해하면 안 됩니다. [1]({s0})

## 프리셋은 추천 출발점입니다

Installer, Mom-and-Pop 같은 고객 유형을 선택하면 추천 레벨이 먼저 적용됩니다. 이후 고객이 구성 값을 조정하는 흐름입니다. [1]({s0})

## 용어

HW는 디바이스 같은 하드웨어, SW는 디바이스에서 사용할 소프트웨어 기능을 가리킵니다. 이 페이지는 두 구성 영역을 각각 설명합니다. [1]({s0})

## 확인필요

기능 카테고리 이름과 레벨 구성은 시나리오와 차이가 발견되어 최종 기준 확인이 필요합니다.
'''),
('guide-quote','견적 저장과 My Quotes', [('IDRM-14201',5),('IDRM-14201',7)], '''# 견적 저장과 My Quotes

## 견적은 구매 전 구성 기록입니다

고객이 고른 구성과 가격을 저장하고 다시 확인하는 흐름입니다. 견적 저장에는 로그인이 필요하며, 저장할 때 견적명을 지정할 수 있습니다. [1]({s0})

## My Quotes는 저장한 견적을 찾는 곳입니다

저장 완료 후 나의 견적 리스트 보기를 누르면 Plan의 My Quotes로 이동합니다. 비로그인 상태에서는 로그인을 먼저 안내합니다. [2]({s1})

## 만료와 재견적

만료된 견적은 직접 구매할 수 없으며 같은 구성으로 다시 견적을 내도록 유도합니다. 견적 저장과 주문 완료는 서로 다른 단계입니다. [1]({s0})

## 주의할 변경

PRD의 삭제 표시에 따르면 CPQ와 My Quotes 견적 상세의 장바구니 담기는 제공하지 않습니다. 오래된 변경 이력이나 예시만 보고 현재 동작으로 해석하지 않아야 합니다. [1]({s0})
'''),
('guide-trial','Free Trial과 AI Pack', [('IDRM-14344',3)], '''# Free Trial과 AI Pack

## Free Trial은 체험 라이선스입니다

해당 PRD 판본은 1개월, 최대 3대, Mom-and-Pops 조건으로 체험을 안내합니다. 미로그인 사용자는 로그인·가입을 거치고, 이전 체험 이력도 확인합니다. [1]({s0})

## AI Pack은 별도 상품입니다

AI Complete Pack과 AI Image Pack을 AI Pack으로 통합한다는 변경 내용이 있습니다. PRD의 상품 크레딧은 B2B Peer가 문서를 분석할 때 쓰는 OpenAI API 토큰과 다른 개념입니다. [1]({s0})

## 확인필요

이 설명은 등록된 PRD 판본 기준입니다. 실제 서비스 정책이 변경되면 최신 원본으로 다시 검토해야 합니다.
''')]

def main():
 with connect() as db:
  ws.setup(db)
  for id,title,refs,body in GUIDES:
   if db.execute('SELECT 1 FROM knowledge_notes WHERE id=?',(id,)).fetchone():continue
   sources=[]
   for external,page in refs:
    d=db.execute('SELECT id FROM documents WHERE external_id=? ORDER BY version ASC LIMIT 1',(external,)).fetchone()
    if not d:break
    sources.append({'document_id':d['id'],'page_number':page})
   else:
    ws.write_note(db,title,'CPQ',body.format(**{f's{i}':f"source:{s['document_id']}:{s['page_number']}" for i,s in enumerate(sources)}),sources,id)
if __name__=='__main__':main()

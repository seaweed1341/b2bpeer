"""Source snapshot validation and page-anchored review comments."""
import hashlib
import json
import math
from pathlib import Path
from store import document_rows, finding_rows, now


def setup(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS review_runs(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, snapshot TEXT NOT NULL, finding_ids TEXT NOT NULL, uncovered_ids TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS annotations(id INTEGER PRIMARY KEY, finding_id INTEGER NOT NULL REFERENCES findings(id), document_id INTEGER NOT NULL REFERENCES documents(id), page_number INTEGER NOT NULL, x REAL NOT NULL, y REAL NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')

    columns={r['name'] for r in db.execute('PRAGMA table_info(review_runs)')}
    for name,default in [('scope','{}'),('result_snapshot','[]')]:
        if name not in columns:
            db.execute(f"ALTER TABLE review_runs ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
    db.commit()

def latest_docs(db):
    return list({(d['kind'],d['external_id']):d for d in reversed(document_rows(db))}.values())


def runs(db):
    setup(db)
    result=[]
    actions={r['id']:r['action_type'] for r in db.execute('SELECT id,action_type FROM findings')}
    for row in db.execute('SELECT * FROM review_runs ORDER BY id DESC'):
        r=dict(row)
        for key in ('snapshot','finding_ids','uncovered_ids','scope','result_snapshot'):
            r[key]=json.loads(r[key])
        for f in r['result_snapshot']:
            f['action_type']=actions.get(f['id'],'clarify')
        r['stale']=False
        if not r['scope']:
            r['scope']={'category':'legacy','product':'CPQ','scenario_id':None,'prd_ids':[]}
        result.append(r)
    return result


def status(db):
    history=runs(db)
    return history[0] if history else None


def analyze(db,p):
    setup(db)
    category=p.get('category')
    product=p.get('product')
    if category not in ('scenario_prd','prd_prd') or product not in ('CPQ','대시보드','데이터','콘텐츠','디바이스'):
        raise ValueError('분석 유형과 프로덕트를 선택하세요.')
    prd_ids=p.get('prd_ids')
    if not isinstance(prd_ids,list) or not all(type(x) is int for x in prd_ids): raise ValueError('PRD를 선택하세요.')
    prd_ids=sorted(set(prd_ids))
    if len(prd_ids)<(1 if category=='scenario_prd' else 2): raise ValueError('비교할 PRD가 부족합니다.')
    scenario_id=p.get('scenario_id') if category=='scenario_prd' else None
    docs={d['id']:d for d in document_rows(db)}
    if category=='scenario_prd' and (scenario_id not in docs or docs[scenario_id]['kind']!='scenario' or docs[scenario_id]['product']!=product):
        raise ValueError('해당 프로덕트의 시나리오 버전을 선택하세요.')
    if any(i not in docs or docs[i]['kind']!='prd' for i in prd_ids): raise ValueError('PRD 선택이 올바르지 않습니다.')
    ids=set(prd_ids+([scenario_id] if scenario_id else []))
    for i in ids:
        d=docs[i]
        if hashlib.sha256(Path(d['file_path']).read_bytes()).hexdigest()!=d['sha256']:
            raise ValueError('원본 파일이 변경되었습니다. PDF를 다시 수집하세요.')
    findings=[f for f in finding_rows(db) if f['category']==category and f['evidence'] and all(e['document_id'] in ids for e in f['evidence'])]
    covered={e['document_id'] for f in findings for e in f['evidence']}
    scope={'category':category,'product':product,'scenario_id':scenario_id,'prd_ids':prd_ids,'scenario_version':docs[scenario_id]['version'] if scenario_id else None,'scenario_name':docs[scenario_id]['filename'] if scenario_id else None}
    db.execute('INSERT INTO review_runs(created_at,snapshot,finding_ids,uncovered_ids,scope,result_snapshot) VALUES(?,?,?,?,?,?)', (now(),json.dumps(sorted([[i,docs[i]['sha256']] for i in ids])),json.dumps([f['id'] for f in findings]),json.dumps(sorted(ids-covered)),json.dumps(scope,ensure_ascii=False),json.dumps(findings,ensure_ascii=False)))
    db.commit()
    return status(db)


def add_annotation(db,p):
    setup(db)
    body=p.get('body')
    if not isinstance(body,str) or not body.strip() or len(body)>5000: raise ValueError('메모는 1~5000자로 입력하세요.')
    x,y=p.get('x'),p.get('y')
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100 for v in (x,y)): raise ValueError('주석 위치가 올바르지 않습니다.')
    match=db.execute('SELECT 1 FROM finding_evidence WHERE finding_id=? AND document_id=? AND page_number=?',(p.get('finding_id'),p.get('document_id'),p.get('page_number'))).fetchone()
    if not match: raise ValueError('검토 근거 페이지에만 주석을 추가할 수 있습니다.')
    cur=db.execute('INSERT INTO annotations(finding_id,document_id,page_number,x,y,body,created_at) VALUES(?,?,?,?,?,?,?)',(p['finding_id'],p['document_id'],p['page_number'],x,y,body.strip(),now()))
    db.commit()
    return dict(db.execute('SELECT * FROM annotations WHERE id=?',(cur.lastrowid,)).fetchone())

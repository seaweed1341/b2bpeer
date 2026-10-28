import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import store
import workspace_service as ws

class WorkspaceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.patches=[patch.object(store,'DATA',self.root),patch.object(store,'FILES',self.root/'files'),patch.object(store,'DB',self.root/'test.db'),patch.object(ws,'KB_DIR',self.root/'knowledge')]
  for p in self.patches:p.start()
  self.db=store.connect();ws.setup(self.db)
  self.doc=self.add_doc('REQ-A',1,['intro','save quote','purchase flow'])
  self.payload={'product':'CPQ','task':'interpret','mode':'delta','engine':'local','prd_ids':[self.doc]}
 def tearDown(self):
  self.db.close()
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def add_doc(self,external,version,texts):
  path=self.root/f'{external}-{version}.pdf';path.write_bytes(('pdf'+external+str(version)+''.join(texts)).encode());digest=hashlib.sha256(path.read_bytes()).hexdigest()
  cur=self.db.execute('INSERT INTO documents(kind,source,external_id,version,title,filename,file_path,sha256,page_count,imported_at,product) VALUES(?,?,?,?,?,?,?,?,?,?,?)',('prd','test',external,version,external,path.name,str(path),digest,len(texts),store.now(),'CPQ'))
  id=cur.lastrowid
  for page,text in enumerate(texts,1):self.db.execute('INSERT INTO pages VALUES(?,?,?,?,?)',(id,page,'page',text,hashlib.sha256(text.encode()).hexdigest()))
  self.db.commit();return id
 def baseline(self):return ws.set_baseline(self.db,{'product':'CPQ','snapshot':ws.snapshot(ws.latest(self.db,'CPQ'))})
 def test_initial_estimate_and_reuse(self):
  a=ws.prepare(self.db,self.payload);self.assertEqual(a['plan']['effective_mode'],'full');self.assertIsNone(a['actual_input'])
  a=ws.execute(self.db,a['id']);self.assertEqual(a['status'],'completed');self.assertEqual(a['actual_input'],0)
  b=ws.execute(self.db,ws.prepare(self.db,self.payload)['id']);self.assertEqual(b['status'],'reused');self.assertEqual(a['result'],b['result'])
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM knowledge_notes').fetchone()[0],1)
 def test_baseline_and_unchanged(self):
  self.baseline();op=ws.prepare(self.db,self.payload);self.assertTrue(op['plan']['unchanged'])
  done=ws.execute(self.db,op['id']);self.assertEqual(done['result']['type'],'unchanged');self.assertEqual(done['actual_output'],0)
 def test_delta_deletion_and_previous_context(self):
  self.baseline();new=self.add_doc('REQ-A',2,['intro','purchase flow'])
  op=ws.prepare(self.db,{**self.payload,'prd_ids':[new]});self.assertTrue(any(c['kind']=='delete' for c in op['plan']['changes']))
  self.assertTrue(any(p['document_id']==self.doc and p['role']=='previous' for p in op['plan']['pages']))
  self.assertEqual(ws.baseline(self.db,'CPQ')['snapshot'][0][0],self.doc)
 def test_visual_only_requires_review(self):
  self.baseline();new=self.add_doc('REQ-A',2,['intro','save quote','purchase flow'])
  op=ws.prepare(self.db,{**self.payload,'prd_ids':[new]});self.assertEqual(op['plan']['changes'][0]['kind'],'visual_check')
 def test_new_document_full_and_stale_estimate(self):
  self.baseline();new=self.add_doc('REQ-B',1,['new requirement'])
  op=ws.prepare(self.db,{**self.payload,'prd_ids':[new]});self.assertEqual(op['plan']['new_documents'],['REQ-B'])
  self.baseline()
  with self.assertRaises(ValueError):ws.execute(self.db,op['id'])
 def test_unknown_sources_and_ai_not_configured(self):
  with self.assertRaises(ValueError):ws.prepare(self.db,{**self.payload,'prd_ids':[999]})
  with patch.dict('os.environ',{},clear=True):
   with self.assertRaises(ValueError):ws.prepare(self.db,{**self.payload,'engine':'openai'})
 def test_note_stale_and_review(self):
  n=ws.write_note(self.db,'test','CPQ','# test',[{'document_id':self.doc,'page_number':1}])
  self.assertEqual(ws.review_note(self.db,{'id':n['id'],'status':'verified'})['status'],'verified')
  self.add_doc('REQ-A',2,['new'])
  self.assertTrue(ws.get_note(self.db,n['id'])['outdated'])
  with self.assertRaises(ValueError):ws.review_note(self.db,{'id':n['id'],'status':'verified'})
 def test_raw_source_tamper_rejected(self):
  op=ws.prepare(self.db,self.payload)
  path=self.db.execute('SELECT file_path FROM documents WHERE id=?',(self.doc,)).fetchone()[0];Path(path).write_text('tampered')
  with self.assertRaises(ValueError):ws.execute(self.db,op['id'])

 def test_ai_usage_is_api_reported_and_sources_validated(self):
  import io
  response={'status':'completed','usage':{'input_tokens':231,'output_tokens':72,'input_tokens_details':{'cached_tokens':100}},'output':[{'content':[{'type':'output_text','text':f'# 설명\n근거 [1](source:{self.doc}:1)'}]}]}
  with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only','B2B_OPENAI_MODEL':'test-model'}):
   op=ws.prepare(self.db,{**self.payload,'engine':'openai'})
   with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):ws.ai_job(op['id'])
  done=ws.get_operation(self.db,op['id'])
  self.assertEqual(done['status'],'completed');self.assertEqual(done['actual_input'],231);self.assertEqual(done['actual_output'],72);self.assertEqual(done['cached_input'],100)
 def test_ai_failure_keeps_usage_unknown(self):
  with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only','B2B_OPENAI_MODEL':'test-model'}):
   op=ws.prepare(self.db,{**self.payload,'engine':'openai'})
   with patch('urllib.request.urlopen',side_effect=TimeoutError()):ws.ai_job(op['id'])
  done=ws.get_operation(self.db,op['id']);self.assertEqual(done['status'],'failed');self.assertIsNone(done['actual_input'])

if __name__=='__main__':unittest.main()

"""Run python -m unittest discover -s tests from project directory."""
import io
import unittest
import uuid
import fitz
from fastapi.testclient import TestClient
from server import app

client=TestClient(app)
DEMO='static/example.pdf'

class PDFStudioTests(unittest.TestCase):
    def setUp(self):
        self.sid=uuid.uuid4().hex
        self.headers={'X-Session':self.sid}
        with open(DEMO,'rb') as f:
            res=client.post('/api/open',files={'file':('demo.pdf',f,'application/pdf')},headers=self.headers)
        self.assertEqual(res.status_code,200,res.text)
        self.count=res.json()['count']

    def test_real_original_text_edit(self):
        blocks=client.get('/api/page/0/blocks',headers=self.headers)
        self.assertEqual(blocks.status_code,200,blocks.text)
        options=blocks.json()['blocks']
        selected=next(b for b in options if 'Project Review' in b['text'])
        update=client.post('/api/text/edit',headers=self.headers,json={
            'page':0,'block':selected['id'],'text':'Final Document Review',
            'font_size':selected['size'],'width':selected['suggestedWidth'],
            'color':selected['color'],'font_override':'original'})
        self.assertEqual(update.status_code,200,update.text)
        output=client.get('/api/export',headers=self.headers)
        self.assertEqual(output.status_code,200)
        with fitz.open(stream=output.content,filetype='pdf') as doc:
            txt=doc[0].get_text()
            self.assertIn('Final Document Review',txt)
            self.assertNotIn('Project Review',txt)
            self.assertEqual(len(doc),self.count)

    def test_tight_heading_edits_in_place(self):
        blocks=client.get('/api/page/0/blocks',headers=self.headers).json()['blocks']
        heading=next(b for b in blocks if 'CONTOH DOKUMEN PDF' in b['text'])
        update=client.post('/api/text/edit',headers=self.headers,json={
            'page':0,'block':heading['id'],'text':'EDIT PDF LANGSUNG',
            'font_size':heading['size'],'width':heading['suggestedWidth'],
            'color':heading['color'],'font_override':'original'})
        self.assertEqual(update.status_code,200,update.text)
        with fitz.open(stream=client.get('/api/export',headers=self.headers).content,filetype='pdf') as doc:
            text=doc[0].get_text()
            self.assertIn('EDIT PDF LANGSUNG',text)
            self.assertNotIn('CONTOH DOKUMEN PDF',text)
            self.assertIn('Gunakan file ini',text)

    def test_unicode_fallback_prevents_gibberish(self):
        with open('static/example-embedded.pdf','rb') as f:
            res=client.post('/api/open',files={'file':('font-embedded.pdf',f,'application/pdf')},headers=self.headers)
        self.assertEqual(res.status_code,200,res.text)
        b=client.get('/api/page/0/blocks',headers=self.headers).json()['blocks'][0]
        self.assertIn('Teks sumber',b['text'])
        new='Nilai Rp1.000 dan café di Bandung.'
        update=client.post('/api/text/edit',headers=self.headers,json={
            'page':0,'block':b['id'],'text':new,'font_size':b['size'],
            'width':b['suggestedWidth'],'color':b['color'],'font_override':'original'})
        self.assertEqual(update.status_code,200,update.text)
        with fitz.open(stream=client.get('/api/export',headers=self.headers).content,filetype='pdf') as doc:
            self.assertIn(new,doc[0].get_text())
            self.assertNotIn('Teks sumber',doc[0].get_text())

    def test_org_rotate_duplicate_delete_merge_export(self):
        r=client.post('/api/pages/action',json={'action':'rotate','page':0},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['pages'][0]['rotation'],90)
        r=client.post('/api/pages/action',json={'action':'duplicate','page':0},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['count'],self.count+1)
        r=client.post('/api/pages/reorder',json={'order':list(reversed(range(self.count+1)))},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        r=client.post('/api/pages/action',json={'action':'delete','page':0},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['count'],self.count)
        with open(DEMO,'rb') as f:
            r=client.post('/api/merge',headers=self.headers,files=[('files',('another.pdf',f,'application/pdf'))])
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['count'],self.count*2)
        r=client.get('/api/export?pages=0,2',headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        with fitz.open(stream=r.content,filetype='pdf') as doc:self.assertEqual(len(doc),2)

    def test_undo_redo_and_fail_no_damage(self):
        src=client.get('/api/export',headers=self.headers).content
        blocks=client.get('/api/page/0/blocks',headers=self.headers).json()['blocks']
        b=next(b for b in blocks if 'Project Review' in b['text'])
        payload={'page':0,'block':b['id'],'text':'A'*1500,'font_size':b['size'],'width':b['suggestedWidth'],'color':b['color']}
        r=client.post('/api/text/edit',json=payload,headers=self.headers)
        self.assertEqual(r.status_code,422)
        self.assertEqual(src,client.get('/api/export',headers=self.headers).content)
        r=client.post('/api/pages/action',json={'page':0,'action':'rotate'},headers=self.headers)
        self.assertEqual(r.status_code,200)
        r=client.post('/api/history/undo',headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['pages'][0]['rotation'],0)
        r=client.post('/api/history/redo',headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['pages'][0]['rotation'],90)

if __name__=='__main__':unittest.main()

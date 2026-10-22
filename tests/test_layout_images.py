"""Regression for adjacent table fields and discrete PDF raster XObjects."""
import io
import uuid
import unittest
from PIL import Image, ImageDraw
import fitz
from fastapi.testclient import TestClient
from server import app

client=TestClient(app)

def sample_png(color):
    img=Image.new('RGB',(100,60),'white')
    draw=ImageDraw.Draw(img)
    draw.rectangle((7,5,90,55),fill=color)
    data=io.BytesIO();img.save(data,format='PNG');return data.getvalue()

def sample_pdf(reuse=False):
    doc=fitz.open();p=doc.new_page(width=600,height=440)
    p.draw_rect(fitz.Rect(55,200,540,226),color=None,fill=(.93,.93,.93))
    p.insert_text((85,150),'GAJI BULAN    :     September 2026',fontname='hebo',fontsize=12)
    p.insert_text((85,170),'NAMA KARYAWAN     :      Sample Person',fontname='hebo',fontsize=12)
    p.insert_text((85,190),'NIK              :      123456789',fontname='helv',fontsize=12)
    p.insert_image(fitz.Rect(80,35,160,83),stream=sample_png((0,90,180)))
    if reuse:
        q=doc.new_page(width=600,height=440)
        q.insert_image(fitz.Rect(80,35,160,83),xref=doc[0].get_images()[0][0])
    data=doc.tobytes();doc.close();return data

class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.headers={'X-Session':uuid.uuid4().hex}
        self.orig=sample_pdf()
        r=client.post('/api/open',headers=self.headers,files={'file':('slip.pdf',self.orig,'application/pdf')})
        self.assertEqual(r.status_code,200,r.text)

    def blocks(self):
        r=client.get('/api/page/0/blocks',headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def test_in_place_label_does_not_move_other_columns(self):
        runs=self.blocks()['blocks']
        self.assertTrue(any(b['text']=='GAJI BULAN' for b in runs),[b['text'] for b in runs])
        b=next(b for b in runs if b['text']=='GAJI BULAN')
        before=fitz.open(stream=client.get('/api/export',headers=self.headers).content,filetype='pdf')
        original_chars=[]
        for word in before[0].get_text('words'):
            if word[4] in ('September','2026','NAMA','KARYAWAN','Person'):
                original_chars.append(word[:5])
        out=client.post('/api/text/edit',headers=self.headers,json={
            'page':0,'block':b['id'],'text':'GAJI TAHUN','font_size':b['size'],
            'width':b['suggestedWidth'],'color':b['color']})
        self.assertEqual(out.status_code,200,out.text)
        after=fitz.open(stream=client.get('/api/export',headers=self.headers).content,filetype='pdf')
        self.assertIn('GAJI TAHUN',after[0].get_text())
        self.assertNotIn('GAJI BULAN',after[0].get_text())
        assert after[0].get_text().count(':')==3,after[0].get_text()
        updated=[]
        for word in after[0].get_text('words'):
            if word[4] in ('September','2026','NAMA','KARYAWAN','Person'):
                updated.append(word[:5])
        self.assertEqual([(tuple(round(v,2) for v in row[:4]),row[4]) for row in original_chars],
                         [(tuple(round(v,2) for v in row[:4]),row[4]) for row in updated])
        # Compare image pixels away from the edited label bounding box.
        pixa=before[0].get_pixmap(alpha=False,matrix=fitz.Matrix(1,1))
        pixb=after[0].get_pixmap(alpha=False,matrix=fitz.Matrix(1,1))
        orig=Image.frombytes('RGB',(pixa.width,pixa.height),pixa.samples)
        new=Image.frombytes('RGB',(pixb.width,pixb.height),pixb.samples)
        mask=Image.new('RGB',orig.size,'black')
        draw=ImageDraw.Draw(mask)
        x0,y0,x1,y1=b['bbox'];draw.rectangle((x0-3,y0-4,x1+130,y1+4),fill='white')
        import PIL.ImageChops
        outside=PIL.ImageChops.difference(orig,new)
        outside.paste('black',mask=mask.convert('L'))
        self.assertIsNone(outside.getbbox())
        before.close();after.close()

    def test_image_replacement_and_deletion(self):
        items=self.blocks()['images'];self.assertEqual(len(items),1,items)
        self.assertAlmostEqual(items[0]['bbox'][0],80,delta=.01)
        r=client.post('/api/image/replace',params={'page':0,'image':items[0]['id']},headers=self.headers,
                      files={'file':('new.png',sample_png((200,0,0)),'image/png')})
        self.assertEqual(r.status_code,200,r.text)
        with fitz.open(stream=client.get('/api/export',headers=self.headers).content,filetype='pdf') as doc:
            pix=doc[0].get_pixmap(alpha=False)
            img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            c=img.getpixel((120,62));self.assertGreater(c[0],c[2]);self.assertIn('GAJI BULAN',doc[0].get_text())
        item=self.blocks()['images'][-1]
        r=client.post('/api/image/delete',json={'page':0,'image':item['id']},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        with fitz.open(stream=client.get('/api/export',headers=self.headers).content,filetype='pdf') as doc:
            pix=doc[0].get_pixmap(alpha=False)
            img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            self.assertEqual(img.getpixel((120,62)),(255,255,255))

    def test_shared_image_only_edits_target_page(self):
        self.headers={'X-Session':uuid.uuid4().hex}
        r=client.post('/api/open',headers=self.headers,files={'file':('shared.pdf',sample_pdf(reuse=True),'application/pdf')})
        self.assertEqual(r.status_code,200,r.text)
        image=self.blocks()['images'][0]
        r=client.post('/api/image/delete',json={'page':0,'image':image['id']},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        with fitz.open(stream=client.get('/api/export',headers=self.headers).content,filetype='pdf') as d:
            pg0=Image.frombytes('RGB',(600,440),d[0].get_pixmap().samples)
            pg1=Image.frombytes('RGB',(600,440),d[1].get_pixmap().samples)
            self.assertEqual(pg0.getpixel((120,62)),(255,255,255))
            self.assertLess(pg1.getpixel((120,62))[0],100)

if __name__=='__main__':unittest.main()

"""PDF Studio v2. Original PDF text block reconstruction with PyMuPDF.
Run: uvicorn server:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import io
import math
import os
import re
import sys
import unicodedata
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Literal

import fitz
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
MAX_FILE = 60 * 1024 * 1024
MAX_PAGES = 500
TTL = 2 * 60 * 60
app = FastAPI(title='PDF Studio', version='2.3')

@dataclass
class Workspace:
    name: str = 'Dokumen Baru.pdf'
    revisions: list[bytes] = field(default_factory=list)
    pointer: int = -1
    touched: float = field(default_factory=time.time)
    lock: RLock = field(default_factory=RLock)

    @property
    def raw(self):
        if self.pointer < 0:
            raise HTTPException(400, 'Belum ada PDF yang dibuka.')
        return self.revisions[self.pointer]

    def commit(self, raw: bytes):
        self.revisions = self.revisions[:self.pointer+1] + [raw]
        if len(self.revisions) > 12:
            self.revisions.pop(0)
        self.pointer = len(self.revisions)-1
        self.touched = time.time()

SESSIONS: dict[str, Workspace] = {}
SESSION_LOCK = RLock()

def workspace(session: str | None, create: bool = False) -> Workspace:
    if not session or not re.fullmatch(r'[a-f0-9]{32}', session):
        raise HTTPException(401, 'ID sesi tidak valid.')
    with SESSION_LOCK:
        for key, item in list(SESSIONS.items()):
            if time.time() - item.touched > TTL:
                del SESSIONS[key]
        if session not in SESSIONS:
            if not create:
                raise HTTPException(404, 'Sesi berakhir. Buka kembali PDF kamu.')
            SESSIONS[session] = Workspace()
        w = SESSIONS[session]
        w.touched = time.time()
        return w

def get_doc(raw: bytes) -> fitz.Document:
    try:
        doc = fitz.open(stream=raw, filetype='pdf')
        if doc.needs_pass:
            doc.close()
            raise HTTPException(422, 'PDF dilindungi password. Buka proteksinya terlebih dahulu.')
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f'PDF tidak dapat dibuka: {str(e)[:140]}')

def save_pdf(doc: fitz.Document) -> bytes:
    return doc.tobytes(garbage=3, deflate=True)

def summary(w: Workspace) -> dict:
    if w.pointer < 0:
        return {'name':w.name,'pages': [], 'count':0,'undo':False,'redo':False}
    with get_doc(w.raw) as doc:
        pages=[{'index':i,'width':round(p.rect.width,2),'height':round(p.rect.height,2),'rotation':p.rotation} for i,p in enumerate(doc)]
    return {'name':w.name,'pages':pages,'count':len(pages), 'undo':w.pointer>0, 'redo':w.pointer<len(w.revisions)-1}

async def read_uploaded(file: UploadFile):
    name=Path(file.filename or 'document.pdf').name
    if not name.lower().endswith('.pdf'):
        raise HTTPException(422, f'{name}: hanya .pdf yang diterima.')
    content=await file.read(MAX_FILE+1)
    if len(content)>MAX_FILE: raise HTTPException(413, 'Batas ukuran tiap file adalah 60 MB.')
    if not content.startswith(b'%PDF-'):
        raise HTTPException(422, 'File tidak dikenali sebagai PDF.')
    return name,content

@app.get('/')
def index():
    return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/health')
def health(): return {'ok':True, 'engine':'PyMuPDF', 'version':fitz.VersionBind}

@app.get('/api/document')
def info(x_session: str | None = Header(None)):
    w=workspace(x_session, True)
    with w.lock: return summary(w)

@app.post('/api/open')
async def open_file(file: UploadFile=File(...), x_session: str | None=Header(None)):
    w=workspace(x_session, True)
    name,raw=await read_uploaded(file)
    with get_doc(raw) as d:
        if len(d)>MAX_PAGES: raise HTTPException(422, 'Maksimal 500 halaman.')
        normalized=save_pdf(d)
    with w.lock:
        w.name=name
        w.revisions=[];w.pointer=-1;w.commit(normalized)
        return summary(w)

@app.post('/api/merge')
async def merge(files: list[UploadFile]=File(...), x_session: str | None=Header(None)):
    w=workspace(x_session)
    incoming=[]
    for file in files:
        name,data=await read_uploaded(file)
        incoming.append((name,data))
    with w.lock, get_doc(w.raw) as doc:
        added=0
        for name,data in incoming:
            with get_doc(data) as extra:
                if len(doc)+len(extra)>MAX_PAGES:
                    raise HTTPException(422, 'Gabungan melebihi 500 halaman.')
                doc.insert_pdf(extra, links=True, annots=True)
                added+=len(extra)
        w.commit(save_pdf(doc))
        return {'added':added, **summary(w)}

class PageAction(BaseModel):
    action: Literal['rotate','duplicate','delete','blank','move_up','move_down']
    page: int

@app.post('/api/pages/action')
def page_action(body:PageAction,x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock, get_doc(w.raw) as d:
        n=len(d); i=body.page
        if i<0 or i>=n: raise HTTPException(422, 'Nomor halaman tidak valid.')
        if body.action=='rotate': d[i].set_rotation((d[i].rotation+90)%360)
        elif body.action=='duplicate':
            if n>=MAX_PAGES:raise HTTPException(422,'Batas 500 halaman tercapai.')
            d.fullcopy_page(i,to=i+1)
        elif body.action=='delete':
            if n<2:raise HTTPException(422,'Tidak bisa menghapus satu-satunya halaman.')
            d.delete_page(i)
        elif body.action=='blank':
            if n>=MAX_PAGES:raise HTTPException(422,'Batas 500 halaman tercapai.')
            rect=d[i].rect;d.new_page(pno=i+1,width=rect.width,height=rect.height)
        elif body.action in ('move_up','move_down'):
            dest=i-1 if body.action=='move_up' else i+1
            if dest<0 or dest>=n: raise HTTPException(422,'Halaman sudah berada di batas.')
            order=list(range(n));order[i],order[dest]=order[dest],order[i]
            d.select(order)
        w.commit(save_pdf(d))
        return summary(w)

class Reorder(BaseModel):
    order: list[int]

@app.post('/api/pages/reorder')
def reorder(body:Reorder,x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock,get_doc(w.raw) as doc:
        if sorted(body.order)!=list(range(len(doc))):
            raise HTTPException(422,'Urutan halaman harus mencakup semua halaman tepat sekali.')
        doc.select(body.order)
        w.commit(save_pdf(doc))
        return summary(w)

@app.get('/api/page/{page}/image')
def page_image(page:int,scale:float=1.4,x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock,get_doc(w.raw) as doc:
        if not 0<=page<len(doc):raise HTTPException(404,'Halaman tidak ditemukan.')
        scale=max(.3,min(2.2,scale)); pg=doc[page]
        pix=pg.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False,annots=True)
        png=pix.tobytes('png')
        return Response(png,media_type='image/png',headers={'Cache-Control':'no-store'})

def block_text(block:dict)->str:
    """Merge PDF visual line wraps into editable paragraphs; keep large visual gaps."""
    lines=block.get('lines',[])
    out=[];prev=None
    for line in lines:
        text=''.join(s.get('text','') for s in line.get('spans',[])).strip()
        if not text:continue
        if prev is None:
            out.append(text)
        else:
            gap=float(line['bbox'][1])-float(prev['bbox'][3])
            fs=max([s.get('size',11) for s in prev.get('spans',[])] or [11])
            if gap>fs*.65:
                out.append('\n'+text)
            elif out and out[-1].endswith('-'):
                out[-1]=out[-1][:-1]+text
            else:out.append(' '+text)
        prev=line
    return ''.join(out)

def normalize_font(name:str)->str:
    return re.sub(r'^[A-Z]{6}\+', '',name or '').lower().replace(' ','').replace('-','')

def primary_span(block:dict)->dict:
    spans=[s for ln in block.get('lines',[]) for s in ln.get('spans',[]) if s.get('text','').strip()]
    return max(spans,key=lambda s:len(s.get('text','')),default={})

def guessed_font(fontname:str)->str:
    n=normalize_font(fontname)
    if 'cour' in n or 'mono' in n: return 'cobo' if 'bold' in n else 'cour'
    if 'times' in n or 'serif' in n or 'georgia' in n: return 'tibo' if 'bold' in n else 'tiro'
    if 'bold' in n or 'black' in n or 'heavy' in n:return 'hebo'
    if 'italic' in n or 'oblique' in n:return 'heit'
    return 'helv'

def font_options(original: str):
    """Find Unicode TTF fonts installed on this system. Do not trust PDF subset
    font streams as writable fonts: original CID/glyph mapping is often incomplete.
    Fonts are referenced from the OS; no font files are distributed in this app.
    """
    dirs = []
    if sys.platform == 'win32':
        dirs = [Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts']
    elif sys.platform == 'darwin':
        dirs = [Path('/Library/Fonts'), Path('/System/Library/Fonts/Supplemental')]
    else:
        dirs = [Path('/usr/share/fonts/truetype/dejavu'),
                Path('/usr/share/fonts/truetype/liberation2'),
                Path('/usr/share/fonts/truetype/liberation'),
                Path('/usr/share/fonts/truetype/lato'),
                Path('/usr/share/fonts/truetype/msttcorefonts')]
    names = {
      'sans':[('Arial','arial.ttf'),('Segoe UI','segoeui.ttf'),('Calibri','calibri.ttf'),
              ('Liberation Sans','LiberationSans-Regular.ttf'),('DejaVu Sans','DejaVuSans.ttf'),('Lato','Lato-Regular.ttf')],
      'bold':[('Arial Bold','arialbd.ttf'),('Segoe UI Bold','segoeuib.ttf'),('Calibri Bold','calibrib.ttf'),
              ('Liberation Sans Bold','LiberationSans-Bold.ttf'),('DejaVu Sans Bold','DejaVuSans-Bold.ttf'),('Lato Bold','Lato-Bold.ttf')],
      'italic':[('Arial Italic','ariali.ttf'),('Liberation Sans Italic','LiberationSans-Italic.ttf'),('DejaVu Sans Italic','DejaVuSans-Oblique.ttf'),('Lato Italic','Lato-Italic.ttf')],
      'serif':[('Times New Roman','times.ttf'),('Georgia','georgia.ttf'),('Liberation Serif','LiberationSerif-Regular.ttf'),('DejaVu Serif','DejaVuSerif.ttf')],
      'mono':[('Courier New','cour.ttf'),('Liberation Mono','LiberationMono-Regular.ttf'),('DejaVu Sans Mono','DejaVuSansMono.ttf')],
    }
    n=normalize_font(original)
    family = 'sans'
    if any(q in n for q in ('times','serif','georgia','cambria')): family = 'serif'
    elif any(q in n for q in ('cour','mono','consolas')): family = 'mono'
    elif any(q in n for q in ('bold','black','heavy','semibold')): family = 'bold'
    elif any(q in n for q in ('italic','oblique')): family = 'italic'
    priority=[family,'sans','bold','serif','mono','italic']
    available=[]
    for cat in priority:
        for label,filename in names[cat]:
            for directory in dirs:
                path=directory/filename
                if path.is_file() and str(path) not in [a[1] for a in available]:
                    available.append((label,str(path)))
    return available


def candidate_font(doc:fitz.Document, page:fitz.Page, span:dict, text:str=''):
    """Sample font widths from other spans to select a *safe writable* system font.
    Font outlines from PDF subset fonts are deliberately not reused. Their nonstandard
    glyph mapping can create unreadable characters when generating replacement text.
    """
    original=span.get('font','Helvetica')
    wanted=normalize_font(original)
    samples=[]
    for i in [page.number]+[n for n in range(min(len(doc),4)) if n!=page.number]:
        for b in doc[i].get_text('dict').get('blocks',[]):
            if b.get('type')!=0:continue
            for line in b.get('lines',[]):
                for s in line.get('spans',[]):
                    if normalize_font(s.get('font',''))==wanted and len(s.get('text','').strip())>=4:
                        samples.append(s)
                        if len(samples)>=14:break
                if len(samples)>=14:break
            if len(samples)>=14:break
        if len(samples)>=14:break
    options=font_options(original)
    if options:
        candidates=[]
        for j,(label,path) in enumerate(options):
            try:
                ft=fitz.Font(fontfile=path)
                # All required characters need actual glyphs, not tofu replacement.
                if text and any(not ft.has_glyph(ord(c)) for c in set(text) if c not in '\n\r\t'):
                    continue
                penalties=[]
                for s in samples:
                    actual=max(.01,float(s['bbox'][2])-float(s['bbox'][0]))
                    measured=ft.text_length(s['text'],fontsize=s['size'])
                    penalties.append(min(2,abs(measured-actual)/actual))
                diff=sum(penalties)/len(penalties) if penalties else .20
                base=''.join(c for c in original.lower() if c.isalpha())
                nm=''.join(c for c in label.lower() if c.isalpha())
                family_penalty=0 if any(c in base for c in ('arial','calibri','segoe','liberation','dejavu','lato')) and any(c in base for c in nm.split()) else 0.005*j
                candidates.append((diff+family_penalty,j,label,path,diff))
            except Exception:continue
        if candidates:
            _,_,label,path,error=min(candidates)
            return {'font':'StudioUnicode','path':path,'match':f'{label} (font sistem, sampling {len(samples)} cuplikan; selisih lebar sekitar {error*100:.1f}%). Font asli PDF: {original}.',
                    'confidence':'Perkiraan terukur' if samples else 'Font sistem', 'font_name':original, 'display_font':label}
    # Only use built-in Type1 when text can be reliably encoded using Latin-1.
    if all(ord(ch)<256 for ch in text):
        name=guessed_font(original)
        return {'font':name,'path':None,'match':f'{name} (font PDF standar; font asli: {original})',
                'confidence':'Pengganti', 'font_name':original,'display_font':'Helvetica'}
    raise HTTPException(422,'Karakter membutuhkan font Unicode. Instal Arial, Segoe UI, DejaVu Sans, atau Liberation Sans pada komputer ini.')


def normalized_text(value:str)->str:
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',value)).strip()

def get_fragments(page: fitz.Page) -> list[dict]:
    """Independent, position-preserving visual text runs.

    A PyMuPDF text *block* is not necessarily a paragraph. It can contain an
    entire multi-column table row. Editing that whole block destroys neighbours.
    We only offer edits to horizontal fragments inside one physical PDF line.
    """
    data = page.get_text('rawdict', sort=True)
    found = []
    for bi, block in enumerate(data['blocks']):
        if block.get('type') != 0: continue
        for li, line in enumerate(block.get('lines', [])):
            if abs(line.get('dir',(1,0))[1]) > .015 or line.get('wmode', 0):
                continue  # rotated / vertical text requires another reconstruction path
            for si, span in enumerate(line.get('spans', [])):
                chars = span.get('chars', [])
                if not chars: continue
                # Isolated table separators and abnormal spaces are their own units.
                groups=[]; group=[]; pending=[]
                for ci, char in enumerate(chars):
                    ch=char['c']
                    if ch.isspace():
                        pending.append(char)
                        continue
                    if group:
                        gap = (float(char['bbox'][0])-float(group[-1]['bbox'][2]))
                        long_gap = len(pending)>=2 or gap > float(span['size'])*1.45
                        punctuation = ch == ':' and bool(pending)
                        previous_colon = group[-1]['c'] == ':' and bool(pending)
                        if long_gap or punctuation or previous_colon:
                            groups.append(group);group=[]
                        else:
                            group.extend(pending)
                    group.append(char)
                    pending=[]
                if group: groups.append(group)
                for gi, run in enumerate(groups):
                    visible=[c for c in run if not c['c'].isspace()]
                    if not visible:continue
                    a=min(float(c['bbox'][0]) for c in visible)
                    b=min(float(c['bbox'][1]) for c in visible)
                    c=max(float(k['bbox'][2]) for k in visible)
                    d=max(float(k['bbox'][3]) for k in visible)
                    fragment=''.join(k['c'] for k in run).strip()
                    if not fragment:continue
                    spec=dict(span)
                    spec['text']=fragment
                    found.append({'id':f's{bi}_{li}_{si}_{gi}', 'text':fragment,
                       'bbox':[round(a,2),round(b,2),round(c,2),round(d,2)],
                       'origin':list(visible[0].get('origin',span.get('origin',(a,d)))),
                       'span':spec, 'line':(bi,li), 'size':float(span['size'])})
    return found


def placed_images(page:fitz.Page)->list[dict]:
    """Actual painted raster image occurrences, not page-background snapshots."""
    result=[]
    for info in page.get_image_info(xrefs=True):
        try:
            rect=fitz.Rect(info['bbox'])
            if rect.is_empty or rect.is_infinite:continue
            if info.get('width',0)<=1 or info.get('height',0)<=1:continue
            # Pure 1px masks and non-visible placements are not editable photos.
            if rect.get_area()<9:continue
            result.append({'id':f'im{len(result)}','bbox':[round(float(x),2) for x in rect],
                           'xref':int(info.get('xref',0)), 'pixelWidth':int(info['width']),
                           'pixelHeight':int(info['height'])})
        except (ValueError,TypeError,KeyError):continue
    return result


def image_occurrences(doc:fitz.Document,xref:int)->int:
    return sum(1 for page in doc for info in page.get_image_info(xrefs=True) if info.get('xref')==xref)

@app.get('/api/page/{page}/blocks')
def get_blocks(page:int,x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock,get_doc(w.raw) as doc:
        if not 0<=page<len(doc):raise HTTPException(404,'Halaman tidak ditemukan.')
        pg=doc[page]; fragments=get_fragments(pg)
        images=placed_images(pg)
        blocks=[]
        font_cache={}
        for frag in fragments:
            span=frag['span'];x0,y0,x1,y1=frag['bbox']
            font_key=span.get('font','')
            if font_key not in font_cache: font_cache[font_key]=candidate_font(doc,pg,span)
            font=font_cache[font_key]
            color=int(span.get('color',0))
            right_border=pg.rect.width-20
            # Never allow newly typed text to reach a neighbouring table column.
            for other in fragments:
                if other is frag: continue
                ox0,oy0,ox1,oy1=other['bbox']
                if ox0>=x1-0.1 and oy0<y1-1 and oy1>y0+1:
                    right_border=min(right_border,ox0-3)
            for item in images:
                ix0,iy0,ix1,iy1=item['bbox']
                if ix0>=x1 and iy0<y1 and iy1>y0:
                    right_border=min(right_border,ix0-3)
            usable=max(x1-x0,min(right_border-x0,pg.rect.width-x0-8))
            blocks.append({'id':frag['id'],'bbox':frag['bbox'],'text':frag['text'],
                'size':round(frag['size'],2),'color':f'#{color&0xffffff:06x}',
                'font':span.get('font',''), 'fontConfidence':font['confidence'],
                'fontMatch':font['match'],'displayFont':font['display_font'],
                'suggestedWidth':round(usable,2),'lineCount':1})
        return {'page':page,'width':pg.rect.width,'height':pg.rect.height,
                'blocks':blocks,'images':images}

class TextEdit(BaseModel):
    page:int
    block:str
    text:str=Field(max_length=20000)
    font_size:float=Field(ge=5,le=72)
    width:float=Field(ge=5,le=1500)
    color:str=Field(pattern=r'^#[0-9a-fA-F]{6}$')
    font_override:Literal['original','helv','hebo','heit','tiro','tibo','cour','cobo']='original'

@app.post('/api/text/edit')
def edit_text(body:TextEdit,x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock,get_doc(w.raw) as original:
        if not 0<=body.page<len(original):raise HTTPException(422,'Halaman tidak ditemukan.')
        src=original[body.page];fragments=get_fragments(src)
        frag=next((f for f in fragments if f['id']==body.block),None)
        if frag is None:raise HTTPException(422,'Area teks telah berubah. Klik teks lagi.')
        span=frag['span'];left,top,right,bottom=frag['bbox']
        # A multiline edit is not allowed to silently push neighbouring PDF rows.
        if '\n' in body.text or '\r' in body.text:
            raise HTTPException(422,'Area ini satu baris. Tekan teks pada baris lain secara terpisah agar tata letak tidak berubah.')
        font=candidate_font(original,src,span,body.text) if body.font_override=='original' else None
        safe_width=src.rect.width-left-8
        neighbors=[]
        for f in fragments:
            if f is frag:continue
            fx0,fy0,fx1,fy1=f['bbox']
            if fx0>=right-.1 and fy0<bottom-1 and fy1>top+1:
                neighbors.append(fx0)
        for im in placed_images(src):
            ix0,iy0,ix1,iy1=im['bbox']
            if ix0>=right and iy0<bottom and iy1>top: neighbors.append(ix0)
        if neighbors:safe_width=min(safe_width,min(neighbors)-left-3)
        width=min(body.width,safe_width)
        if width<right-left-.5:
            raise HTTPException(422,'Area PDF terlalu rapat dengan elemen berikutnya untuk diedit dengan aman.')
        rgb=tuple(int(body.color[i:i+2],16)/255 for i in (1,3,5))
        fontname='StudioUnicode' if font and font.get('path') else (font['font'] if font else body.font_override)
        if body.text.strip():
            try:
                f=fitz.Font(fontfile=font['path']) if font and font.get('path') else fitz.Font(fontname=fontname)
                extent=f.text_length(body.text,fontsize=body.font_size)
            except Exception as e:raise HTTPException(422,f'Font tidak bisa digunakan: {str(e)[:120]}')
            if extent>width+.15:
                raise HTTPException(422,f'Teks baru membutuhkan {extent:.1f} pt, hanya tersedia {width:.1f} pt sebelum elemen lain. Kurangi teks atau ukuran font.')
        work=get_doc(w.raw)
        try:
            pg=work[body.page]
            # A very tight glyph-shaped rectangle only touches this fragment.
            # Redacting a whole PyMuPDF block/line destroyed colons & other cells.
            rect=fitz.Rect(left+.10, top+.25, right-.10, bottom-.25)
            if rect.is_empty:raise HTTPException(422,'Area teks tidak valid.')
            pg.add_redact_annot(rect,fill=False,cross_out=False)
            pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                text=fitz.PDF_REDACT_TEXT_REMOVE)
            if body.text.strip():
                if font and font.get('path'):
                    pg.insert_font(fontname=fontname,fontfile=font['path'])
                pg.insert_text(fitz.Point(frag['origin']),body.text,fontname=fontname,
                               fontsize=body.font_size,color=rgb,overlay=True)
            raw=save_pdf(work)
            with get_doc(raw) as check:
                after=get_fragments(check[body.page])
                newtext=normalized_text(body.text)
                if newtext and not any(normalized_text(f['text'])==newtext and
                  abs(f['bbox'][0]-left)<3 and abs(f['bbox'][1]-top)<max(6,body.font_size*.6) for f in after):
                    raise HTTPException(422,'Font tidak menghasilkan teks yang benar. Perubahan dibatalkan.')
                # Keep all other visual fragments intact, including punctuation.
                remaining=fragments.copy();remaining.remove(frag)
                for old in remaining:
                    ox,oy,_,_=old['bbox']
                    if not any(f['text']==old['text'] and
                        abs(f['bbox'][0]-ox)<1.2 and abs(f['bbox'][1]-oy)<1.2 for f in after):
                        raise HTTPException(422,'Teks di dekatnya ikut berubah. Penyimpanan dibatalkan untuk melindungi layout.')
            w.commit(raw)
            return {'status':'ok','fontMatch':font['match'] if font else body.font_override,
                    'fontConfidence':font['confidence'] if font else 'Dipilih pengguna',**summary(w)}
        finally:work.close()

class ImageChange(BaseModel):
    page:int
    image:str


def find_image(doc:fitz.Document,page_no:int,image_id:str):
    if not 0<=page_no<len(doc):raise HTTPException(422,'Halaman tidak ditemukan.')
    selected=next((im for im in placed_images(doc[page_no]) if im['id']==image_id),None)
    if not selected:raise HTTPException(422,'Gambar berubah. Klik lagi gambar pada halaman.')
    return selected


def remove_image_object(doc:fitz.Document,page_no:int,selected:dict):
    """Delete uniquely referenced raster XObjects without touching other images.
    Shared/inline images use clipping redaction, but overlapping image layers are
    refused because they cannot be removed independently by that method.
    """
    pg=doc[page_no];xref=selected['xref']
    if xref>0 and image_occurrences(doc,xref)==1:
        pg.delete_image(xref)
        return 'xref'
    rect=fitz.Rect(selected['bbox'])
    for im in placed_images(pg):
        if im['id']==selected['id']:continue
        if fitz.Rect(im['bbox']).intersects(rect):
            raise HTTPException(422,'Gambar ini berada di atas gambar lain. Penghapusan terpisah tidak aman, jadi PDF tidak diubah.')
    pg.add_redact_annot(rect,fill=False,cross_out=False)
    pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE,
                        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                        text=fitz.PDF_REDACT_TEXT_NONE)
    return 'clipped'

@app.post('/api/image/delete')
def delete_image(body:ImageChange,x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock,get_doc(w.raw) as work:
        selected=find_image(work,body.page,body.image)
        remove_image_object(work,body.page,selected)
        w.commit(save_pdf(work))
        return {'status':'ok',**summary(w)}

@app.post('/api/image/replace')
async def replace_image(page:int,image:str,file:UploadFile=File(...),x_session:str|None=Header(None)):
    w=workspace(x_session)
    content=await file.read(16*1024*1024+1)
    if len(content)>16*1024*1024:raise HTTPException(413,'Gambar maksimal 16 MB.')
    if Path(file.filename or '').suffix.lower() not in ('.jpg','.jpeg','.png'):
        raise HTTPException(422,'Gunakan gambar PNG atau JPG.')
    try:
        pix=fitz.Pixmap(content)
        if pix.width>12000 or pix.height>12000 or pix.width<2 or pix.height<2:
            raise HTTPException(422,'Resolusi gambar tidak valid.')
    except HTTPException:raise
    except Exception:raise HTTPException(422,'Format gambar tidak valid. Gunakan PNG atau JPG.')
    with w.lock,get_doc(w.raw) as work:
        selected=find_image(work,page,image)
        remove_image_object(work,page,selected)
        # Preserve original occupied rectangle, do not alter text or layout.
        pg=work[page];rect=fitz.Rect(selected['bbox'])
        try:pg.insert_image(rect,stream=content,keep_proportion=False,overlay=True)
        except Exception as e:raise HTTPException(422,f'Gambar pengganti tidak bisa ditambahkan: {str(e)[:150]}')
        w.commit(save_pdf(work))
        return {'status':'ok',**summary(w)}

@app.post('/api/history/{direction}')
def history(direction:Literal['undo','redo'],x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock:
        dest=w.pointer+(-1 if direction=='undo' else 1)
        if dest<0 or dest>=len(w.revisions):raise HTTPException(422,'Riwayat tidak tersedia.')
        w.pointer=dest
        return summary(w)

@app.get('/api/export')
def export(pages:str|None=None,x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock:
        if not pages:
            result=w.raw
            name=w.name.removesuffix('.pdf')+'-edited.pdf'
        else:
            with get_doc(w.raw) as d:
                try:indices=[int(i) for i in pages.split(',')]
                except ValueError:raise HTTPException(422,'Daftar halaman tidak valid.')
                if not indices or any(i<0 or i>=len(d) for i in indices):
                    raise HTTPException(422,'Nomor halaman tidak valid.')
                subset=fitz.open()
                for i in indices:subset.insert_pdf(d,from_page=i,to_page=i,annots=True)
                result=save_pdf(subset);subset.close()
                name=w.name.removesuffix('.pdf')+'-selected.pdf'
        return StreamingResponse(io.BytesIO(result),media_type='application/pdf',headers={
            'Content-Disposition':f'attachment; filename="{re.sub(r"[^a-zA-Z0-9_.-]","_",name)}"',
            'Cache-Control':'no-store'})

@app.delete('/api/document')
def discard(x_session:str|None=Header(None)):
    w=workspace(x_session)
    with w.lock:
        w.pointer=-1;w.revisions=[]
    return {'status':'discarded'}

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

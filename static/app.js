(() => {
  'use strict';
  const $ = s => document.getElementById(s);
  const state={
    session:sessionStorage.getItem('pdf-studio-session') || Array.from(crypto.getRandomValues(new Uint8Array(16))).map(n=>n.toString(16).padStart(2,'0')).join(''),
    doc:null,page:0,view:'edit',zoom:1,blocks:[],images:[],selectedImage:null,selected:null,selectedPages:new Set(),busy:false,inline:null,
    thumbUrls:new Map(),currentPreview:null,openId:0,observer:null,
  };
  sessionStorage.setItem('pdf-studio-session',state.session);
  const headers={'X-Session':state.session};
  let toastTimer;
  const toast=(message,error=false)=>{const e=$('toast');e.textContent=message;e.classList.toggle('error',error);e.classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>e.classList.remove('visible'),5000);};
  const busy=(on,msg='Memproses PDF…')=>{state.busy=on;$('busyOverlay').classList.toggle('hidden',!on);$('busyMessage').textContent=msg;if(!on){document.querySelectorAll('.requires-doc').forEach(b=>b.disabled=!hasDoc());$('undoBtn').disabled=!state.doc?.undo;$('redoBtn').disabled=!state.doc?.redo;}};
  async function api(path,opt={}){
    const reply=await fetch('/api'+path,{...opt,headers:{...headers,...opt.headers}});
    if(!reply.ok){let d;try{d=await reply.json();}catch{};throw Error(typeof d?.detail==='string'?d.detail:`Terjadi kesalahan (${reply.status}).`);}
    return reply;
  }
  const post=async(path,body)=> (await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  const safe=async(fn)=>{if(state.busy)return;try{await fn();}catch(e){console.error(e);toast(e.message||'Gagal memproses.',true);}finally{busy(false);}};
  const hasDoc=()=>!!state.doc?.count;
  const normalIndex=n=>Math.max(0,Math.min(n,state.doc.count-1));
  function clearThumbnails(){for(const u of state.thumbUrls.values())URL.revokeObjectURL(u);state.thumbUrls.clear();if(state.observer){state.observer.disconnect();state.observer=null;}}
  function hydrate(doc,expectedPage=state.page){state.doc=doc;state.page=doc.count?Math.max(0,Math.min(expectedPage,doc.count-1)):0;state.inline=null;state.selected=null;state.selectedImage=null;state.blocks=[];state.images=[];state.selectedPages.clear();clearThumbnails();renderShell();}
  function renderShell(){
    const have=hasDoc();
    $('welcome').classList.toggle('hidden',have);$('editWorkspace').classList.toggle('hidden',!have||!['edit','images','preview'].includes(state.view));$('organizeWorkspace').classList.toggle('hidden',!have||state.view!=='organize');
    document.querySelectorAll('.requires-doc').forEach(b=>b.disabled=!have||state.busy);
    $('fileName').textContent=have?state.doc.name:'Belum ada dokumen';$('pageCountMini').textContent=state.doc?.count||0;
    $('statusPages').textContent=have?`${state.doc.count} halaman`:'PDF Studio v2.2';
    $('undoBtn').disabled=!have||!state.doc.undo;$('redoBtn').disabled=!have||!state.doc.redo;
    $('editModeBtn').classList.toggle('active',['edit','images'].includes(state.view));$('organizeModeBtn').classList.toggle('active',state.view==='organize');
    $('workspaceMode').textContent=state.view==='edit'?'EDIT TEKS':state.view==='images'?'EDIT GAMBAR':state.view==='preview'?'PREVIEW PDF':'ORGANIZE PAGES';
    $('toolbarNote').textContent=state.view==='edit'?'Edit potongan teks tanpa menggeser kolom lainnya.':state.view==='images'?'Klik objek gambar untuk mengganti atau menghapusnya.':state.view==='preview'?'Viewer PDF utuh tanpa area editor.':'Seret halaman, rotasi, atau gabungkan beberapa file.';
    $('emptyInspector').classList.toggle('hidden',!have||!!state.selected||state.view==='organize');
    $('textInspector').classList.toggle('hidden',!state.selected||state.view!=='edit');
    $('organizeInspector').classList.toggle('hidden',!have||state.view!=='organize');
    $('zoomLabel').textContent=Math.round(state.zoom*100)+'%';
    $('previewModeBtn').classList.toggle('active',state.view==='preview');
    $('textModeBtn').classList.toggle('active',state.view==='edit');
    $('imageModeBtn').classList.toggle('active',state.view==='images');
    $('autosaveStatus').classList.toggle('hidden',state.view!=='edit');
    if(have){renderSidebar(); if(state.view==='organize')renderOrganize(); else renderPage();}
    else $('pageList').innerHTML='<div class="side-empty">Buka PDF untuk melihat halaman.</div>';
  }
  async function imageBlob(index,scale){const r=await api(`/page/${index}/image?scale=${scale}`);return r.blob();}
  async function thumbImage(img,index){
    if(!img?.isConnected||!state.doc)return;
    const name=`${index}`;
    try{
      if(!state.thumbUrls.has(name)){
        const blob=await imageBlob(index,.55);if(!hasDoc())return;
        const url=URL.createObjectURL(blob);state.thumbUrls.set(name,url);
      }
      if(img.isConnected)img.src=state.thumbUrls.get(name);
    }catch(e){img.alt='Preview gagal dimuat';}
  }
  function lazyThumbs(root){
    if(!state.observer){
      state.observer=new IntersectionObserver(entries=>{
        for(const en of entries){if(en.isIntersecting){state.observer.unobserve(en.target);thumbImage(en.target,Number(en.target.dataset.page));}}
      },{rootMargin:'250px'});
    }
    root.querySelectorAll('img[data-page]').forEach(img=>state.observer.observe(img));
  }
  function renderSidebar(){
    const list=$('pageList');list.replaceChildren();
    state.doc.pages.forEach((p,i)=>{
      const btn=document.createElement('button');btn.className='page-card'+(state.page===i?' active':'');btn.type='button';
      const img=document.createElement('img');img.className='page-image';img.dataset.page=String(i);img.alt=`Halaman ${i+1}`;img.loading='lazy';
      const l=document.createElement('div');l.className='page-card-label';
      const a=document.createElement('span');a.textContent=`Halaman ${i+1}`;
      const b=document.createElement('span');b.textContent=String(i+1).padStart(2,'0');l.append(a,b);btn.append(img,l);
      btn.addEventListener('click',async()=>{if(state.inline){const ok=await finishInline();if(!ok)return;}state.page=i;state.selected=null;state.view='edit';renderShell();});
      list.appendChild(btn);
    });
    lazyThumbs(list);
  }
  function setSaveStatus(message, kind='ready'){
    const el=$('autosaveStatus');el.textContent=message;el.dataset.status=kind;
  }
  function activateImage(item){
    state.selectedImage=item;
    const layer=$('textOverlay');
    layer.querySelectorAll('.image-actions').forEach(x=>x.remove());
    layer.querySelectorAll('.image-target').forEach(x=>x.classList.toggle('picked',x.dataset.image===item.id));
    const panel=document.createElement('div');panel.className='image-actions';
    const info=state.doc.pages[state.page],scale=1.2*state.zoom;
    const [x0,y0,x1,y1]=item.bbox;
    panel.style.left=Math.max(2,Math.min(x0/info.width*100,80))+'%';
    panel.style.top=Math.max(0,(y0-45/scale)/info.height*100)+'%';
    const label=document.createElement('span');label.textContent=`▧ Gambar ${item.pixelWidth}×${item.pixelHeight}`;
    const replace=document.createElement('button');replace.type='button';replace.textContent='↻ Ganti';replace.addEventListener('click',()=>{$('imageInput').value='';$('imageInput').click();});
    const remove=document.createElement('button');remove.type='button';remove.className='image-delete';remove.textContent='⌫ Hapus';remove.addEventListener('click',()=>removeSelectedImage());
    panel.append(label,replace,remove);layer.append(panel);
  }
  async function removeSelectedImage(){
    const item=state.selectedImage;if(!item)return;
    if(!window.confirm('Hapus gambar terpilih dari halaman PDF ini?'))return;
    await safe(async()=>{
      busy(true,'Menghapus gambar asli PDF…');
      const result=await post('/image/delete',{page:state.page,image:item.id});
      hydrate(result,state.page);toast('Gambar dihapus. Teks dan elemen lainnya dipertahankan.');
    });
  }
  async function replaceSelectedImage(file){
    const item=state.selectedImage;if(!item||!file)return;
    await safe(async()=>{
      busy(true,'Mengganti gambar PDF…');
      const fd=new FormData();fd.append('file',file);
      const result=await (await api('/image/replace?page='+state.page+'&image='+encodeURIComponent(item.id),{method:'POST',body:fd})).json();
      hydrate(result,state.page);toast('Gambar berhasil diganti pada posisi aslinya.');
    });
  }
  function renderOverlay(){
    const el=$('textOverlay');
    el.querySelectorAll('.text-block,.image-target,.image-actions').forEach(x=>x.remove());
    const info=state.doc.pages[state.page];
    if(state.view==='edit')state.blocks.forEach(b=>{
      const hit=document.createElement('button');hit.type='button';hit.className='text-block';
      const [x0,y0,x1,y1]=b.bbox;
      hit.style.left=x0/info.width*100+'%';hit.style.top=y0/info.height*100+'%';
      hit.style.width=Math.max(8,x1-x0)/info.width*100+'%';hit.style.height=Math.max(8,y1-y0)/info.height*100+'%';
      hit.title='Edit teks tepat di lokasi ini: '+b.text.slice(0,80);hit.setAttribute('aria-label','Edit teks: '+b.text.slice(0,80));
      hit.addEventListener('click',event=>activateInline(b,event));el.append(hit);
    });
    if(state.view==='images')state.images.forEach(item=>{
      const hit=document.createElement('button');hit.type='button';hit.className='image-target';hit.dataset.image=item.id;
      const [x0,y0,x1,y1]=item.bbox;
      hit.style.left=x0/info.width*100+'%';hit.style.top=y0/info.height*100+'%';
      hit.style.width=(x1-x0)/info.width*100+'%';hit.style.height=(y1-y0)/info.height*100+'%';
      hit.title=`Gambar ${item.pixelWidth} x ${item.pixelHeight} pixel. Klik untuk mengganti atau menghapus.`;
      hit.setAttribute('aria-label','Pilih gambar untuk diganti atau dihapus');
      hit.addEventListener('click',()=>activateImage(item));el.append(hit);
    });
    el.style.pointerEvents=['edit','images'].includes(state.view)?'auto':'none';
    $('pageCaption').textContent=state.view==='edit'
      ?(state.blocks.length?'Klik teks pada halaman. Bagian lain di baris yang sama tidak ikut berubah.':'Tidak ditemukan teks digital. PDF scan membutuhkan OCR.')
      :state.view==='images'?(state.images.length?`${state.images.length} objek gambar raster terdeteksi. Klik untuk Ganti atau Hapus.`:'Tidak ditemukan objek gambar raster terpisah. Logo mungkin berupa vektor atau menyatu dengan background.')
      :'Tampilan asli PDF tanpa area editor.';
    $('paperLabel').textContent=`PAGE ${String(state.page+1).padStart(2,'0')} / ${String(state.doc.count).padStart(2,'0')}`;
    $('statusLine').textContent=`${state.blocks.length} potongan teks · ${state.images.length} objek raster · Halaman ${state.page+1}`;
  }
  async function renderPage(){
    if(!hasDoc()||state.view==='organize')return;
    const requestId=++state.openId, page=state.page, dim=state.doc.pages[page], scale=1.2*state.zoom;
    $('pageHolder').style.width=dim.width*scale+'px';$('pageHolder').style.height=dim.height*scale+'px';
    if(!state.inline)$('textOverlay').replaceChildren();
    const current=state.currentPreview;state.currentPreview=null;
    try{
      const [blob,res]=await Promise.all([imageBlob(page,Math.min(2.2,scale)),api(`/page/${page}/blocks`)]);
      const blocks=await res.json();if(requestId!==state.openId||page!==state.page)return;
      state.currentPreview=URL.createObjectURL(blob);$('pageImage').src=state.currentPreview;
      if(current)URL.revokeObjectURL(current);
      state.blocks=blocks.blocks;state.images=blocks.images||[];state.selectedImage=null;renderOverlay();
    }catch(e){toast(e.message||'Halaman gagal dirender.',true);}
  }
  const inlineText=editor=>editor.innerText.replace(/\r/g,'').replace(/\n$/,'');
  let editTimer=null;
  function autosaveLater(){
    clearTimeout(editTimer);
    if(!state.inline)return;
    setSaveStatus('● Belum disimpan','dirty');
    if(inlineText(state.inline.el).trim())editTimer=setTimeout(()=>commitInline(false),1250);
  }
  function backgroundAt(block){
    // Sample a pixel just left of the original glyphs so the editable patch
    // matches colored headings and other non-white PDF backgrounds.
    const img=$('pageImage'),dim=state.doc.pages[state.page];
    if(!img.complete||!img.naturalWidth)return '#ffffff';
    try{
      const c=document.createElement('canvas');c.width=1;c.height=1;
      const ctx=c.getContext('2d',{willReadFrequently:true});
      const sx=Math.max(0,Math.min(img.naturalWidth-1,Math.round((block.bbox[0]-4)*img.naturalWidth/dim.width)));
      const sy=Math.max(0,Math.min(img.naturalHeight-1,Math.round((block.bbox[1]+block.bbox[3])/2*img.naturalHeight/dim.height)));
      ctx.drawImage(img,sx,sy,1,1,0,0,1,1);
      const rgba=ctx.getImageData(0,0,1,1).data;
      return `rgb(${rgba[0]},${rgba[1]},${rgba[2]})`;
    }catch{return '#ffffff';}
  }
  async function activateInline(block,clickEvent=null){
    if(state.view!=='edit'||!hasDoc())return;
    if(state.inline){
      if(state.inline.block.id===block.id){state.inline.el.focus();return;}
      const ok=await finishInline();if(!ok)return;
    }
    const dim=state.doc.pages[state.page],scale=1.2*state.zoom;
    const [left,top,right,bottom]=block.bbox;
    const editor=document.createElement('div');editor.className='inline-editor';
    editor.setAttribute('role','textbox');editor.setAttribute('aria-label','Edit paragraf PDF langsung');
    editor.setAttribute('contenteditable','plaintext-only');editor.setAttribute('spellcheck','false');
    editor.style.left=left/dim.width*100+'%';editor.style.top=(top-1)/dim.height*100+'%';
    editor.style.width=Math.min(block.suggestedWidth,dim.width-left-12)*scale+'px';
    editor.style.minHeight=Math.max((bottom-top-1)*scale,(block.size*1.2*scale))+'px';
    editor.style.fontSize=Math.max(7,block.size*scale)+'px';
    editor.style.color=block.color;
    editor.style.backgroundColor=backgroundAt(block);
    editor.style.fontWeight=/bold|heavy|black/i.test(block.font)?'700':'400';
    editor.style.fontStyle=/italic|oblique/i.test(block.font)?'italic':'normal';
    editor.style.fontFamily=`"${(block.displayFont||'Arial').replaceAll('"','')}",Arial,sans-serif`;
    editor.textContent=block.text;
    const inline={el:editor,block,original:block.text,lastSaved:block.text,page:state.page,saving:false,closed:false,failed:false};
    state.inline=inline;$('textOverlay').append(editor);
    editor.addEventListener('input',autosaveLater);
    editor.addEventListener('paste',e=>{e.preventDefault();const s=e.clipboardData?.getData('text/plain')||'';document.execCommand('insertText',false,s);});
    editor.addEventListener('keydown',e=>{
      if(e.key==='Escape'){e.preventDefault();cancelInline();}
      if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();finishInline();}
      e.stopPropagation();
    });
    editor.addEventListener('blur',()=>{if(state.inline===inline)setTimeout(()=>{if(state.inline===inline&&document.activeElement!==editor)finishInline();},100);});
    editor.focus();
    const sel=window.getSelection(),range=document.createRange();
    let caret=null;
    if(clickEvent&&document.caretPositionFromPoint)caret=document.caretPositionFromPoint(clickEvent.clientX,clickEvent.clientY);
    else if(clickEvent&&document.caretRangeFromPoint){const r=document.caretRangeFromPoint(clickEvent.clientX,clickEvent.clientY);if(r)caret={offsetNode:r.startContainer,offset:r.startOffset};}
    if(caret&&editor.contains(caret.offsetNode))range.setStart(caret.offsetNode,caret.offset);
    else {range.selectNodeContents(editor);range.collapse(false);}
    range.collapse(true);sel.removeAllRanges();sel.addRange(range);
    setSaveStatus('✎ Mengedit langsung','editing');
  }
  function cancelInline(){
    clearTimeout(editTimer);
    const ed=state.inline;if(!ed)return;
    if(ed.saving){toast('Tunggu proses simpan selesai sebelum membatalkan.',true);return;}
    state.inline=null;ed.el.remove();setSaveStatus('✓ Siap diedit');
    renderPage();
  }
  async function commitInline(close=false){
    const ed=state.inline;if(!ed)return true;
    clearTimeout(editTimer);
    if(ed.saving){if(close)ed.closed=true;return false;}
    const value=inlineText(ed.el);
    if(value===ed.lastSaved){if(close){state.inline=null;ed.el.remove();setSaveStatus('✓ Tersimpan','saved');renderPage();}return true;}
    if(!value.trim()&&!close)return false; // Never erase the source while typing a replacement.
    ed.saving=true;ed.failed=false;setSaveStatus('↻ Menyimpan ke PDF…','saving');
    try{
      const result=await post('/text/edit',{page:ed.page,block:ed.block.id,text:value,font_size:ed.block.size,
                    color:ed.block.color,width:ed.block.suggestedWidth,font_override:'original'});
      state.doc=result;ed.lastSaved=value;
      clearThumbnails();renderSidebar();
      $('undoBtn').disabled=!result.undo;$('redoBtn').disabled=!result.redo;
      const res=await api(`/page/${ed.page}/blocks`);const updated=(await res.json()).blocks;
      state.blocks=updated;
      // Text reconstruction changes PDF block IDs. Bind to the newly generated block.
      const left=ed.block.bbox[0],top=ed.block.bbox[1];
      const matches=updated.filter(x=>Math.abs(x.bbox[0]-left)<18&&Math.abs(x.bbox[1]-top)<28);
      const newBlock=matches.sort((a,b)=>Math.abs(a.bbox[0]-left)+Math.abs(a.bbox[1]-top)-Math.abs(b.bbox[0]-left)-Math.abs(b.bbox[1]-top))[0];
      if(newBlock)ed.block=newBlock;
      ed.saving=false;
      setSaveStatus('✓ Disimpan ke PDF','saved');
      if(close||ed.closed){
        if(inlineText(ed.el)!==ed.lastSaved){ed.closed=true;return commitInline(true);}
        state.inline=null;ed.el.remove();renderPage();
      } else if(inlineText(ed.el)!==ed.lastSaved){autosaveLater();}
      return true;
    }catch(e){
      ed.saving=false;ed.closed=false;ed.failed=true;
      setSaveStatus('! Gagal menyimpan','error');toast('Teks belum tersimpan: '+(e.message||'Kesalahan tidak diketahui'),true);
      ed.el.classList.add('inline-error');ed.el.focus();return false;
    }
  }
  async function finishInline(){
    if(!state.inline)return true;
    const ed=state.inline;
    if(ed.saving){
      ed.closed=true;
      while(ed.saving)await new Promise(resolve=>setTimeout(resolve,80));
      if(ed.failed)return false;
      if(state.inline!==ed)return true;
    }
    return commitInline(true);
  }
  function renderOrganize(){
    const grid=$('organizeGrid');grid.replaceChildren();
    state.doc.pages.forEach((p,i)=>{
      const card=document.createElement('article');card.className='grid-card'+(state.selectedPages.has(i)?' selected':'');card.draggable=true;card.dataset.index=String(i);
      const img=document.createElement('img');img.dataset.page=String(i);img.alt=`Preview halaman ${i+1}`;
      const foot=document.createElement('div');foot.className='grid-card-foot';
      const label=document.createElement('strong');label.textContent=`Halaman ${String(i+1).padStart(2,'0')}`;
      const check=document.createElement('input');check.type='checkbox';check.checked=state.selectedPages.has(i);check.setAttribute('aria-label',`Pilih halaman ${i+1}`);
      const setCheck=v=>{if(v)state.selectedPages.add(i);else state.selectedPages.delete(i);card.classList.toggle('selected',v);};
      check.addEventListener('change',()=>setCheck(check.checked));card.addEventListener('click',e=>{if(e.target===check)return;setCheck(!check.checked);check.checked=state.selectedPages.has(i);});
      card.addEventListener('dragstart',e=>{e.dataTransfer.setData('text/plain',String(i));e.dataTransfer.effectAllowed='move';card.classList.add('dragging');});
      card.addEventListener('dragend',()=>card.classList.remove('dragging'));
      card.addEventListener('dragover',e=>{e.preventDefault();e.dataTransfer.dropEffect='move';card.classList.add('dragover');});
      card.addEventListener('dragleave',()=>card.classList.remove('dragover'));
      card.addEventListener('drop',e=>{e.preventDefault();card.classList.remove('dragover');const from=Number(e.dataTransfer.getData('text/plain'));if(!Number.isInteger(from)||from===i)return;const order=state.doc.pages.map(p=>p.index);order.splice(from,1);order.splice(i,0,from);performReorder(order,i);});
      foot.append(label,check);card.append(img,foot);grid.append(card);
    });
    lazyThumbs(grid);
  }
  async function performReorder(order,target){
    await safe(async()=>{busy(true,'Mengatur urutan halaman…');const result=await post('/pages/reorder',{order});hydrate(result,target);toast('Urutan halaman diperbarui.');});
  }
  async function applyPageAction(action,index=state.page){
    await safe(async()=>{
      busy(true,'Mengedit susunan halaman…');
      const d=await post('/pages/action',{action,page:index});
      const next=(action==='delete'&&index>=d.count)?d.count-1:action==='duplicate'||action==='blank'?index+1:action==='move_up'?index-1:action==='move_down'?index+1:index;
      hydrate(d,Math.max(0,next));toast('Halaman berhasil diperbarui.');
    });
  }
  async function multiplePageActions(action){
    const chosen=[...state.selectedPages].sort((a,b)=>(action==='delete'||action==='duplicate')?b-a:a-b);
    if(!chosen.length)return toast('Pilih halaman terlebih dahulu.',true);
    if(action==='delete'&&chosen.length===state.doc.count)return toast('Tidak boleh menghapus seluruh halaman.',true);
    await safe(async()=>{
      busy(true,`Memproses ${chosen.length} halaman…`);
      let d;
      for(const i of chosen)d=await post('/pages/action',{action,page:i});
      hydrate(d,Math.min(chosen[0],d.count-1));toast(`${chosen.length} halaman selesai diproses.`);
    });
  }
  async function openFiles(files,merge=false){
    if(!files?.length)return;
    if(state.inline&&!(await finishInline()))return;
    await safe(async()=>{
      busy(true,merge?'Menggabungkan beberapa PDF…':'Membaca PDF…');
      const data=new FormData();
      if(merge){for(const file of files)data.append('files',file);}else data.append('file',files[0]);
      const d=await (await api(merge?'/merge':'/open',{method:'POST',body:data})).json();
      state.view='edit';hydrate(d,merge?state.page:0);toast(merge?`${d.added} halaman baru berhasil digabungkan.`:`${d.count} halaman berhasil dibuka.`);
    });
  }
  async function openDemo(){
    await safe(async()=>{busy(true,'Membuka dokumen contoh…');const resp=await fetch('/static/example.pdf');if(!resp.ok)throw Error('File demo tidak ditemukan.');const blob=await resp.blob();const data=new File([blob],'contoh-pdf-studio.pdf',{type:'application/pdf'});
      const fd=new FormData();fd.append('file',data);const d=await (await api('/open',{method:'POST',body:fd})).json();hydrate(d,0);toast('Dokumen contoh siap diedit. Klik paragraf yang diinginkan.');});
  }
  async function download(pages=null){
    if(state.inline&&!(await finishInline()))return;
    await safe(async()=>{
      busy(true,'Menyiapkan hasil PDF…');
      const suffix=pages?.length?'?pages='+pages.join(','):'';
      const response=await api('/export'+suffix);
      const blob=await response.blob();const url=URL.createObjectURL(blob);
      const a=document.createElement('a');a.href=url;
      const raw=state.doc.name.replace(/\.pdf$/i,'');a.download=raw+(pages?.length?'-selected':'-edited')+'.pdf';document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),5000);toast('PDF berhasil disiapkan untuk diunduh.');
    });
  }
  async function undoRedo(direction){if(state.inline&&!(await finishInline()))return;await safe(async()=>{busy(true,'Memulihkan versi PDF…');const d=await (await api('/history/'+direction,{method:'POST'})).json();hydrate(d);toast(direction==='undo'?'Perubahan dibatalkan.':'Perubahan diterapkan ulang.');});}
  async function setView(view){if(state.inline){const ok=await finishInline();if(!ok)return;}state.view=view;state.selected=null;renderShell();}
  function register(){
    const input=$('pdfInput'),mergeInput=$('mergeInput');
    for(const id of ['openBtn','welcomeOpenBtn'])$(id).addEventListener('click',()=>input.click());
    input.addEventListener('change',()=>{const files=[...input.files];input.value='';openFiles(files);});
    for(const id of ['mergeTopBtn','mergeSideBtn','organizeMergeBtn'])$(id).addEventListener('click',()=>mergeInput.click());
    mergeInput.addEventListener('change',()=>{const files=[...mergeInput.files];mergeInput.value='';openFiles(files,true);});
    $('demoBtn').addEventListener('click',openDemo);
    $('downloadBtn').addEventListener('click',()=>download());
    $('editModeBtn').addEventListener('click',()=>setView('edit'));
    $('organizeModeBtn').addEventListener('click',()=>setView('organize'));
    $('previewModeBtn').addEventListener('click',()=>setView(state.view==='preview'?'edit':'preview'));
    $('textModeBtn').addEventListener('click',()=>setView('edit'));
    $('imageModeBtn').addEventListener('click',()=>setView('images'));
    $('imageInput').addEventListener('change',()=>{const file=$('imageInput').files?.[0];$('imageInput').value='';replaceSelectedImage(file);});
    $('mergeToolbarBtn').addEventListener('click',()=>mergeInput.click());
    $('newPageToolbarBtn').addEventListener('click',()=>applyPageAction('blank'));
    // Inline editor autosaves, no inspector action required.
    
    
    
    $('zoomOut').addEventListener('click',async()=>{if(state.inline&&!(await finishInline()))return;state.zoom=Math.max(.5,state.zoom-.1);renderShell();});
    $('zoomIn').addEventListener('click',async()=>{if(state.inline&&!(await finishInline()))return;state.zoom=Math.min(2,state.zoom+.1);renderShell();});
    $('undoBtn').addEventListener('click',()=>undoRedo('undo'));$('redoBtn').addEventListener('click',()=>undoRedo('redo'));
    const actions={rotateBtn:'rotate',duplicateBtn:'duplicate',deletePageBtn:'delete',moveUpBtn:'move_up',moveDownBtn:'move_down',insertPageBtn:'blank',addBlankBtn:'blank',organizeBlankBtn:'blank'};
    Object.entries(actions).forEach(([id,a])=>$(id).addEventListener('click',()=>applyPageAction(a)));
    $('selectAllBtn').addEventListener('click',()=>{const all=state.selectedPages.size===state.doc.count;state.selectedPages=new Set(all?[]:state.doc.pages.map(p=>p.index));renderOrganize();});
    $('rotateSelectedBtn').addEventListener('click',()=>multiplePageActions('rotate'));
    $('duplicateSelectedBtn').addEventListener('click',()=>multiplePageActions('duplicate'));
    $('deleteSelectedBtn').addEventListener('click',()=>multiplePageActions('delete'));
    $('exportSelectedBtn').addEventListener('click',()=>{const arr=[...state.selectedPages].sort((a,b)=>a-b);if(!arr.length)return toast('Pilih halaman untuk diekspor.',true);download(arr);});
    document.addEventListener('keydown',e=>{if(document.activeElement?.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undoRedo(e.shiftKey?'redo':'undo');}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();undoRedo('redo');}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if(hasDoc())download();}
    });
    document.addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files'))e.preventDefault();});
    document.addEventListener('drop',e=>{if(e.dataTransfer?.files?.length){e.preventDefault();const pdf=[...e.dataTransfer.files].filter(f=>/\.pdf$/i.test(f.name));if(pdf.length)openFiles(pdf,hasDoc());}});
  }
  async function init(){register();try{const d=await(await api('/document')).json();state.doc=d.count?d:null;renderShell();}catch(e){toast(e.message,true);renderShell();}}
  init();
})();

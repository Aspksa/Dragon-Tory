let activeChatId=null;
let activeChatTitle="Новый чат";
let chatLoaded=false;
let currentRequestId=null;
let currentAbortController=null;
let chatSearchTimer=null;
const $=id=>document.getElementById(id);
const fmtBytes=n=>{if(n==null)return"—";const u=["Б","КБ","МБ","ГБ","ТБ"];let i=0,v=Number(n);while(v>=1024&&i<u.length-1){v/=1024;i++}return (i<2?v.toFixed(0):v.toFixed(1))+" "+u[i]};
function state(el,text,kind=""){el.textContent=text;el.className="value "+kind}
async function withBusyButton(id,busyText,action){
  const btn=$(id);if(!btn||btn.disabled)return;
  const original=btn.textContent;btn.disabled=true;btn.setAttribute("aria-busy","true");
  if(busyText)btn.textContent=busyText;
  try{return await action()}
  finally{btn.disabled=false;btn.removeAttribute("aria-busy");btn.textContent=original}
}
async function api(url,opts={}){const r=await fetch(url,{cache:"no-store",headers:{"Content-Type":"application/json",...(opts.headers||{})},...opts});let d;try{d=await r.json()}catch{d={detail:await r.text()}}if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:JSON.stringify(d.detail||d));return d}
function showView(view,source=null){document.body.classList.toggle("home-mode",view==="home");document.querySelectorAll(".nav").forEach(x=>x.classList.remove("active"));document.querySelectorAll(".view").forEach(x=>x.classList.remove("active"));document.querySelectorAll(".bottom-update").forEach(x=>x.classList.remove("active"));if(source)source.classList.add("active");if(view==="cloud"&&source&&source.dataset.view==="cloud"){cloudTrashMode=false;cloudFavoritesOnly=false}$(view).classList.add("active");if(view==="home"){loadHomeDashboard();refreshDiag()}if(view==="chat")ensureChatReady();if(view==="cloud")loadCloud();if(view==="documentModule")loadDocumentModule(source&&source.dataset.module?source.dataset.module:activeDocumentModule);if(view==="diagnostics")refreshDiag();if(view==="settings")loadSettings();if(view==="updates"){updateStatus();refreshUpdateHistory()}}
document.querySelectorAll(".nav").forEach(b=>b.onclick=()=>showView(b.dataset.view,b));
$("openUpdate").onclick=()=>showView("updates",$("openUpdate"));
$("openSettings").onclick=()=>showView("settings",$("openSettings"));
$("homeOpenSettings").onclick=()=>showView("settings",$("openSettings"));
$("homeThemeToggle").onclick=()=>$("home").classList.toggle("reduced-glow");
$("homeBrainReset").onclick=resetHomeBrain;
$("homeDrawerClose").onclick=closeHomeNode;


let cloudLoaded=false;
let cloudSearchTimer=null;
let activePassportId=null;
let cloudCurrentFolder=null;
let cloudFolderStack=[];
let cloudFavoritesOnly=false;
let cloudTrashMode=false;
let draggedCloudDocument=null;
let activeDocumentModule="contracts";
const nowForTimesheet=new Date();
let timesheetYear=Math.max(2026,Math.min(2027,nowForTimesheet.getFullYear()));
let timesheetMonth=nowForTimesheet.getMonth()+1;
let counterpartiesCache=[];
let activeCounterpartyId=null;
let counterpartyPickForPassport=false;
const documentModuleKinds={contracts:"договор",invoice_offers:"счёт-оферта",memos:"служебная записка",orders:"приказ",directives:"распоряжение"};const directoryModules=new Set(["employees","garage","timesheet"]);
const aiAccessNames={denied:"ИИ запрещён",search:"Поиск по паспорту",read:"Чтение",answer:"Для ответов",memory:"Ответы + память",full:"Полный анализ"};
const indexNames={blocked:"Заблокирован",not_indexed:"Не индексирован",needs_indexing:"Требуется индексация",ready:"Готов"};
const confidentialityNames={ordinary:"Обычный",personal:"Личный",confidential:"Конфиденциальный",highly_protected:"Особо защищённый"};
const securityHints={ordinary:"Обычный: специальных ограничений нет; допуск ИИ задаёте вручную.",personal:"Личный: документ относится к вашему личному диску. ИИ по умолчанию запрещён, но вы можете разрешить его вручную.",confidential:"Конфиденциальный: запрещены ответы по содержимому, долговременная память и полный облачный анализ. Разрешены только запрет, поиск по паспорту и чтение.",highly_protected:"Особо защищённый: ИИ-доступ принудительно запрещён, а файл шифруется AES-256-GCM. Для включения и открытия нужен разблокированный Сейф Тори."};
async function loadDiskModules(){
  const box=$("diskModules");if(!box)return;
  try{
    const [registry,profiles]=await Promise.all([
      api("/v1/settings/modules"),
      api("/v1/cloud/intelligence/modules")
    ]);
    const counts=new Map((profiles.items||[]).map(x=>[x.id,x.count||0]));
    const visible=(registry.items||[]).filter(x=>["documents","reference","work"].includes(x.area)&&x.id!=="drive");
    box.innerHTML="";
    const icons={memos:"📝",invoice_offers:"🧾",contracts:"📑",orders:"📜",directives:"📋",employees:"👥",garage:"🚗",timesheet:"📊"};
    visible.forEach(item=>{
      const card=document.createElement("button");card.className="disk-module";card.type="button";
      const head=document.createElement("div");head.className="disk-module-head";
      const icon=document.createElement("span");icon.className="disk-module-icon";icon.textContent=icons[item.id]||"◈";
      const version=document.createElement("span");version.className="disk-module-version";version.textContent="v"+item.version;
      head.append(icon,version);
      const title=document.createElement("div");title.className="disk-module-title";title.textContent=item.title;
      const desc=document.createElement("div");desc.className="disk-module-desc";desc.textContent=item.description;
      const count=document.createElement("div");count.className="disk-module-count";
      if(counts.has(item.id))count.textContent=counts.get(item.id)+" док.";
      else if(item.id==="employees")count.textContent="справочник";
      else if(item.id==="garage")count.textContent="автопарк";
      else if(item.id==="timesheet")count.textContent="учёт часов";
      card.append(head,title,desc,count);card.onclick=()=>openDiskModule(item.id);box.append(card);
    });
  }catch(e){box.innerHTML='<div class="cloud-empty">Не удалось загрузить модули: '+escapeHtml(e.message)+'</div>'}
}
function openDiskModule(moduleId){
  activeDocumentModule=moduleId;
  showView("documentModule");
}
function cloudIcon(name){
  const ext=(String(name).split(".").pop()||"").toLowerCase();
  if(["png","jpg","jpeg","gif","webp","svg"].includes(ext))return"🖼️";
  if(ext==="pdf")return"📕";
  if(["doc","docx","odt","rtf"].includes(ext))return"📘";
  if(["xls","xlsx","csv"].includes(ext))return"📗";
  if(["zip","7z","rar"].includes(ext))return"🗜️";
  return"📄";
}
function cloudFolderParam(){return cloudCurrentFolder||"root"}
function renderCloudBreadcrumbs(){
  const box=$("cloudBreadcrumbs");box.innerHTML="";
  cloudFolderStack.forEach((folder,index)=>{
    const sep=document.createElement("span");sep.className="muted";sep.textContent="›";
    const b=document.createElement("button");b.className="icon-btn";b.textContent=folder.name;
    b.onclick=()=>{cloudFolderStack=cloudFolderStack.slice(0,index+1);cloudCurrentFolder=folder.id;cloudTrashMode=false;loadCloud()};
    box.append(sep,b);
  });
}
function openCloudFolder(folder){
  cloudCurrentFolder=folder.id;cloudFolderStack.push({id:folder.id,name:folder.name});
  cloudTrashMode=false;cloudFavoritesOnly=false;loadCloud();
}
async function moveCloudDocument(documentId,folderId){
  try{
    const body=folderId?{folder_id:folderId}:{move_to_root:true};
    await api("/v1/cloud/files/"+encodeURIComponent(documentId),{method:"PATCH",body:JSON.stringify(body)});
    $("cloudStatus").textContent="Документ перемещён.";await loadCloud();
  }catch(e){$("cloudStatus").textContent="Ошибка перемещения: "+e.message}
}
function renderCloudFolders(folders){
  const box=$("cloudList");
  folders.forEach(folder=>{
    const row=document.createElement("div");row.className="cloud-file cloud-folder";
    const main=document.createElement("div");main.className="cloud-file-main";
    const icon=document.createElement("div");icon.className="cloud-icon";icon.textContent="📁";
    const names=document.createElement("div");names.style.minWidth="0";
    const name=document.createElement("div");name.className="cloud-name";name.textContent=folder.name;
    const sub=document.createElement("div");sub.className="cloud-sub";sub.textContent="Папка · "+folder.id;
    names.append(name,sub);main.append(icon,names);main.onclick=()=>openCloudFolder(folder);
    row.ondragover=e=>{if(draggedCloudDocument){e.preventDefault();row.classList.add("drag-target")}};
    row.ondragleave=()=>row.classList.remove("drag-target");
    row.ondrop=e=>{e.preventDefault();row.classList.remove("drag-target");if(draggedCloudDocument)moveCloudDocument(draggedCloudDocument,folder.id)};
    const blank1=document.createElement("div");const blank2=document.createElement("div");
    const actions=document.createElement("div");actions.className="cloud-actions";
    const rename=document.createElement("button");rename.className="icon-btn";rename.textContent="✎";rename.title="Переименовать папку";
    rename.onclick=async e=>{e.stopPropagation();const value=prompt("Название папки:",folder.name);if(!value||!value.trim())return;try{await api("/v1/cloud/folders/"+encodeURIComponent(folder.id),{method:"PATCH",body:JSON.stringify({name:value.trim()})});await loadCloud()}catch(err){$("cloudStatus").textContent=err.message}};
    actions.append(rename);row.append(main,blank1,blank2,actions);box.appendChild(row);
  });
}
function renderCloudFiles(items,{trash=false}={}){
  const box=$("cloudList");
  items.forEach(item=>{
    const row=document.createElement("div");row.className="cloud-file";row.draggable=!trash;
    row.ondragstart=()=>{draggedCloudDocument=item.id};row.ondragend=()=>{draggedCloudDocument=null};
    const main=document.createElement("div");main.className="cloud-file-main";
    const icon=document.createElement("div");icon.className="cloud-icon";icon.textContent=cloudIcon(item.name);
    const names=document.createElement("div");names.style.minWidth="0";
    const name=document.createElement("div");name.className="cloud-name";name.textContent=(item.favorite?"★ ":"")+item.name;
    const sub=document.createElement("div");sub.className="cloud-sub";sub.textContent=item.id+" · v"+item.version+" · "+fmtBytes(item.size_bytes);
    names.append(name,sub);main.append(icon,names);
    main.title="Открыть документ";main.style.cursor="pointer";main.onclick=()=>openCloudDocument(item);

    const scope=document.createElement("div");const scopeBadge=document.createElement("span");scopeBadge.className="cloud-badge";
    scopeBadge.textContent=item.scope==="project"?"Проект · "+(item.project_id||"—"):"Личный документ";scope.append(scopeBadge);
    const ai=document.createElement("div");const aiBadge=document.createElement("span");aiBadge.className="cloud-badge ai";
    aiBadge.textContent=aiAccessNames[item.ai_access]||item.ai_access;ai.append(aiBadge);
    const actions=document.createElement("div");actions.className="cloud-actions";

    if(trash){
      const restore=document.createElement("button");restore.className="icon-btn";restore.textContent="↩";restore.title="Восстановить";
      restore.onclick=async()=>{try{await api("/v1/cloud/files/"+encodeURIComponent(item.id)+"/restore",{method:"POST"});await loadCloud()}catch(e){$("cloudStatus").textContent=e.message}};
      actions.append(restore);
    }else{
      const rename=document.createElement("button");rename.className="icon-btn";rename.textContent="✎";rename.title="Переименовать";
      rename.onclick=async()=>{const value=prompt("Новое название:",item.name);if(!value||!value.trim())return;try{await api("/v1/cloud/files/"+encodeURIComponent(item.id),{method:"PATCH",body:JSON.stringify({name:value.trim()})});await loadCloud()}catch(e){$("cloudStatus").textContent=e.message}};
      const open=document.createElement("button");open.className="icon-btn";open.title="Открыть файл";open.textContent="Открыть";open.onclick=()=>openCloudDocument(item);
      const passport=document.createElement("button");passport.className="icon-btn";passport.title="Центр документа";passport.textContent="Центр";passport.onclick=()=>openPassport(item.id);
      const download=document.createElement("a");download.className="icon-btn";download.title="Скачать";download.textContent="↓";download.href="/v1/cloud/files/"+encodeURIComponent(item.id)+"/content";download.setAttribute("download","");
      const trashBtn=document.createElement("button");trashBtn.className="icon-btn";trashBtn.title="В корзину";trashBtn.textContent="🗑";trashBtn.onclick=async()=>{if(!confirm("Переместить документ в корзину?"))return;try{await api("/v1/cloud/files/"+encodeURIComponent(item.id),{method:"DELETE"});await loadCloud()}catch(e){$("cloudStatus").textContent=e.message}};
      actions.append(open,rename,passport,download,trashBtn);
    }
    row.append(main,scope,ai,actions);box.appendChild(row);
  });
}
async function loadCloud(){
  cloudLoaded=true;loadDiskModules();renderCloudBreadcrumbs();
  try{
    const box=$("cloudList");box.innerHTML="";
    if(cloudTrashMode){
      const d=await api("/v1/cloud/trash");
      $("cloudFileCount").textContent=d.stats.total;$("cloudFolderCount").textContent=d.stats.folders;
      $("cloudUsed").textContent=fmtBytes(d.stats.total_bytes);$("cloudFavoriteCount").textContent=d.stats.favorites;
      $("cloudAiAllowed").textContent=d.stats.ai_allowed;$("cloudTrashCount").textContent=d.stats.trash;
      renderCloudFiles(d.items,{trash:true});
      if(!d.items.length)box.innerHTML='<div class="cloud-empty">Корзина пуста.</div>';
      $("cloudStatus").textContent="Корзина · документы можно восстановить.";return;
    }
    const query=$("cloudSearch").value.trim();const sort=$("cloudSort").value;
    const url="/v1/cloud/files?limit=200&folder_id="+encodeURIComponent(cloudFolderParam())+"&sort="+encodeURIComponent(sort)+(query?"&query="+encodeURIComponent(query):"")+(cloudFavoritesOnly?"&favorites_only=true":"");
    const d=await api(url);
    $("cloudFileCount").textContent=d.stats.total;$("cloudFolderCount").textContent=d.stats.folders;
    $("cloudUsed").textContent=fmtBytes(d.stats.total_bytes);$("cloudFavoriteCount").textContent=d.stats.favorites;
    $("cloudAiAllowed").textContent=d.stats.ai_allowed;$("cloudTrashCount").textContent=d.stats.trash;
    renderCloudFolders(d.folders||[]);renderCloudFiles(d.items||[]);
    if(!(d.folders||[]).length&&!(d.items||[]).length)box.innerHTML='<div class="cloud-empty">Здесь пока пусто. Создайте папку или перетащите файлы.</div>';
    $("cloudStatus").textContent=cloudFavoritesOnly?"Показано избранное.":(query?"Результаты поиска обновлены.":"");
  }catch(e){$("cloudStatus").textContent="Ошибка диска: "+e.message}
}
function activeUploadQueue(){
  return $("documentModule").classList.contains("active")?$("documentModuleUploadQueue"):$("cloudUploadQueue");
}
function createUploadQueueItem(file){
  const queue=activeUploadQueue();queue.hidden=false;
  const row=document.createElement("div");row.className="upload-item";
  const name=document.createElement("div");name.className="upload-item-name";name.textContent=file.name;
  const state=document.createElement("div");state.className="upload-item-state";state.textContent="Ожидание";
  const track=document.createElement("div");track.className="upload-track";
  const fill=document.createElement("div");fill.className="upload-fill";track.append(fill);
  row.append(name,state,track);queue.append(row);
  return{row,state,fill};
}
function uploadCloudFileWithProgress(file,folderId,onProgress){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    xhr.open("POST","/v1/cloud/files?name="+encodeURIComponent(file.name)+"&folder_id="+encodeURIComponent(folderId));
    xhr.setRequestHeader("Content-Type",file.type||"application/octet-stream");
    xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.round(e.loaded/e.total*100))};
    xhr.onerror=()=>reject(new Error("Сетевая ошибка загрузки."));
    xhr.onload=()=>{let data;try{data=JSON.parse(xhr.responseText||"{}")}catch{data={detail:xhr.responseText}};if(xhr.status>=200&&xhr.status<300)resolve(data);else reject(new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data)))};
    xhr.send(file);
  });
}
async function assignUploadedDocumentModule(document,moduleKind){
  if(!document||!document.id||!moduleKind)return;
  await api("/v1/cloud/smart/files/"+encodeURIComponent(document.id)+"/dna",{method:"PATCH",body:JSON.stringify({kind:moduleKind,origin:"Загружен пользователем через модуль «"+moduleKind+"»"})});
  await api("/v1/cloud/files/"+encodeURIComponent(document.id),{method:"PATCH",body:JSON.stringify({tags:[moduleKind]})});
}
async function uploadCloudFiles(fileList,moduleKind=null){
  const files=Array.from(fileList||[]);if(!files.length)return;
  const queue=activeUploadQueue();queue.innerHTML="";queue.hidden=false;
  let completed=0;
  for(let i=0;i<files.length;i++){
    const file=files[i],ui=createUploadQueueItem(file);ui.state.textContent="Загрузка…";
    const statusEl=$("documentModule").classList.contains("active")?$("documentModuleStatus"):$("cloudStatus");
    statusEl.textContent="Загрузка "+(i+1)+" из "+files.length+": "+file.name;
    try{
      const d=await uploadCloudFileWithProgress(file,cloudFolderParam(),p=>{ui.fill.style.width=p+"%";ui.state.textContent=p+"%"});
      ui.fill.style.width="100%";ui.state.textContent="Готово";
      if(moduleKind)await assignUploadedDocumentModule(d,moduleKind);
      completed++;
    }catch(e){ui.state.textContent="Ошибка";ui.row.title=e.message;statusEl.textContent="Ошибка загрузки "+file.name+": "+e.message}
  }
  const finalStatus=$("documentModule").classList.contains("active")?$("documentModuleStatus"):$("cloudStatus");
  finalStatus.textContent="Загружено "+completed+" из "+files.length+". Цифровые паспорта созданы автоматически.";
  $("cloudFileInput").value="";$("documentModuleFileInput").value="";
  await loadCloud();
  if(moduleKind)await loadDocumentModule(activeDocumentModule);
}
function openCloudDocument(item){
  const url="/v1/cloud/files/"+encodeURIComponent(item.id)+"/open";
  const opened=window.open(url,"_blank","noopener");
  if(!opened){openPassport(item.id);$("passportStatus").textContent="Браузер заблокировал новую вкладку. Открыл Центр документа."}
}
function moduleLead(moduleId){
  return{contracts:"Договоры по контрагентам: реквизиты, номер, дата, сумма, срок и условия. Один контрагент может иметь много договоров.",invoice_offers:"Счёт-оферта — самостоятельный мини-договор 2-в-1: контрагент, реквизиты, сумма и короткие договорные условия.",memos:"Служебные записки, включая «Работа в выходной день» с данными для табеля.",orders:"Тоору изучает разрешённые приказы предприятия как образцы структуры и формулировок, чтобы по запросу готовить новый проект приказа.",directives:"Тоору изучает разрешённые распоряжения предприятия как образцы структуры и формулировок, чтобы по запросу готовить новый проект распоряжения."}[moduleId]||"Специализированный рабочий модуль документов Тори.";
}
function formatBusinessAmount(item){
  if(item.amount_value===null||item.amount_value===undefined||item.amount_value==="")return"";
  const value=Number(item.amount_value);const amount=Number.isFinite(value)?value.toLocaleString("ru-RU",{maximumFractionDigits:2}):String(item.amount_value);
  return amount+(item.amount_currency?" "+item.amount_currency:"");
}
function createModuleDocumentRow(item){
  const row=document.createElement("div");row.className="module-document";row.onclick=()=>openPassport(item.id);
  const left=document.createElement("div");
  const title=document.createElement("div");title.className="cloud-name";title.textContent=item.name;
  const business=document.createElement("div");business.className="business-summary";
  if(item.counterparty){const x=document.createElement("span");x.className="cloud-badge";x.textContent="Контрагент: "+item.counterparty;business.append(x)}
  if(item.document_number){const x=document.createElement("span");x.className="cloud-badge";x.textContent="№ "+item.document_number;business.append(x)}
  if(item.document_date){const x=document.createElement("span");x.className="cloud-badge";x.textContent=item.document_date;business.append(x)}
  const amount=formatBusinessAmount(item);if(amount){const x=document.createElement("span");x.className="cloud-badge ai";x.textContent=amount;business.append(x)}
  if(item.document_subtype){const x=document.createElement("span");x.className="cloud-badge";x.textContent=item.document_subtype;business.append(x)}
  if(item.employee_name){const x=document.createElement("span");x.className="cloud-badge";x.textContent=item.employee_name;business.append(x)}
  if(item.work_date){const x=document.createElement("span");x.className="cloud-badge lock";x.textContent="Работа: "+item.work_date+(item.work_hours?" · "+item.work_hours+" ч":"");business.append(x)}
  const meta=document.createElement("div");meta.className="module-document-meta";
  const version=document.createElement("span");version.className="cloud-badge";version.textContent="v"+item.version;meta.append(version);
  if(item.deadlines&&item.deadlines.length){const deadline=document.createElement("span");deadline.className="cloud-badge lock";deadline.textContent="📅 "+item.deadlines[0].date;meta.append(deadline)}
  left.append(title,business,meta);
  const actions=document.createElement("div");actions.className="cloud-actions";
  const open=document.createElement("button");open.className="secondary";open.textContent="Открыть";open.onclick=e=>{e.stopPropagation();openCloudDocument(item)};
  const center=document.createElement("button");center.className="primary";center.textContent="Подробнее";center.onclick=e=>{e.stopPropagation();openPassport(item.id)};
  actions.append(open,center);row.append(left,actions);return row;
}
function renderDocumentModuleItems(items){
  const box=$("documentModuleList");box.innerHTML="";
  if(!items.length){box.innerHTML='<div class="cloud-empty">Здесь пока нет документов. Загрузите файл — тип модуля будет назначен автоматически.</div>';return}
  if(activeDocumentModule==="contracts"){
    const groups=new Map();
    items.forEach(item=>{const key=(item.counterparty||"Контрагент не указан").trim();if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item)});
    Array.from(groups.entries()).sort((a,b)=>a[0].localeCompare(b[0],"ru")).forEach(([name,groupItems])=>{
      const group=document.createElement("div");group.className="counterparty-group";
      const head=document.createElement("div");head.className="counterparty-head";
      const title=document.createElement("strong");title.textContent=name;
      const count=document.createElement("span");count.className="muted";count.textContent=groupItems.length+" договор"+(groupItems.length===1?"":groupItems.length<5?"а":"ов");
      head.append(title,count);group.append(head);groupItems.forEach(item=>group.append(createModuleDocumentRow(item)));box.append(group);
    });
    return;
  }
  items.forEach(item=>box.append(createModuleDocumentRow(item)));
}
function counterpartyPayload(){
  return {
    name:$("cpName").value.trim(),
    short_name:$("cpShortName").value.trim(),
    inn:$("cpInn").value.trim(),
    kpp:$("cpKpp").value.trim(),
    ogrn:$("cpOgrn").value.trim(),
    legal_address:$("cpLegalAddress").value.trim(),
    postal_address:$("cpPostalAddress").value.trim(),
    bank_name:$("cpBankName").value.trim(),
    bik:$("cpBik").value.trim(),
    settlement_account:$("cpSettlementAccount").value.trim(),
    correspondent_account:$("cpCorrespondentAccount").value.trim(),
    email:$("cpEmail").value.trim(),
    phone:$("cpPhone").value.trim(),
    contact_person:$("cpContactPerson").value.trim(),
    notes:$("cpNotes").value.trim()
  };
}
function clearCounterpartyForm(){
  activeCounterpartyId=null;
  ["cpName","cpShortName","cpInn","cpKpp","cpOgrn","cpLegalAddress","cpPostalAddress","cpBankName","cpBik","cpSettlementAccount","cpCorrespondentAccount","cpEmail","cpPhone","cpContactPerson","cpNotes"].forEach(id=>$(id).value="");
  $("counterpartyEditorTitle").textContent="Новый контрагент";
  $("counterpartyStatus").textContent="";
  renderCounterpartyList();
}
function fillCounterpartyForm(cp){
  activeCounterpartyId=cp.id;
  $("counterpartyEditorTitle").textContent=cp.name;
  $("cpName").value=cp.name||"";$("cpShortName").value=cp.short_name||"";$("cpInn").value=cp.inn||"";$("cpKpp").value=cp.kpp||"";$("cpOgrn").value=cp.ogrn||"";$("cpLegalAddress").value=cp.legal_address||"";$("cpPostalAddress").value=cp.postal_address||"";$("cpBankName").value=cp.bank_name||"";$("cpBik").value=cp.bik||"";$("cpSettlementAccount").value=cp.settlement_account||"";$("cpCorrespondentAccount").value=cp.correspondent_account||"";$("cpEmail").value=cp.email||"";$("cpPhone").value=cp.phone||"";$("cpContactPerson").value=cp.contact_person||"";$("cpNotes").value=cp.notes||"";
  renderCounterpartyList();
}
function renderCounterpartyList(){
  const box=$("counterpartyList");if(!box)return;box.innerHTML="";
  if(!counterpartiesCache.length){box.innerHTML='<div class="muted">Контрагентов пока нет.</div>';return}
  counterpartiesCache.forEach(cp=>{
    const row=document.createElement("div");row.className="counterparty-item"+(cp.id===activeCounterpartyId?" active":"");row.onclick=()=>fillCounterpartyForm(cp);
    const name=document.createElement("strong");name.textContent=cp.name;
    const meta=document.createElement("div");meta.className="muted";meta.textContent=(cp.inn?"ИНН "+cp.inn+" · ":"")+(cp.document_count||0)+" док.";
    row.append(name,meta);box.append(row);
  });
}
function refreshCounterpartyOptions(){
  const list=$("counterpartyOptions");if(!list)return;list.innerHTML="";
  counterpartiesCache.forEach(cp=>{const option=document.createElement("option");option.value=cp.name;option.dataset.id=cp.id;option.label=cp.inn?("ИНН "+cp.inn):cp.short_name||"";list.append(option)});
}
async function loadCounterparties(renderList=false){
  try{
    const d=await api("/v1/cloud/smart/counterparties?limit=1000");
    counterpartiesCache=d.items||[];refreshCounterpartyOptions();if(renderList)renderCounterpartyList();return counterpartiesCache;
  }catch(e){if(renderList)$("counterpartyStatus").textContent="Ошибка: "+e.message;return[]}
}
function renderPassportCounterpartyDetails(){
  const box=$("passportCounterpartyDetails");if(!box)return;
  const id=$("passportCounterpartyId").value;
  const cp=counterpartiesCache.find(x=>x.id===id);
  if(!cp){box.hidden=true;box.textContent="";return}
  const parts=[cp.inn?"ИНН "+cp.inn:"",cp.kpp?"КПП "+cp.kpp:"",cp.ogrn?"ОГРН "+cp.ogrn:"",cp.legal_address||"",cp.bank_name||"",cp.bik?"БИК "+cp.bik:"",cp.settlement_account?"р/с "+cp.settlement_account:""].filter(Boolean);
  box.textContent=parts.join(" · ");box.hidden=!parts.length;
}
function syncPassportCounterpartySelection(){
  const name=$("passportCounterparty").value.trim().toLocaleLowerCase("ru");
  const cp=counterpartiesCache.find(x=>String(x.name).trim().toLocaleLowerCase("ru")===name||String(x.short_name||"").trim().toLocaleLowerCase("ru")===name);
  $("passportCounterpartyId").value=cp?cp.id:"";renderPassportCounterpartyDetails();
}
async function openCounterpartyModal(pickForPassport=false){
  counterpartyPickForPassport=pickForPassport;await loadCounterparties(true);clearCounterpartyForm();$("counterpartyModal").hidden=false;
}
function closeCounterpartyModal(){$("counterpartyModal").hidden=true;counterpartyPickForPassport=false}
async function saveCounterparty(){
  const payload=counterpartyPayload();if(!payload.name){$("counterpartyStatus").textContent="Укажите наименование.";return}
  try{
    $("counterpartyStatus").textContent="Сохранение…";
    const cp=activeCounterpartyId
      ?await api("/v1/cloud/smart/counterparties/"+encodeURIComponent(activeCounterpartyId),{method:"PUT",body:JSON.stringify(payload)})
      :await api("/v1/cloud/smart/counterparties",{method:"POST",body:JSON.stringify(payload)});
    await loadCounterparties(true);activeCounterpartyId=cp.id;fillCounterpartyForm(cp);$("counterpartyStatus").textContent="Сохранено.";
    if(counterpartyPickForPassport&&activePassportId){$("passportCounterparty").value=cp.name;$("passportCounterpartyId").value=cp.id;renderPassportCounterpartyDetails()}
    if($("documentModule").classList.contains("active"))loadDocumentModule(activeDocumentModule);
  }catch(e){$("counterpartyStatus").textContent="Ошибка: "+e.message}
}
function applyWorkdayFields(){
  const enabled=$("passportDocumentSubtype").value==="Работа в выходной день";
  $("passportWorkdayFields").hidden=!enabled;
  if(enabled&&$("passportDnaKind").value.trim()==="")$("passportDnaKind").value="служебная записка";
}
async function showWeekendTimesheet(){
  const period=prompt("Период табеля в формате ГГГГ-ММ (можно оставить пустым):","")||"";
  let url="/v1/cloud/smart/timesheet/weekend-work";
  const match=period.trim().match(/^(\d{4})-(\d{2})$/);if(match)url+="?year="+encodeURIComponent(match[1])+"&month="+encodeURIComponent(Number(match[2]));
  openSmartModal("📋 Табель · работа в выходной день",match?period.trim():"Все записи");
  try{
    const d=await api(url);
    $("smartBody").append(smartLine("Итого",d.count+" записей · "+d.total_hours+" ч","smart-good"));
    if((d.date_conflicts||[]).length)$("smartBody").append(smartLine("⚠ Требуют проверки",d.date_conflicts.map(x=>x.document_name+" · "+(x.employee_name||"сотрудник не указан")).join("\n"),"smart-danger"));
    if(!d.items.length){$("smartBody").append(smartLine("Нет подтверждённых данных","Проверьте конфликтные даты или заполните сотрудника, даты и часы в ДНК служебной записки."));return}
    d.items.forEach(item=>{
      const body=(item.department?item.department+"\n":"")+(item.work_date||"Дата не указана")+" · "+item.work_hours+" ч"+(item.work_reason?"\n"+item.work_reason:"");
      const row=smartLine(item.employee_name,body);row.style.cursor="pointer";row.onclick=()=>{closeSmartModal();openPassport(item.document_id)};$("smartBody").append(row);
    });
  }catch(e){$("smartStatus").textContent=e.message}
}
async function studyActiveModule(){
  const allowed=new Set(["contracts","invoice_offers","garage","timesheet"]);
  if(!allowed.has(activeDocumentModule))return;
  const labels={contracts:"Договоры",invoice_offers:"Счета-оферты",garage:"Гараж",timesheet:"Табель"};
  openSmartModal("🧠 Изучение · "+(labels[activeDocumentModule]||activeDocumentModule),"Знания сохраняются только в проектную память Dragon Tory");
  $("smartStatus").textContent="Тоору изучает разрешённые данные…";
  try{
    const d=await api("/v1/cloud/intelligence/modules/"+encodeURIComponent(activeDocumentModule)+"/study",{method:"POST"});
    $("smartBody").append(smartLine("Изучено",String(d.studied),"smart-good"));
    $("smartBody").append(smartLine("Пропущено",String(d.skipped),d.skipped?"smart-warn":"smart-good"));
    $("smartBody").append(smartLine("Глубокий AI-анализ",String(d.external_ai_summaries||0)+" документов"));
    $("smartBody").append(smartLine("Память","project: "+(d.project_id||"dragon-tory")+" · личная память не изменялась","smart-good"));
    (d.skipped_items||[]).slice(0,12).forEach(item=>$("smartBody").append(smartLine("Пропущен "+item.id,item.reason,"smart-warn")));
    $("smartStatus").textContent="Изучение завершено. При следующем вопросе чат сможет найти эти знания через проектную память.";
  }catch(e){$("smartStatus").textContent="Не удалось изучить модуль: "+e.message}
}

async function draftAdministrativeDocument(){
  const isOrder=activeDocumentModule==="orders";
  const task=prompt(isOrder?"Что должен оформить новый приказ?":"Что должно содержать новое распоряжение?");
  if(!task||!task.trim())return;
  openSmartModal(isOrder?"✨ Проект приказа":"✨ Проект распоряжения","Тоору использует только разрешённые образцы этого модуля");
  try{
    $("smartStatus").textContent="Изучаю разрешённые образцы…";
    const d=await api("/v1/cloud/intelligence/modules/"+encodeURIComponent(activeDocumentModule)+"/draft",{method:"POST",body:JSON.stringify({task:task.trim()})});
    const answer=document.createElement("div");answer.className="smart-line";answer.style.whiteSpace="pre-wrap";answer.textContent=d.draft;$("smartBody").append(answer);
    $("smartBody").append(smartLine("Использовано образцов",String(d.references.length)+" · без дообучения модели и без записи в память","smart-good"));
    $("smartStatus").textContent="Проект подготовлен. Проверьте реквизиты и факты перед использованием.";
  }catch(e){$("smartStatus").textContent="Не удалось подготовить проект: "+e.message}
}

function renderDirectoryRows(items,type){
  const box=$("documentModuleList");box.innerHTML="";
  if(!items.length){box.innerHTML='<div class="cloud-empty">Записей пока нет.</div>';return}
  items.forEach(item=>{
    const row=document.createElement("div");row.className="module-document";
    const left=document.createElement("div");
    const title=document.createElement("div");title.className="cloud-name";
    const meta=document.createElement("div");meta.className="business-summary";
    if(type==="employees"){
      title.textContent=item.full_name;
      [item.personnel_number&&"Таб. № "+item.personnel_number,item.position,item.department,item.driver_license&&"В/У "+item.driver_license].filter(Boolean).forEach(value=>{const x=document.createElement("span");x.className="cloud-badge";x.textContent=value;meta.append(x)});
    }else{
      title.textContent=item.garage_number?("Гараж № "+item.garage_number):(item.plate_number||item.make_model||"Автомобиль");
      const badges=[
        item.plate_number,
        item.make_model,
        item.vin&&"VIN "+item.vin,
        item.driver_name&&"Водитель: "+item.driver_name,
        item.fuel_type&&"ГСМ: "+item.fuel_type,
        item.fuel_rate_summer!=null&&"Лето "+item.fuel_rate_summer+" л/100 км",
        item.fuel_rate_winter!=null&&"Зима "+item.fuel_rate_winter+" л/100 км",
        item.tire_size_summer&&"Шины лето: "+item.tire_size_summer,
        item.tire_size_winter&&"Шины зима: "+item.tire_size_winter
      ].filter(Boolean);
      badges.forEach(value=>{const x=document.createElement("span");x.className="cloud-badge";x.textContent=value;meta.append(x)});
      if(item.insurance_end){
        const x=document.createElement("span");
        x.className="cloud-badge "+(item.insurance_expired?"lock":item.insurance_alert?"ai":"");
        x.textContent=item.insurance_expired
          ?"⚠ Страховка истекла "+item.insurance_end
          :(item.insurance_alert
            ?"⚠ Страховка: "+item.insurance_days_left+" дн. · до "+item.insurance_end
            :"Страховка до "+item.insurance_end);
        meta.append(x);
      }
      row.style.cursor="pointer";
      row.title="Открыть карточку автомобиля";
      row.onclick=()=>openVehicleEditor(item);
    }
    left.append(title,meta);row.append(left);box.append(row);
  });
}
async function loadDirectoryModule(moduleId){
  const employeeMode=moduleId==="employees";
  const endpoint=employeeMode?"/v1/cloud/smart/employees?limit=1000":"/v1/cloud/smart/garage?limit=1000";
  const d=await api(endpoint);const items=d.items||[];
  $("documentModuleIcon").textContent=employeeMode?"👥":"🚗";
  $("documentModuleTitle").textContent=employeeMode?"Сотрудники":"Гараж";
  $("documentModuleLead").textContent=employeeMode
    ?"Справочник сотрудников для приказов, служебных записок, гаража и табеля."
    :"Автопарк: номера, VIN, водители, ГСМ, шины и страхование.";
  const insuranceAttention=employeeMode?0:items.filter(x=>x.insurance_alert||x.insurance_expired).length;
  const insuranceExpired=employeeMode?0:items.filter(x=>x.insurance_expired).length;
  $("documentModuleCount").textContent=items.length;
  $("documentModuleAnalyzed").textContent=0;
  $("documentModuleDeadlines").textContent=employeeMode?"—":insuranceAttention;
  $("documentModuleNeeds").textContent=employeeMode?"—":insuranceExpired;
  $("documentModuleExtra").textContent=employeeMode
    ?"Тоору использует этот справочник как структурированный контекст, а не как замену кадровой системе."
    :(insuranceAttention
      ?"⚠ Страхование требует внимания: "+insuranceAttention+". Предупреждение появляется за 15 дней до окончания."
      :"ГСМ хранится отдельно для летней и зимней нормы. Страховка контролируется автоматически за 15 дней.");
  const focus=$("documentModuleFocus");focus.innerHTML="";
  (employeeMode
    ?["ФИО и табельный номер","должность и подразделение","водительское удостоверение"]
    :["гаражный номер / госномер / VIN","ГСМ: лето и зима","автошины: лето и зима","страховка с / по"]).forEach(v=>{const x=document.createElement("span");x.textContent=v;focus.append(x)});
  renderDirectoryRows(items,moduleId);
}
const timesheetMonthNames=["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
function timesheetCellContent(cell){
  const wrap=document.createElement("div");wrap.className="timesheet-cell";
  const code=document.createElement("b");code.textContent=cell.code||"";
  const hours=document.createElement("small");hours.textContent=cell.hours==null?"":String(cell.hours);
  wrap.append(code,hours);return wrap;
}
function renderTimesheetGrid(d){
  const box=$("documentModuleList");box.innerHTML="";
  const scroll=document.createElement("div");scroll.className="timesheet-scroll";
  const table=document.createElement("table");table.className="timesheet-table";
  const thead=document.createElement("thead");
  const dayRow=document.createElement("tr");const personHead=document.createElement("th");personHead.rowSpan=2;personHead.textContent="Сотрудник";personHead.className="timesheet-person";dayRow.append(personHead);
  (d.calendar.days||[]).forEach(day=>{const th=document.createElement("th");th.textContent=day.day;th.className=(day.is_workday?"":"day-off")+(day.is_short_day?" short-day":"");th.title=day.reason||"";dayRow.append(th)});
  const total=document.createElement("th");total.rowSpan=2;total.textContent="Итого";dayRow.append(total);
  const weekdayRow=document.createElement("tr");
  (d.calendar.days||[]).forEach(day=>{const th=document.createElement("th");th.textContent=day.weekday_name;th.className=day.is_workday?"":"day-off";weekdayRow.append(th)});
  thead.append(dayRow,weekdayRow);table.append(thead);
  const tbody=document.createElement("tbody");
  const calendarRow=document.createElement("tr");const calendarName=document.createElement("th");calendarName.textContent="Производственный календарь";calendarName.className="timesheet-person";calendarRow.append(calendarName);
  (d.calendar.days||[]).forEach(day=>{const td=document.createElement("td");if(!day.is_workday)td.className="day-off";if(day.is_short_day)td.classList.add("short-day");td.append(timesheetCellContent({code:day.planned_code,hours:day.planned_hours}));td.title=day.reason||"";calendarRow.append(td)});
  const calendarTotal=document.createElement("td");calendarTotal.innerHTML="<b>"+d.calendar.summary.norm_hours+" ч</b><small>"+d.calendar.summary.workdays+" раб. дн.</small>";calendarRow.append(calendarTotal);tbody.append(calendarRow);
  (d.rows||[]).forEach(row=>{const tr=document.createElement("tr");const name=document.createElement("th");name.className="timesheet-person";name.textContent=row.employee_name;tr.append(name);(row.cells||[]).forEach(cell=>{const td=document.createElement("td");if(cell.code==="В")td.className="day-off";if(cell.code==="ОТ")td.className="timesheet-vacation";if(cell.code==="Б")td.className="timesheet-sick";if(cell.code==="РВ")td.className="timesheet-weekend-work";td.append(timesheetCellContent(cell));td.title=(cell.reason||"")+" · "+(cell.source||"");tr.append(td)});const summary=document.createElement("td");summary.innerHTML="<b>"+row.worked_hours+" ч</b><small>ОТ "+row.vacation_days+" · Б "+row.sick_days+" · РВ "+row.weekend_work_hours+" ч</small>";tr.append(summary);tbody.append(tr)});
  table.append(tbody);scroll.append(table);box.append(scroll);
  if(!(d.rows||[]).length){const hint=document.createElement("div");hint.className="home-trace-empty";hint.textContent="Форма табеля готова без сотрудников. Добавьте вручную отпуск/больничный или создайте служебную записку «Работа в выходной день».";box.append(hint)}
  if((d.manual_entries||[]).length){const manual=document.createElement("div");manual.className="timesheet-manual-list";const title=document.createElement("b");title.textContent="Ручные отметки";manual.append(title);d.manual_entries.forEach(entry=>{const row=document.createElement("div");row.className="module-document";const text=document.createElement("div");text.textContent=entry.employee_name+" · "+entry.code+" · "+entry.date_from+(entry.date_to!==entry.date_from?" — "+entry.date_to:"")+(entry.note?" · "+entry.note:"");const del=document.createElement("button");del.className="secondary";del.textContent="Удалить";del.onclick=async()=>{if(!confirm("Удалить ручную отметку из табеля?"))return;await api("/v1/cloud/smart/timesheet/manual/"+encodeURIComponent(entry.id),{method:"DELETE"});await loadTimesheetModule()};row.append(text,del);manual.append(row)});box.append(manual)}
  if((d.conflicts||[]).length){const warn=document.createElement("div");warn.className="statusbar bad";warn.textContent="Конфликты табеля: "+d.conflicts.map(x=>x.employee_name+" "+x.date+" ("+x.manual_code+" ↔ РВ)").join("; ");box.append(warn)}
}
async function loadTimesheetModule(){
  const d=await api("/v1/cloud/smart/timesheet/month?year="+timesheetYear+"&month="+timesheetMonth);
  $("documentModuleIcon").textContent="📊";$("documentModuleTitle").textContent="Табель";
  $("documentModuleLead").textContent="Табель учета рабочего времени: производственный календарь РФ + ручные ОТ/Б + работа в выходной из документов.";
  $("documentModuleCount").textContent=d.row_count;
  $("documentModuleAnalyzed").textContent=0;
  $("documentModuleDeadlines").textContent=d.calendar.summary.norm_hours+" ч";
  $("documentModuleNeeds").textContent=d.conflicts.length;
  $("documentModuleExtra").textContent=d.calendar.regulation+" · Норма 40 ч/нед: "+d.calendar.summary.norm_hours+" ч. Коды: Я, В, РВ, ОТ, Б.";
  const focus=$("documentModuleFocus");focus.innerHTML="";
  const year=document.createElement("select");year.className="timesheet-select";[2026,2027].forEach(value=>{const o=document.createElement("option");o.value=value;o.textContent=value+" год";o.selected=value===timesheetYear;year.append(o)});year.onchange=()=>{timesheetYear=Number(year.value);loadTimesheetModule()};
  const month=document.createElement("select");month.className="timesheet-select";timesheetMonthNames.forEach((name,index)=>{const o=document.createElement("option");o.value=index+1;o.textContent=name;o.selected=index+1===timesheetMonth;month.append(o)});month.onchange=()=>{timesheetMonth=Number(month.value);loadTimesheetModule()};
  focus.append(year,month);
  ["Я — явка","В — выходной","РВ — работа в выходной","ОТ — отпуск","Б — больничный"].forEach(v=>{const x=document.createElement("span");x.textContent=v;focus.append(x)});
  renderTimesheetGrid(d);
}

function formField(label,id,placeholder="",type="text"){
  const wrap=document.createElement("div");wrap.className="field";const l=document.createElement("label");l.textContent=label;const input=document.createElement("input");input.id=id;input.type=type;input.placeholder=placeholder;wrap.append(l,input);return wrap;
}
function openEmployeeEditor(){
  openSmartModal("👥 Новый сотрудник","Справочник Тори · данные можно использовать в документах и табеле");
  const grid=document.createElement("div");grid.className="passport-data-grid";
  [["ФИО *","empFull","Иванов Иван Иванович"],["Табельный номер","empNumber",""],["Должность","empPosition","Водитель"],["Подразделение","empDepartment",""],["Телефон","empPhone",""],["E-mail","empEmail",""],["Водительское удостоверение","empLicense",""]].forEach(x=>grid.append(formField(x[0],x[1],x[2])));
  $("smartBody").append(grid);const save=document.createElement("button");save.className="primary";save.textContent="Сохранить сотрудника";save.onclick=async()=>{const full=$("empFull").value.trim();if(!full){$("smartStatus").textContent="Укажите ФИО.";return}try{await api("/v1/cloud/smart/employees",{method:"POST",body:JSON.stringify({full_name:full,personnel_number:$("empNumber").value.trim(),position:$("empPosition").value.trim(),department:$("empDepartment").value.trim(),phone:$("empPhone").value.trim(),email:$("empEmail").value.trim(),driver_license:$("empLicense").value.trim()})});$("smartStatus").textContent="Сотрудник сохранён.";await loadDocumentModule("employees")}catch(e){$("smartStatus").textContent=e.message}};$("smartBody").append(save);
}
async function openVehicleEditor(item=null){
  let employees=[];try{employees=(await api("/v1/cloud/smart/employees?limit=1000")).items||[]}catch{}
  const editing=!!(item&&item.id);
  openSmartModal(editing?"🚗 Карточка автомобиля":"🚗 Новый автомобиль","Гараж Тори · ГСМ, шины, страхование и закреплённый водитель");
  const grid=document.createElement("div");grid.className="passport-data-grid";
  [
    ["Гаражный номер","carGarage","", "text",item&&item.garage_number],
    ["Госномер","carPlate","", "text",item&&item.plate_number],
    ["Марка / модель","carModel","", "text",item&&item.make_model],
    ["VIN","carVin","", "text",item&&item.vin],
    ["Вид топлива","carFuelType","АИ-95 / ДТ", "text",item&&item.fuel_type],
    ["Расход ГСМ летом, л/100 км","carFuelSummer","", "number",item&&item.fuel_rate_summer],
    ["Расход ГСМ зимой, л/100 км","carFuelWinter","", "number",item&&item.fuel_rate_winter],
    ["Шины лето","carTireSummer","225/60 R17", "text",item&&item.tire_size_summer],
    ["Шины зима","carTireWinter","225/60 R17", "text",item&&item.tire_size_winter],
    ["Тип страховки","carInsuranceType","ОСАГО / КАСКО", "text",item&&item.insurance_type],
    ["Номер полиса","carInsurancePolicy","", "text",item&&item.insurance_policy],
    ["Страховая компания","carInsuranceCompany","", "text",item&&item.insurance_company],
    ["Страховка с","carInsuranceStart","", "date",item&&item.insurance_start],
    ["Страховка по","carInsuranceEnd","", "date",item&&item.insurance_end]
  ].forEach(x=>{const field=formField(x[0],x[1],x[2],x[3]);const input=field.querySelector("input");if(x[3]==="number"){input.step="0.001";input.min="0"}if(x[4]!==null&&x[4]!==undefined)input.value=x[4];grid.append(field)});
  const driverWrap=document.createElement("div");driverWrap.className="field span-2";const label=document.createElement("label");label.textContent="Закреплённый водитель";const select=document.createElement("select");select.id="carDriver";const blank=document.createElement("option");blank.value="";blank.textContent="Не закреплён";select.append(blank);employees.forEach(emp=>{const o=document.createElement("option");o.value=emp.id;o.textContent=emp.full_name+(emp.position?" · "+emp.position:"");o.selected=!!(item&&item.driver_employee_id===emp.id);select.append(o)});driverWrap.append(label,select);grid.append(driverWrap);
  const notesWrap=document.createElement("div");notesWrap.className="field span-2";const notesLabel=document.createElement("label");notesLabel.textContent="Примечание";const notes=document.createElement("textarea");notes.id="carNotes";notes.value=item&&item.notes||"";notesWrap.append(notesLabel,notes);grid.append(notesWrap);
  $("smartBody").append(grid);
  if(editing&&item.insurance_end){const info=document.createElement("div");info.className="statusbar "+(item.insurance_expired?"bad":item.insurance_alert?"warn":"");info.textContent=item.insurance_expired?"Страховка просрочена.":(item.insurance_alert?"До окончания страховки "+item.insurance_days_left+" дн.":"Страховка действует до "+item.insurance_end);$("smartBody").append(info)}
  const save=document.createElement("button");save.className="primary";save.textContent=editing?"Сохранить изменения":"Сохранить автомобиль";
  save.onclick=async()=>{try{
    const body={
      garage_number:$("carGarage").value.trim(),
      plate_number:$("carPlate").value.trim(),
      make_model:$("carModel").value.trim(),
      vin:$("carVin").value.trim(),
      driver_employee_id:$("carDriver").value||null,
      fuel_type:$("carFuelType").value.trim(),
      fuel_rate_summer:$("carFuelSummer").value===""?null:Number($("carFuelSummer").value),
      fuel_rate_winter:$("carFuelWinter").value===""?null:Number($("carFuelWinter").value),
      tire_size_summer:$("carTireSummer").value.trim(),
      tire_size_winter:$("carTireWinter").value.trim(),
      insurance_type:$("carInsuranceType").value.trim(),
      insurance_policy:$("carInsurancePolicy").value.trim(),
      insurance_company:$("carInsuranceCompany").value.trim(),
      insurance_start:$("carInsuranceStart").value||null,
      insurance_end:$("carInsuranceEnd").value||null,
      notes:$("carNotes").value.trim()
    };
    const url=editing?"/v1/cloud/smart/garage/"+encodeURIComponent(item.id):"/v1/cloud/smart/garage";
    await api(url,{method:editing?"PUT":"POST",body:JSON.stringify(body)});
    $("smartStatus").textContent=editing?"Карточка автомобиля обновлена.":"Автомобиль сохранён.";
    await loadDocumentModule("garage");
  }catch(e){$("smartStatus").textContent=e.message}};
  $("smartBody").append(save);
}
async function openTimesheetEntryEditor(){
  let employees=[];try{employees=(await api("/v1/cloud/smart/employees?limit=1000")).items||[]}catch{}
  openSmartModal("📊 Ручная отметка табеля","Отпуск и больничный вводятся вручную и остаются в локальном структурированном учёте.");
  const grid=document.createElement("div");grid.className="passport-data-grid";
  const employeeWrap=document.createElement("div");employeeWrap.className="field span-2";const employeeLabel=document.createElement("label");employeeLabel.textContent="Сотрудник из справочника (необязательно)";const employeeSelect=document.createElement("select");employeeSelect.id="tsEmployee";const blank=document.createElement("option");blank.value="";blank.textContent="Ввести ФИО вручную";employeeSelect.append(blank);employees.forEach(emp=>{const o=document.createElement("option");o.value=emp.id;o.textContent=emp.full_name+(emp.personnel_number?" · "+emp.personnel_number:"");employeeSelect.append(o)});employeeWrap.append(employeeLabel,employeeSelect);grid.append(employeeWrap);
  grid.append(formField("ФИО вручную","tsEmployeeName","Иванов И.И."));
  const codeWrap=document.createElement("div");codeWrap.className="field";const codeLabel=document.createElement("label");codeLabel.textContent="Код";const codeSelect=document.createElement("select");codeSelect.id="tsCode";[["ОТ","ОТ — ежегодный оплачиваемый отпуск"],["Б","Б — временная нетрудоспособность"]].forEach(([value,text])=>{const o=document.createElement("option");o.value=value;o.textContent=text;codeSelect.append(o)});codeWrap.append(codeLabel,codeSelect);grid.append(codeWrap);
  grid.append(formField("Дата с","tsDateFrom","", "date"));
  grid.append(formField("Дата по","tsDateTo","", "date"));
  const noteWrap=document.createElement("div");noteWrap.className="field span-2";const noteLabel=document.createElement("label");noteLabel.textContent="Примечание";const note=document.createElement("textarea");note.id="tsNote";note.placeholder="Например: приказ на отпуск / больничный лист";noteWrap.append(noteLabel,note);grid.append(noteWrap);
  $("smartBody").append(grid);
  const save=document.createElement("button");save.className="primary";save.textContent="Добавить в табель";save.onclick=async()=>{try{
    const from=$("tsDateFrom").value,to=$("tsDateTo").value||from;
    if(!from){$("smartStatus").textContent="Укажите дату.";return}
    const selected=employees.find(x=>x.id===$("tsEmployee").value);
    await api("/v1/cloud/smart/timesheet/manual",{method:"POST",body:JSON.stringify({
      employee_id:$("tsEmployee").value||null,
      employee_name:selected?selected.full_name:$("tsEmployeeName").value.trim(),
      date_from:from,date_to:to,code:$("tsCode").value,note:$("tsNote").value.trim()
    })});
    $("smartStatus").textContent="Ручная отметка добавлена.";
    await loadTimesheetModule();
  }catch(e){$("smartStatus").textContent=e.message}};
  $("smartBody").append(save);
}

async function loadDocumentModule(moduleId){
  activeDocumentModule=moduleId||activeDocumentModule;
  $("documentModuleCounterparty").hidden=!["contracts","invoice_offers"].includes(activeDocumentModule);
  $("documentModuleTimesheet").hidden=activeDocumentModule!=="memos";
  $("documentModuleDraft").hidden=!["orders","directives"].includes(activeDocumentModule);
  $("documentModuleStudy").hidden=!["contracts","invoice_offers","garage","timesheet"].includes(activeDocumentModule);
  $("documentModuleAddRecord").hidden=!["employees","garage","timesheet"].includes(activeDocumentModule);
  $("documentModuleAddRecord").textContent=activeDocumentModule==="employees"
    ?"＋ Сотрудник"
    :(activeDocumentModule==="garage"?"＋ Автомобиль":"＋ Отпуск / больничный");
  $("documentModuleUpload").hidden=directoryModules.has(activeDocumentModule);
  if(activeDocumentModule==="employees"||activeDocumentModule==="garage"){try{await loadDirectoryModule(activeDocumentModule);$("documentModuleStatus").textContent=""}catch(e){$("documentModuleStatus").textContent="Ошибка модуля: "+e.message}return}
  if(activeDocumentModule==="timesheet"){try{await loadTimesheetModule();$("documentModuleStatus").textContent=""}catch(e){$("documentModuleStatus").textContent="Ошибка табеля: "+e.message}return}
  $("documentModuleDraft").textContent=activeDocumentModule==="orders"?"✨ Создать проект приказа":"✨ Создать проект распоряжения";
  $("documentModuleStatus").textContent="Загрузка модуля…";
  try{
    const d=await api("/v1/cloud/intelligence/modules/"+encodeURIComponent(activeDocumentModule));
    $("documentModuleIcon").textContent=d.icon;$("documentModuleTitle").textContent=d.title;$("documentModuleLead").textContent=moduleLead(activeDocumentModule);
    $("documentModuleCount").textContent=d.count;$("documentModuleAnalyzed").textContent=d.analyzed;$("documentModuleDeadlines").textContent=d.with_deadlines;$("documentModuleNeeds").textContent=d.needs_analysis;
    $("documentModuleExtra").textContent=activeDocumentModule==="contracts"?"Контрагентов: "+((d.counterparties||[]).length)+" · у каждого контрагента может быть несколько договоров.":(activeDocumentModule==="invoice_offers"?"Счёт-оферта хранится как самостоятельный мини-договор с реквизитами контрагента.":(activeDocumentModule==="memos"?"Подтип «Работа в выходной день» попадает в табель автоматически после заполнения даты и часов.":(["orders","directives"].includes(activeDocumentModule)?"ИИ использует только образцы с явным разрешением content_read + answer + external_ai.":"")));
    const focus=$("documentModuleFocus");focus.innerHTML="";d.ai_focus.slice(0,4).forEach(x=>{const s=document.createElement("span");s.textContent=x;focus.append(s)});
    renderDocumentModuleItems(d.items||[]);$("documentModuleStatus").textContent="";
  }catch(e){$("documentModuleStatus").textContent="Ошибка модуля: "+e.message}
}

async function createCloudFolder(){
  const name=prompt("Название новой папки:");if(!name||!name.trim())return;
  try{await api("/v1/cloud/folders",{method:"POST",body:JSON.stringify({name:name.trim(),parent_id:cloudCurrentFolder})});await loadCloud()}catch(e){$("cloudStatus").textContent="Ошибка создания папки: "+e.message}
}
function setPassportTab(name){
  document.querySelectorAll(".passport-tab").forEach(b=>b.classList.toggle("active",b.dataset.passportTarget===name));
  document.querySelectorAll("[data-passport-tab]").forEach(el=>el.classList.toggle("tab-active",el.dataset.passportTab===name));
}
async function openPassport(documentId){
  activePassportId=documentId;setPassportTab("overview");$("passportModal").hidden=false;$("passportDetails").hidden=true;$("passportStatus").textContent="Загрузка Центра документа…";
  try{
    const d=await api("/v1/cloud/files/"+encodeURIComponent(documentId)+"/passport");
    $("passportName").textContent=d.name;$("passportDocumentName").value=d.name;$("passportDescription").value=d.description||"";$("passportTags").value=(d.tags||[]).join(", ");$("passportFavorite").checked=!!d.favorite;
    $("passportId").textContent=d.id;$("passportVersion").textContent="v"+d.version;$("passportSize").textContent=fmtBytes(d.size_bytes);$("passportType").textContent=d.content_type||"—";$("passportSha").textContent=d.sha256;
    $("passportIndex").textContent=indexNames[d.ai_index_status]||d.ai_index_status;$("passportIntegrity").textContent=d.last_integrity_at?"Проверялся "+fmtChatDate(d.last_integrity_at):"Не проверялась";
    $("passportCreated").textContent=fmtChatDate(d.created_at);$("passportUpdated").textContent=fmtChatDate(d.updated_at);$("passportSource").textContent=d.source||"—";$("passportEncryption").textContent=d.encryption_status||"не зашифрован";
    $("passportAiAccess").value=d.ai_access;$("passportConfidentiality").value=d.confidentiality;$("passportScope").value=d.scope;applyConfidentialityPolicy();
    $("passportProject").value=d.project_id||"";$("passportProject").disabled=d.scope!=="project";
    $("passportDownload").href="/v1/cloud/files/"+encodeURIComponent(d.id)+"/content";
    await loadSmartPassport(documentId);
    $("passportKindBadge").textContent="Тип: "+($("passportDnaKind").value||"не определён");
    $("passportSecurityBadge").textContent="Доступ: "+(confidentialityNames[d.confidentiality]||d.confidentiality);
    $("passportAutomationBadge").textContent=d.ai_index_status==="ready"?"Интеллект: актуален":"Интеллект: проверить";
    $("passportStatus").textContent="Центр документа загружен. "+confidentialityNames[d.confidentiality]+".";
  }catch(e){$("passportStatus").textContent="Ошибка: "+e.message}
}
function closePassport(){$("passportModal").hidden=true;activePassportId=null}
function applyConfidentialityPolicy(){
  const confidentiality=$("passportConfidentiality").value;const ai=$("passportAiAccess");
  const allowed=confidentiality==="highly_protected"?["denied"]:(confidentiality==="confidential"?["denied","search","read"]:["denied","search","read","answer","memory","full"]);
  Array.from(ai.options).forEach(option=>option.disabled=!allowed.includes(option.value));
  if(!allowed.includes(ai.value))ai.value="denied";ai.disabled=true;
  $("passportSecurityHint").textContent=securityHints[confidentiality]||"";
}
async function verifyPassportIntegrity(){
  if(!activePassportId)return;
  try{$("passportIntegrity").textContent="Проверка…";const d=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/verify",{method:"POST"});$("passportIntegrity").textContent=d.ok?"✓ Файл подлинный":"⚠ Файл изменён";$("passportIntegrity").className="passport-value "+(d.ok?"ok":"bad");$("passportStatus").textContent=d.ok?"SHA-256 и размер совпадают с цифровым паспортом.":"ВНИМАНИЕ: содержимое файла не совпадает с паспортом."}catch(e){$("passportIntegrity").textContent="Ошибка";$("passportStatus").textContent="Ошибка проверки: "+e.message}
}
async function loadSmartPassport(documentId){
  try{
    const [dna,contract]=await Promise.all([
      api("/v1/cloud/smart/files/"+encodeURIComponent(documentId)+"/dna"),
      api("/v1/cloud/smart/files/"+encodeURIComponent(documentId)+"/ai-contract")
    ]);
    await loadCounterparties(false);
    $("passportDnaKind").value=dna.kind||"";$("passportDnaOrigin").value=dna.origin||"";$("passportCounterparty").value=dna.counterparty||"";$("passportCounterpartyId").value=dna.counterparty_id||"";$("passportDocumentNumber").value=dna.document_number||"";$("passportDocumentDate").value=dna.document_date||"";$("passportAmountValue").value=dna.amount_value??"";$("passportAmountCurrency").value=dna.amount_currency||"";$("passportTermsSummary").value=dna.terms_summary||"";$("passportDocumentSubtype").value=dna.document_subtype||"";$("passportEmployeeName").value=dna.employee_name||"";$("passportDepartment").value=dna.department||"";$("passportWorkDate").value=dna.work_date||"";$("passportWorkDates").value=(dna.work_dates||[]).join(", ");$("passportWorkHours").value=dna.work_hours??"";$("passportWorkReason").value=dna.work_reason||"";$("passportDnaExternalRef").value=dna.external_ref||"";$("passportDnaImportantDate").value=dna.important_date||"";$("passportDnaLanguage").value=dna.language||"";$("passportDnaNotes").value=dna.notes||"";const dateWarning=$("passportWorkDateWarning");dateWarning.hidden=!dna.work_date_conflict;dateWarning.textContent=dna.work_date_conflict?"⚠ Конфликт дат: имя файла и текст документа расходятся. Проверьте даты вручную и сохраните паспорт.":"";renderPassportCounterpartyDetails();applyWorkdayFields();
    $("contractMetadataSearch").checked=!!contract.metadata_search;$("contractContentRead").checked=!!contract.content_read;$("contractAnswer").checked=!!contract.answer;$("contractCompare").checked=!!contract.compare;$("contractMemory").checked=!!contract.memory;$("contractProposeEdits").checked=!!contract.propose_edits;$("contractExternalAI").checked=!!contract.external_ai;$("contractCleanRoom").checked=!!contract.clean_room;$("contractOneTime").checked=!!contract.one_time_answer;$("contractExpiresAt").value=contract.expires_at||"";
  }catch(e){$("passportStatus").textContent="Умный паспорт: "+e.message}
}
function smartContractPayload(){return {metadata_search:$("contractMetadataSearch").checked,content_read:$("contractContentRead").checked,answer:$("contractAnswer").checked,compare:$("contractCompare").checked,memory:$("contractMemory").checked,propose_edits:$("contractProposeEdits").checked,external_ai:$("contractExternalAI").checked,clean_room:$("contractCleanRoom").checked,one_time_answer:$("contractOneTime").checked,expires_at:$("contractExpiresAt").value.trim()||null}}
function smartDNApayload(){const workDates=$("passportWorkDates").value.split(/[;,\n]+/).map(x=>x.trim()).filter(Boolean);return {kind:$("passportDnaKind").value.trim(),origin:$("passportDnaOrigin").value.trim(),counterparty:$("passportCounterparty").value.trim(),counterparty_id:$("passportCounterpartyId").value||null,document_number:$("passportDocumentNumber").value.trim(),document_date:$("passportDocumentDate").value.trim()||null,amount_value:$("passportAmountValue").value===""?null:Number($("passportAmountValue").value),amount_currency:$("passportAmountCurrency").value.trim().toUpperCase(),terms_summary:$("passportTermsSummary").value.trim(),document_subtype:$("passportDocumentSubtype").value,employee_name:$("passportEmployeeName").value.trim(),department:$("passportDepartment").value.trim(),work_date:$("passportWorkDate").value.trim()||null,work_dates:workDates,work_hours:$("passportWorkHours").value===""?null:Number($("passportWorkHours").value),work_reason:$("passportWorkReason").value.trim(),external_ref:$("passportDnaExternalRef").value.trim(),important_date:$("passportDnaImportantDate").value.trim()||null,language:$("passportDnaLanguage").value.trim(),notes:$("passportDnaNotes").value.trim()}}
async function savePassport(){
  if(!activePassportId)return;const scope=$("passportScope").value;const project=$("passportProject").value.trim();
  if(scope==="project"&&!project){$("passportStatus").textContent="Укажите ID проекта.";return}
  try{
    $("passportStatus").textContent="Сохранение…";
    await api("/v1/cloud/files/"+encodeURIComponent(activePassportId),{method:"PATCH",body:JSON.stringify({name:$("passportDocumentName").value.trim(),favorite:$("passportFavorite").checked,description:$("passportDescription").value,tags:$("passportTags").value.split(",").map(x=>x.trim()).filter(Boolean)})});
    const d=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/passport",{method:"PATCH",body:JSON.stringify({ai_access:$("passportAiAccess").value,confidentiality:$("passportConfidentiality").value,scope:scope,project_id:scope==="project"?project:null})});
    await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/dna",{method:"PATCH",body:JSON.stringify(smartDNApayload())});
    const contract=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/ai-contract",{method:"PUT",body:JSON.stringify(smartContractPayload())});
    $("passportAiAccess").value=contract.memory?"memory":(contract.propose_edits||contract.compare?"full":(contract.answer?"answer":(contract.content_read?"read":(contract.metadata_search?"search":"denied"))));
    $("passportName").textContent=d.name;$("passportIndex").textContent=indexNames[d.ai_index_status]||d.ai_index_status;$("passportKindBadge").textContent="Тип: "+($("passportDnaKind").value||"не определён");$("passportSecurityBadge").textContent="Доступ: "+(confidentialityNames[d.confidentiality]||d.confidentiality);$("passportStatus").textContent="Центр документа сохранён: паспорт, ДНК и ИИ-договор синхронизированы.";await loadCloud();if($("documentModule").classList.contains("active"))await loadDocumentModule(activeDocumentModule);
  }catch(e){$("passportStatus").textContent="Ошибка: "+e.message}
}
async function previewPassportDocument(){
  if(!activePassportId)return;
  try{
    $("passportStatus").textContent="Читаю документ локально…";
    const d=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/preview");
    const box=$("passportDetails");box.hidden=false;box.innerHTML="<h4>Просмотр документа</h4>";
    d.chunks.forEach(chunk=>{const block=document.createElement("div");block.className="cloud-note";const title=document.createElement("b");title.textContent=chunk.label;const pre=document.createElement("div");pre.style.whiteSpace="pre-wrap";pre.style.marginTop="7px";pre.textContent=chunk.text;block.append(title,pre);box.append(block)});
    $("passportStatus").textContent=d.truncated?"Показана часть документа.":"Документ прочитан локально.";
  }catch(e){$("passportStatus").textContent="Просмотр недоступен: "+e.message}
}
async function restudyPassportDocument(){
  if(!activePassportId)return;
  openSmartModal("🧠 Повторное изучение","Тот же Tory Document ID · распознавание → DeepSeek → Guardian → память");
  try{
    $("smartStatus").textContent="Тоору повторно изучает документ…";
    const d=await api("/v1/chat/documents/"+encodeURIComponent(activePassportId)+"/restudy",{method:"POST"});
    $("smartBody").append(smartLine("Документ",d.name+"\nTory Document ID: "+d.document_id,"smart-good"));
    $("smartBody").append(smartLine("Распознавание",(d.extraction_method||"—")+(d.ocr_used?" · OCR":"")+"\nИндекс: "+d.indexed_chunks+" фрагм."));
    $("smartBody").append(smartLine("AI",d.ai_studied?((d.provider||"DeepSeek")+" · изучил"):"Только локальный анализ",d.ai_studied?"smart-good":""));
    $("smartBody").append(smartLine("Память",(d.memory_status||"—")+(d.memory_id?"\nMemory ID: "+d.memory_id:""),d.memory_status==="applied"?"smart-good":""));
    if(d.ai_error)$("smartBody").append(smartLine("Предупреждение",d.ai_error,"smart-danger"));
    const summary=document.createElement("div");summary.className="smart-line";summary.style.whiteSpace="pre-wrap";summary.textContent=d.summary||"Конспект не сформирован.";$("smartBody").append(summary);
    $("smartStatus").textContent="Повторное изучение завершено.";
  }catch(e){$("smartStatus").textContent=e.message}
}
async function indexPassportDocument(){
  if(!activePassportId)return;
  try{
    $("passportStatus").textContent="Локально извлекаю текст и создаю индекс…";
    const d=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/index",{method:"POST"});
    $("passportIndex").textContent="Готов";$("passportStatus").textContent="Индекс готов: "+d.chunk_count+" фрагм.";await loadCloud();
  }catch(e){$("passportStatus").textContent="Индексация: "+e.message}
}
async function askPassportDocument(){
  if(!activePassportId)return;
  const question=prompt("Что спросить у Тоору по этому документу?");if(!question||!question.trim())return;
  try{
    $("passportStatus").textContent="Тоору изучает разрешённые фрагменты…";
    const d=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/ask",{method:"POST",body:JSON.stringify({question:question.trim()})});
    const box=$("passportDetails");box.hidden=false;box.innerHTML="<h4>Ответ Тоору</h4>";
    const q=document.createElement("div");q.className="cloud-note";q.textContent="Вопрос: "+question;
    const answer=document.createElement("div");answer.className="cloud-note";answer.style.whiteSpace="pre-wrap";answer.textContent=d.answer;
    const sources=document.createElement("div");sources.className="cloud-note";sources.innerHTML="<b>Источники:</b><br>"+d.sources.map((s,i)=>(i+1)+". "+escapeHtml(s.label)+(s.page?" · стр. "+s.page:"")).join("<br>");
    box.append(q,answer,sources);$("passportStatus").textContent="Ответ сформирован по v"+d.version+" документа.";
  }catch(e){$("passportStatus").textContent="Тоору не может ответить: "+e.message}
}
function openSmartModal(title,subtitle=""){$("smartTitle").textContent=title;$("smartSubtitle").textContent=subtitle;$("smartBody").innerHTML="";$("smartStatus").textContent="";$("smartModal").hidden=false}
function closeSmartModal(){$("smartModal").hidden=true}
function smartLine(title,body,kind=""){const row=document.createElement("div");row.className="smart-line "+kind;const h=document.createElement("strong");h.textContent=title;const p=document.createElement("div");p.className="muted";p.style.whiteSpace="pre-wrap";p.textContent=body;row.append(h,p);return row}
async function showKnowledgeCard(){
  if(!activePassportId)return;openSmartModal("💡 Карточка знаний","Целостная картина документа");
  try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/card");const hero=document.createElement("div");hero.className="smart-hero";hero.innerHTML="<h4>"+escapeHtml(d.document.name)+"</h4><div class='muted'>"+escapeHtml(d.document.id)+" · v"+d.document.version+"</div>";$("smartBody").append(hero);$("smartBody").append(smartLine("ДНК",(d.dna.kind||"Тип не задан")+"\nПроисхождение: "+(d.dna.origin||"—")+"\nВажная дата: "+(d.dna.important_date||"—")));$("smartBody").append(smartLine("ИИ-договор","Чтение: "+(d.ai_contract.content_read?"да":"нет")+" · ответы: "+(d.ai_contract.answer?"да":"нет")+" · внешний ИИ: "+(d.ai_contract.external_ai?"да":"нет")+" · чистая комната: "+(d.ai_contract.clean_room?"да":"нет")));$("smartBody").append(smartLine("Структура","Версий: "+d.version_count+" · связей: "+d.relations.length+" · наблюдателей: "+d.watchers.length+" · печать: "+(d.latest_seal?"v"+d.latest_seal.version:"нет")));if(d.relation_suggestions.length)$("smartBody").append(smartLine("Предлагаемые связи",d.relation_suggestions.map(x=>x.name+" · совпадение "+x.score).join("\n")))}catch(e){$("smartStatus").textContent=e.message}
}
async function showDnaTimeline(){if(!activePassportId)return;openSmartModal("🧬 История ДНК","Происхождение и действия");try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/timeline");if(!d.items.length)$("smartBody").append(smartLine("История","Пока пуста."));d.items.forEach(x=>$("smartBody").append(smartLine(x.event,fmtChatDate(x.created_at)+" · "+x.actor+"\n"+(typeof x.details==="string"?x.details:JSON.stringify(x.details,null,2)))))}catch(e){$("smartStatus").textContent=e.message}}
async function showRelations(){if(!activePassportId)return;openSmartModal("🔗 Связи документа","Граф знаний без копирования файлов");try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/relations");const add=document.createElement("button");add.className="primary";add.textContent="＋ Добавить связь";add.onclick=async()=>{const target=prompt("Tory Document ID второго документа:");if(!target)return;const type=prompt("Тип: related / derived_from / replaces / supports / attachment / same_subject / reference","related")||"related";try{await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/relations",{method:"POST",body:JSON.stringify({target_id:target.trim(),relation_type:type.trim(),note:""})});showRelations()}catch(e){$("smartStatus").textContent=e.message}};$("smartBody").append(add);d.items.forEach(r=>{const other=r.source_id===activePassportId?r.target_name:r.source_name;$("smartBody").append(smartLine(r.relation_type,other+"\n"+(r.note||"")))});if(d.suggestions.length)$("smartBody").append(smartLine("Тоору предлагает",d.suggestions.map(x=>x.name+" · общие теги: "+(x.shared_tags.join(", ")||"—")).join("\n")))}catch(e){$("smartStatus").textContent=e.message}}
async function cleanRoomAsk(){if(!activePassportId)return;const question=prompt("Вопрос для Чистой комнаты:");if(!question||!question.trim())return;openSmartModal("🧼 Чистая комната","Без постоянного индекса и записи в память");try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/clean-room",{method:"POST",body:JSON.stringify({question:question.trim()})});$("smartBody").append(smartLine("Ответ Тоору",d.answer));$("smartBody").append(smartLine("Переданные источники",d.sources.map(x=>"Источник "+x.source_no+": "+x.label+(x.page?" · стр. "+x.page:"")+" · "+x.characters_sent+" символов").join("\n"),"smart-good"));$("smartBody").append(smartLine("Политика","Постоянный индекс: нет\nПамять: нет\nСодержание документа этим режимом не сохраняется.","smart-good"))}catch(e){$("smartStatus").textContent=e.message}}
async function comparePassportDocument(){if(!activePassportId)return;const other=prompt("Tory Document ID второго документа:");if(!other)return;const question=prompt("Что сравнить?","Сравни документы и перечисли существенные различия.")||"Сравни документы";openSmartModal("⇄ Сравнение документов","С доказательствами из обоих документов");try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/compare",{method:"POST",body:JSON.stringify({other_document_id:other.trim(),question})});$("smartBody").append(smartLine("Результат",d.answer));$("smartBody").append(smartLine("Источники",d.sources.map(s=>"Источник "+s.source_no+": "+s.document_name+" · "+s.label+(s.page?" · стр. "+s.page:"")).join("\n"),"smart-good"))}catch(e){$("smartStatus").textContent=e.message}}
async function sealPassportDocument(){if(!activePassportId)return;openSmartModal("🔏 Криптопечать Тори","Ed25519-подпись текущей версии");try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/seal",{method:"POST"});$("smartBody").append(smartLine("Печать создана","Версия: "+d.version+"\nОтпечаток ключа: "+d.public_key_fingerprint+"\nSHA паспорта: "+d.payload_sha256,"smart-good"));$("smartBody").append(smartLine("Важно","Это локальная криптографическая печать этой установки Dragon Tory, не государственная квалифицированная электронная подпись."))}catch(e){$("smartStatus").textContent=e.message}}
async function verifyPassportSeal(){if(!activePassportId)return;openSmartModal("✓ Проверка криптопечати","Подпись и физическая целостность");try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/seal/verify",{method:"POST"});$("smartBody").append(smartLine(d.ok?"Печать подтверждена":"Проверка не пройдена","Подпись: "+(d.signature_valid?"верна":"ошибка")+"\nФайл: "+(d.storage_verified===null?"не проверен":(d.storage_verified?"совпадает":"изменён"))+"\n"+d.storage_message,d.ok?"smart-good":"smart-danger"));$("smartBody").append(smartLine("Отпечаток ключа",d.public_key_fingerprint))}catch(e){$("smartStatus").textContent=e.message}}
async function showWatchers(){if(!activePassportId)return;openSmartModal("👁 Наблюдатели","Реакция на будущие изменения");try{const d=await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/watchers");const actions=document.createElement("div");actions.className="smart-actions";[["version_changed","Версии"],["integrity_failed","Целостность"],["passport_changed","Паспорт"],["seal_failed","Криптопечать"]].forEach(([event,label])=>{const b=document.createElement("button");b.className="secondary";b.textContent="＋ "+label;b.onclick=async()=>{try{await api("/v1/cloud/smart/files/"+encodeURIComponent(activePassportId)+"/watchers",{method:"POST",body:JSON.stringify({event_type:event,config:{}})});showWatchers()}catch(e){$("smartStatus").textContent=e.message}};actions.append(b)});$("smartBody").append(actions);d.items.forEach(w=>$("smartBody").append(smartLine(w.event_type,w.enabled?"Активен":"Выключен")))}catch(e){$("smartStatus").textContent=e.message}}
function formatEntitySummary(entities){
  const parts=[];
  if(entities.vin&&entities.vin.length)parts.push("VIN: "+entities.vin.join(", "));
  if(entities.references&&entities.references.length)parts.push("Номера: "+entities.references.join(", "));
  if(entities.dates&&entities.dates.length)parts.push("Даты: "+entities.dates.join(", "));
  if(entities.work_dates&&entities.work_dates.length)parts.push("Даты работы: "+entities.work_dates.join(", "));
  if(entities.work_date_conflict)parts.push("⚠ Конфликт дат работы: имя файла и тело документа расходятся.");
  if(entities.amounts&&entities.amounts.length)parts.push("Суммы: "+entities.amounts.slice(0,12).map(x=>x.value+" "+x.currency).join(", "));
  if(entities.emails&&entities.emails.length)parts.push("E-mail: "+entities.emails.join(", "));
  if(entities.iban&&entities.iban.length)parts.push("IBAN: "+entities.iban.join(", "));
  return parts.join("\n")||"Структурированные сущности не найдены.";
}
async function analyzePassportIntelligence(){
  if(!activePassportId)return;openSmartModal("✨ Tory Document Intelligence","Локальный анализ без передачи документа во внешний ИИ");
  try{
    $("smartStatus").textContent="Анализирую документ локально…";
    const d=await api("/v1/cloud/intelligence/files/"+encodeURIComponent(activePassportId)+"/analyze",{method:"POST"});
    $("smartBody").append(smartLine("Тип документа",d.kind+" · уверенность "+Math.round(d.confidence*100)+"%","smart-good"));
    $("smartBody").append(smartLine("Краткий фрагмент",d.summary_local||"—"));
    $("smartBody").append(smartLine("Сущности",formatEntitySummary(d.entities)));
    $("smartBody").append(smartLine("Сроки",d.deadlines.length?d.deadlines.map(x=>x.date+" · "+x.context).join("\n\n"):"Сроки не обнаружены."));
    $("smartBody").append(smartLine("Предлагаемые теги",d.suggested_tags.join(", ")||"—"));
    $("smartBody").append(smartLine("Предлагаемые связи",d.suggested_relations.length?d.suggested_relations.map(x=>x.name+" · score "+x.score).join("\n"):"Пока нет."));
    $("smartBody").append(smartLine("Способ извлечения",d.extraction_method+(d.ocr_used?" · использован локальный OCR":" · OCR не использован"),"smart-good"));
    const apply=document.createElement("button");apply.className="primary";apply.textContent="Применить теги и тип к ДНК";apply.onclick=async()=>{try{await api("/v1/cloud/intelligence/files/"+encodeURIComponent(activePassportId)+"/apply-suggestions",{method:"POST",body:JSON.stringify({apply_tags:true,apply_kind_to_dna:true})});$("smartStatus").textContent="Предложения применены после вашего подтверждения.";await openPassport(activePassportId);await loadCloud()}catch(e){$("smartStatus").textContent=e.message}};$("smartBody").append(apply);
    if(d.automation&&d.automation.applied)$("smartBody").append(smartLine("Автоматизация","Безопасно заполнено: "+d.automation.fields.join(", ")+"\nРучные значения не перезаписывались.","smart-good"));
    $("smartStatus").textContent="Анализ завершён. Полный сырой текст в отчёте Intelligence не хранится.";
  }catch(e){
    $("smartStatus").textContent=e.message;
    try{const statusData=await api("/v1/cloud/intelligence/status");$("smartBody").append(smartLine("OCR",statusData.ocr.available?"Доступен локально · "+(statusData.ocr.preferred_language||"язык по умолчанию"):"Не установлен. Сканы не отправляются во внешний ИИ автоматически.",statusData.ocr.available?"smart-good":"smart-danger"))}catch{}
  }
}
async function showPassportIntelligence(){
  if(!activePassportId)return;openSmartModal("🧠 Интеллект документа","Последний анализ текущей версии");
  try{const d=await api("/v1/cloud/intelligence/files/"+encodeURIComponent(activePassportId));$("smartBody").append(smartLine("Классификация",d.kind+" · "+Math.round(d.confidence*100)+"%"));$("smartBody").append(smartLine("Сущности",formatEntitySummary(d.entities)));$("smartBody").append(smartLine("Сроки",d.deadlines.length?d.deadlines.map(x=>x.date+" · "+x.context).join("\n\n"):"Нет"));$("smartBody").append(smartLine("Теги",d.suggested_tags.join(", ")||"—"));$("smartBody").append(smartLine("Извлечение",d.extraction_method+" · OCR: "+(d.ocr_used?"да":"нет")+" · "+fmtChatDate(d.analyzed_at)))}catch(e){$("smartStatus").textContent="Текущая версия ещё не проанализирована: "+e.message}
}
async function semanticVersionCompare(){
  if(!activePassportId)return;
  try{
    const versions=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/versions");
    if(versions.items.length<2){$("passportStatus").textContent="Для сравнения нужны минимум две версии.";return}
    const defaults=versions.items.slice(0,2).map(x=>x.version);
    const first=Number(prompt("Первая версия:",String(defaults[1]||defaults[0])));if(!first)return;
    const second=Number(prompt("Вторая версия:",String(defaults[0])));if(!second)return;
    openSmartModal("Δ Смысловое сравнение версий","DeepSeek получает только тексты двух выбранных версий при разрешённом ИИ-договоре");
    const local=await api("/v1/cloud/intelligence/files/"+encodeURIComponent(activePassportId)+"/versions/diff?first_version="+first+"&second_version="+second);
    $("smartBody").append(smartLine("Локально найдено","Добавлены даты: "+(local.dates_added.join(", ")||"—")+"\nУдалены даты: "+(local.dates_removed.join(", ")||"—")+"\nДобавлены суммы: "+(local.amounts_added.map(x=>x.value+" "+x.currency).join(", ")||"—")+"\nУдалены суммы: "+(local.amounts_removed.map(x=>x.value+" "+x.currency).join(", ")||"—")));
    const run=document.createElement("button");run.className="primary";run.textContent="Сделать смысловое сравнение через DeepSeek";run.onclick=async()=>{try{$("smartStatus").textContent="Сравниваю версии…";const d=await api("/v1/cloud/intelligence/files/"+encodeURIComponent(activePassportId)+"/versions/semantic-compare",{method:"POST",body:JSON.stringify({first_version:first,second_version:second,question:"Сравни версии по смыслу и перечисли существенные изменения."})});$("smartBody").append(smartLine("Ответ Тоору",d.answer,"smart-good"));$("smartBody").append(smartLine("Доказательство","v"+d.version_a+" · "+d.sha256_a+"\nv"+d.version_b+" · "+d.sha256_b));$("smartStatus").textContent="Сравнение завершено. В память ничего не записано."}catch(e){$("smartStatus").textContent=e.message}};$("smartBody").append(run);
  }catch(e){$("passportStatus").textContent=e.message}
}
async function smartDriveSearch(queryOverride=null){
  const query=queryOverride||prompt("Что найти? Например: «контрагент Ромашка договор 2026»");if(!query||!query.trim())return;openSmartModal("🔎 Умный поиск Тори",query);
  try{const d=await api("/v1/cloud/intelligence/search?query="+encodeURIComponent(query.trim()));if(!d.items.length){$("smartBody").append(smartLine("Ничего не найдено","Сначала проанализируйте документы кнопкой «Разобрать документы»."));return}d.items.forEach(item=>{const row=smartLine(item.name,item.kind+" · score "+item.score+"\n"+(item.summary||""));row.style.cursor="pointer";row.onclick=()=>{closeSmartModal();openPassport(item.document_id)};$("smartBody").append(row)})}catch(e){$("smartStatus").textContent=e.message}
}
async function showSmartCollections(){
  openSmartModal("🗂 Умные подборки","Виртуальные папки без физического перемещения файлов");
  try{const d=await api("/v1/cloud/intelligence/collections");d.items.forEach(collection=>{const row=document.createElement("div");row.className="smart-line";const title=document.createElement("strong");title.textContent=collection.title+" · "+collection.count;const open=document.createElement("button");open.className="secondary";open.textContent="Открыть";open.onclick=async()=>{try{const files=await api("/v1/cloud/intelligence/collections/"+encodeURIComponent(collection.id)+"/files");$("smartBody").innerHTML="";$("smartSubtitle").textContent=collection.title;files.items.forEach(item=>{const r=smartLine(item.name,item.id+" · v"+item.version);r.style.cursor="pointer";r.onclick=()=>{closeSmartModal();openPassport(item.id)};$("smartBody").append(r)})}catch(e){$("smartStatus").textContent=e.message}};row.append(title,open);$("smartBody").append(row)})}catch(e){$("smartStatus").textContent=e.message}
}
async function showDocumentDeadlines(){
  openSmartModal("📅 Сроки документов","Даты найдены локально по контексту документа");
  try{const d=await api("/v1/cloud/intelligence/deadlines");if(!d.items.length)$("smartBody").append(smartLine("Сроки","Пока не обнаружены."));d.items.forEach(x=>{const row=smartLine(x.date,x.document_name+" · v"+x.version+"\n"+x.context);row.style.cursor="pointer";row.onclick=()=>{closeSmartModal();openPassport(x.document_id)};$("smartBody").append(row)})}catch(e){$("smartStatus").textContent=e.message}
}
async function analyzePendingDocuments(){
  openSmartModal("✨ Разбор документов Тори","Обрабатываются только документы с разрешённым локальным чтением");
  try{const statusData=await api("/v1/cloud/intelligence/status");$("smartBody").append(smartLine("OCR",statusData.ocr.available?"Tesseract доступен · "+(statusData.ocr.preferred_language||"язык по умолчанию"):"Tesseract не найден. Текстовые документы будут разобраны, сканы будут пропущены.",statusData.ocr.available?"smart-good":""));$("smartStatus").textContent="Разбираю до 20 документов…";const d=await api("/v1/cloud/intelligence/analyze-pending?limit=20",{method:"POST"});$("smartBody").append(smartLine("Готово","Проанализировано: "+d.analyzed.length+"\nПропущено: "+d.skipped.length));if(d.analyzed.length)$("smartBody").append(smartLine("Распознано",d.analyzed.map(x=>x.name+" → "+x.kind+(x.ocr_used?" · OCR":"")).join("\n")));if(d.skipped.length)$("smartBody").append(smartLine("Пропущено",d.skipped.map(x=>x.document_id+" · "+x.reason).join("\n"),"smart-danger"));$("smartStatus").textContent="Пакетный анализ завершён."}catch(e){$("smartStatus").textContent=e.message}
}
async function showKnowledgeGraph(){openSmartModal("🕸 Карта знаний","Связи между документами");try{const d=await api("/v1/cloud/smart/graph");$("smartBody").append(smartLine("Масштаб","Документов: "+d.nodes.length+" · связей: "+d.edges.length));d.edges.forEach(e=>{const a=d.nodes.find(n=>n.id===e.source_id),b=d.nodes.find(n=>n.id===e.target_id);$("smartBody").append(smartLine(e.relation_type,(a?a.name:e.source_id)+" → "+(b?b.name:e.target_id)))})}catch(e){$("smartStatus").textContent=e.message}}
async function showTimeMachine(){openSmartModal("🕒 Машина времени Тори","Снимки структуры и версий диска");try{const d=await api("/v1/cloud/smart/snapshots");const create=document.createElement("button");create.className="primary";create.textContent="＋ Создать снимок сейчас";create.onclick=async()=>{const label=prompt("Название снимка:","Снимок "+new Date().toLocaleString())||"Снимок диска";try{await api("/v1/cloud/smart/snapshots",{method:"POST",body:JSON.stringify({label})});showTimeMachine()}catch(e){$("smartStatus").textContent=e.message}};$("smartBody").append(create);d.items.forEach(s=>{const row=document.createElement("div");row.className="smart-line";const title=document.createElement("strong");title.textContent=s.label;const meta=document.createElement("div");meta.className="muted";meta.textContent=fmtChatDate(s.created_at);const restore=document.createElement("button");restore.className="secondary";restore.textContent="Восстановить";restore.onclick=async()=>{if(!confirm("Восстановить имена, расположение и доступную версию? Текущие правила безопасности будут сохранены."))return;try{const r=await api("/v1/cloud/smart/snapshots/"+encodeURIComponent(s.id)+"/restore",{method:"POST"});$("smartStatus").textContent="Восстановлено: "+r.restored_documents+" · пропущено: "+r.skipped_documents;await loadCloud()}catch(e){$("smartStatus").textContent=e.message}};row.append(title,meta,restore);$("smartBody").append(row)})}catch(e){$("smartStatus").textContent=e.message}}
async function showCloudAlerts(){openSmartModal("🔔 Сигналы Тори","События от наблюдателей");try{const d=await api("/v1/cloud/smart/alerts");if(!d.items.length)$("smartBody").append(smartLine("Спокойно","Новых сигналов нет.","smart-good"));d.items.forEach(a=>{const row=smartLine(a.title,a.document_name+"\n"+a.message,a.severity==="high"?"smart-danger":"");const resolve=document.createElement("button");resolve.className="secondary";resolve.textContent="Закрыть сигнал";resolve.onclick=async()=>{await api("/v1/cloud/smart/alerts/"+encodeURIComponent(a.id)+"/resolve",{method:"POST"});showCloudAlerts()};row.append(resolve);$("smartBody").append(row)})}catch(e){$("smartStatus").textContent=e.message}}
async function loadVaultStatus(){
  try{
    const d=await api("/v1/cloud/vault/status");
    $("vaultSetup").disabled=d.configured;
    $("vaultUnlock").disabled=!d.configured||d.unlocked;
    $("vaultLock").disabled=!d.unlocked;
    $("vaultStatus").textContent=d.configured?(d.unlocked?"Сейф разблокирован · "+d.encryption:"Сейф настроен, но заблокирован."):"Сейф ещё не настроен.";
    return d;
  }catch(e){$("vaultStatus").textContent="Ошибка сейфа: "+e.message}
}
async function openVault(){
  $("vaultModal").hidden=false;$("vaultPassphrase").value="";await loadVaultStatus();$("vaultPassphrase").focus();
}
function closeVault(){$("vaultModal").hidden=true;$("vaultPassphrase").value=""}
async function setupVault(){
  const passphrase=$("vaultPassphrase").value;if(passphrase.length<12){$("vaultStatus").textContent="Нужно не менее 12 символов.";return}
  try{await api("/v1/cloud/vault/setup",{method:"POST",body:JSON.stringify({passphrase})});$("vaultPassphrase").value="";await loadVaultStatus()}catch(e){$("vaultStatus").textContent=e.message}
}
async function unlockVault(){
  const passphrase=$("vaultPassphrase").value;if(passphrase.length<12){$("vaultStatus").textContent="Введите парольную фразу.";return}
  try{await api("/v1/cloud/vault/unlock",{method:"POST",body:JSON.stringify({passphrase})});$("vaultPassphrase").value="";await loadVaultStatus()}catch(e){$("vaultStatus").textContent=e.message}
}
async function lockVault(){try{await api("/v1/cloud/vault/lock",{method:"POST"});await loadVaultStatus()}catch(e){$("vaultStatus").textContent=e.message}}
async function searchCloudContent(){
  const query=prompt("Что найти внутри изученных документов?");if(!query||!query.trim())return;
  try{
    const d=await api("/v1/cloud/search?query="+encodeURIComponent(query.trim())+"&limit=30");
    const box=$("cloudList");box.innerHTML="";
    if(!d.items.length){box.innerHTML='<div class="cloud-empty">Совпадений в индексированных документах не найдено.</div>';return}
    d.items.forEach(item=>{const row=document.createElement("div");row.className="card";row.style.cursor="pointer";const title=document.createElement("b");title.textContent=item.name+" · "+item.label;const snippet=document.createElement("div");snippet.className="muted";snippet.style.whiteSpace="pre-wrap";snippet.style.marginTop="7px";snippet.textContent=item.snippet;row.append(title,snippet);row.onclick=()=>openPassport(item.document_id);box.append(row)});
    $("cloudStatus").textContent="Поиск по содержимому: "+d.items.length+" совпадений.";
  }catch(e){$("cloudStatus").textContent="Ошибка поиска по содержимому: "+e.message}
}
async function showPassportVersions(){
  if(!activePassportId)return;
  try{
    const d=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/versions");const box=$("passportDetails");box.hidden=false;box.innerHTML="<h4>История версий</h4>";
    const list=document.createElement("div");list.className="cloud-version-list";
    d.items.forEach(v=>{const row=document.createElement("div");row.className="cloud-version-row";const meta=document.createElement("div");meta.innerHTML="<b>v"+v.version+"</b><div class='cloud-version-meta'>"+fmtBytes(v.size_bytes)+" · "+fmtChatDate(v.created_at)+" · "+escapeHtml(v.source)+"</div>";const restore=document.createElement("button");restore.className="icon-btn";restore.textContent="Восстановить";restore.onclick=async()=>{if(!confirm("Восстановить v"+v.version+" как новую текущую версию?"))return;try{await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/versions/"+v.version+"/restore",{method:"POST"});await openPassport(activePassportId);await loadCloud()}catch(e){$("passportStatus").textContent=e.message}};row.append(meta,restore);list.append(row)});box.append(list);
  }catch(e){$("passportStatus").textContent="Ошибка версий: "+e.message}
}
async function showPassportActivity(){
  if(!activePassportId)return;
  try{const d=await api("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/activity");const box=$("passportDetails");box.hidden=false;box.innerHTML="<h4>Журнал действий</h4>";const list=document.createElement("div");list.className="cloud-activity-list";d.items.forEach(a=>{const row=document.createElement("div");row.className="cloud-activity-row";row.innerHTML="<div><b>"+escapeHtml(a.action)+"</b><div class='cloud-activity-meta'>"+escapeHtml(a.details||"")+" · "+fmtChatDate(a.created_at)+"</div></div>";list.append(row)});box.append(list)}catch(e){$("passportStatus").textContent="Ошибка журнала: "+e.message}
}
async function uploadNewPassportVersion(file){
  if(!activePassportId||!file)return;
  try{$("passportStatus").textContent="Загрузка новой версии…";const r=await fetch("/v1/cloud/files/"+encodeURIComponent(activePassportId)+"/versions?name="+encodeURIComponent(file.name),{method:"POST",headers:{"Content-Type":file.type||"application/octet-stream"},body:file});let d;try{d=await r.json()}catch{d={detail:await r.text()}}if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:JSON.stringify(d.detail||d));await openPassport(activePassportId);await showPassportVersions();await loadCloud()}catch(e){$("passportStatus").textContent="Ошибка новой версии: "+e.message}
}
async function trashPassport(){
  if(!activePassportId||!confirm("Переместить документ в корзину?"))return;
  try{await api("/v1/cloud/files/"+encodeURIComponent(activePassportId),{method:"DELETE"});closePassport();await loadCloud()}catch(e){$("passportStatus").textContent="Ошибка: "+e.message}
}
$("cloudUploadButton").onclick=()=>$("cloudFileInput").click();$("cloudFileInput").onchange=e=>uploadCloudFiles(e.target.files);$("documentModuleBack").onclick=()=>showView("cloud",document.querySelector('.nav[data-view="cloud"]'));$("documentModuleUpload").onclick=()=>$("documentModuleFileInput").click();$("documentModuleFileInput").onchange=e=>uploadCloudFiles(e.target.files,documentModuleKinds[activeDocumentModule]);$("documentModuleRefresh").onclick=()=>loadDocumentModule(activeDocumentModule);$("documentModuleCounterparty").onclick=()=>openCounterpartyModal(false);$("documentModuleTimesheet").onclick=showWeekendTimesheet;$("documentModuleDraft").onclick=()=>withBusyButton("documentModuleDraft","Создаю…",draftAdministrativeDocument);$("documentModuleStudy").onclick=()=>withBusyButton("documentModuleStudy","Изучаю…",studyActiveModule);$("documentModuleAddRecord").onclick=()=>{if(activeDocumentModule==="employees")openEmployeeEditor();else if(activeDocumentModule==="timesheet")openTimesheetEntryEditor();else openVehicleEditor()};document.querySelectorAll(".passport-tab").forEach(b=>b.onclick=()=>setPassportTab(b.dataset.passportTarget));$("cloudNewFolder").onclick=createCloudFolder;$("cloudContentSearch").onclick=searchCloudContent;$("cloudVault").onclick=openVault;$("cloudKnowledgeGraph").onclick=showKnowledgeGraph;$("cloudTimeMachine").onclick=showTimeMachine;$("cloudAlerts").onclick=showCloudAlerts;$("cloudSmartSearch").onclick=smartDriveSearch;$("cloudSmartCollections").onclick=showSmartCollections;$("cloudDeadlines").onclick=showDocumentDeadlines;$("cloudAnalyzePending").onclick=()=>withBusyButton("cloudAnalyzePending","Разбираю…",analyzePendingDocuments);
$("cloudRoot").onclick=()=>{cloudCurrentFolder=null;cloudFolderStack=[];cloudTrashMode=false;cloudFavoritesOnly=false;loadCloud()};
$("cloudTrashSidebar").onclick=()=>{cloudTrashMode=true;cloudFavoritesOnly=false;showView("cloud");loadCloud()};$("cloudSort").onchange=loadCloud;
$("cloudDropZone").onclick=()=>$("cloudFileInput").click();$("cloudDropZone").onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();$("cloudFileInput").click()}};
["dragenter","dragover"].forEach(name=>$("cloudDropZone").addEventListener(name,e=>{e.preventDefault();$("cloudDropZone").classList.add("dragging")}));
["dragleave","drop"].forEach(name=>$("cloudDropZone").addEventListener(name,e=>{e.preventDefault();$("cloudDropZone").classList.remove("dragging")}));
$("cloudDropZone").addEventListener("drop",e=>uploadCloudFiles(e.dataTransfer.files));$("cloudSearch").addEventListener("input",()=>{clearTimeout(cloudSearchTimer);cloudSearchTimer=setTimeout(loadCloud,250)});$("cloudSearch").addEventListener("keydown",e=>{if(e.key==="Enter"&&$("cloudSearch").value.trim()){e.preventDefault();smartDriveSearch($("cloudSearch").value.trim())}});
$("passportClose").onclick=closePassport;$("passportSave").onclick=savePassport;$("passportSaveTop").onclick=savePassport;$("passportVerify").onclick=verifyPassportIntegrity;$("passportPreview").onclick=previewPassportDocument;$("passportIndexNow").onclick=indexPassportDocument;$("passportStudyMemory").onclick=()=>withBusyButton("passportStudyMemory","Изучаю…",restudyPassportDocument);$("passportAsk").onclick=askPassportDocument;$("passportAnalyze").onclick=analyzePassportIntelligence;$("passportInsights").onclick=showPassportIntelligence;$("passportVersionMeaning").onclick=semanticVersionCompare;$("passportCard").onclick=showKnowledgeCard;$("passportTimeline").onclick=showDnaTimeline;$("passportRelations").onclick=showRelations;$("passportCleanRoom").onclick=cleanRoomAsk;$("passportCompare").onclick=comparePassportDocument;$("passportSeal").onclick=sealPassportDocument;$("passportSealVerify").onclick=verifyPassportSeal;$("passportWatchers").onclick=showWatchers;$("passportVersions").onclick=showPassportVersions;$("passportActivity").onclick=showPassportActivity;$("passportNewVersion").onclick=()=>$("passportVersionInput").click();$("passportVersionInput").onchange=e=>{const file=e.target.files[0];e.target.value="";uploadNewPassportVersion(file)};$("passportTrash").onclick=trashPassport;
$("passportConfidentiality").onchange=applyConfidentialityPolicy;$("passportScope").onchange=()=>{$("passportProject").disabled=$("passportScope").value!=="project";if($("passportScope").value!=="project")$("passportProject").value=""};$("passportDocumentSubtype").onchange=applyWorkdayFields;$("passportCounterparty").onchange=syncPassportCounterpartySelection;$("passportNewCounterparty").onclick=()=>openCounterpartyModal(true);$("counterpartyClose").onclick=closeCounterpartyModal;$("counterpartyNew").onclick=clearCounterpartyForm;$("counterpartySave").onclick=saveCounterparty;$("counterpartyModal").addEventListener("click",e=>{if(e.target===$("counterpartyModal"))closeCounterpartyModal()});
$("passportModal").addEventListener("click",e=>{if(e.target===$("passportModal"))closePassport()});$("smartClose").onclick=closeSmartModal;$("smartModal").addEventListener("click",e=>{if(e.target===$("smartModal"))closeSmartModal()});$("vaultClose").onclick=closeVault;$("vaultSetup").onclick=setupVault;$("vaultUnlock").onclick=unlockVault;$("vaultLock").onclick=lockVault;$("vaultModal").addEventListener("click",e=>{if(e.target===$("vaultModal"))closeVault()});document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!$("counterpartyModal").hidden)closeCounterpartyModal();else if(e.key==="Escape"&&!$("passportModal").hidden)closePassport();if(e.key==="Escape"&&!$("smartModal").hidden)closeSmartModal();if(e.key==="Escape"&&!$("vaultModal").hidden)closeVault()});

function fmtChatDate(value){if(!value)return"";const d=new Date(value);return Number.isNaN(d.getTime())?"":d.toLocaleString()}
function escapeHtml(value){return String(value).replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]))}
function inlineMarkdown(value){
  let s=escapeHtml(value);
  s=s.replace(/`([^`\n]+)`/g,'<code class="inline-code">$1</code>');
  s=s.replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>");
  s=s.replace(/(^|[^*])\*([^*\n]+)\*/g,"$1<em>$2</em>");
  return s;
}
function renderTextMarkdown(value){
  const lines=String(value).split("\n");let html="",paragraph=[];
  const flush=()=>{if(!paragraph.length)return;html+="<p>"+inlineMarkdown(paragraph.join("\n")).replace(/\n/g,"<br>")+"</p>";paragraph=[]};
  lines.forEach(line=>{
    const heading=line.match(/^(#{2,4})\s+(.+)$/);
    const list=line.match(/^\s*[-*]\s+(.+)$/);
    if(heading){flush();const level=heading[1].length;html+="<h"+level+">"+inlineMarkdown(heading[2])+"</h"+level+">"}
    else if(list){flush();html+='<div class="md-list">• '+inlineMarkdown(list[1])+"</div>"}
    else if(!line.trim()){flush()}
    else paragraph.push(line);
  });
  flush();return html;
}
function renderMarkdown(text){
  const source=String(text);let out="",last=0;const re=/```([^\n`]*)\n?([\s\S]*?)```/g;let match;
  while((match=re.exec(source))!==null){
    out+=renderTextMarkdown(source.slice(last,match.index));
    const lang=(match[1]||"код").trim()||"код";
    out+='<div class="code-block"><div class="code-head"><span>'+escapeHtml(lang)+'</span><button class="copy-code">Копировать</button></div><pre><code>'+escapeHtml(match[2].replace(/\n$/,""))+'</code></pre></div>';
    last=re.lastIndex;
  }
  out+=renderTextMarkdown(source.slice(last));return out;
}
function wireCodeCopy(root){
  root.querySelectorAll(".copy-code").forEach(btn=>btn.onclick=async()=>{
    const code=btn.closest(".code-block").querySelector("code").textContent;
    try{await navigator.clipboard.writeText(code);btn.textContent="Скопировано";setTimeout(()=>btn.textContent="Копировать",1200)}catch{btn.textContent="Ошибка"}
  });
}
function emptyChat(){
  $("chatBox").innerHTML='<div class="empty-chat"><div class="dragon">🐉</div><strong>Чем помочь?</strong><span>Напишите сообщение или прикрепите документы — Тоору сохранит, изучит и запомнит их.</span></div>';
}
function addMsg(role,text,{retry=false}={}){
  const wrap=document.createElement("div");wrap.className="msg-wrap "+role;
  const d=document.createElement("div");d.className="msg "+role;
  if(role==="assistant"){d.classList.add("markdown");d.innerHTML=renderMarkdown(text);wireCodeCopy(d)}else d.textContent=text;
  wrap.appendChild(d);
  if(role==="assistant"){
    const actions=document.createElement("div");actions.className="msg-actions";
    const copy=document.createElement("button");copy.textContent="Копировать";copy.onclick=async()=>{try{await navigator.clipboard.writeText(text);copy.textContent="Скопировано";setTimeout(()=>copy.textContent="Копировать",1200)}catch{copy.textContent="Ошибка"}};
    actions.appendChild(copy);
    if(retry){const again=document.createElement("button");again.textContent="Повторить";again.onclick=retryChat;actions.appendChild(again)}
    wrap.appendChild(actions);
  }
  $("chatBox").appendChild(wrap);$("chatBox").scrollTop=$("chatBox").scrollHeight;
}
function renderChatMessages(messages){
  $("chatBox").innerHTML="";
  if(!messages.length){emptyChat();return}
  let lastAssistant=-1;messages.forEach((m,i)=>{if(m.role==="assistant")lastAssistant=i});
  messages.forEach((m,i)=>addMsg(m.role,m.content,{retry:m.role==="assistant"&&i===lastAssistant}));
}
function showThinking(){
  removeThinking();const wrap=document.createElement("div");wrap.id="thinkingBubble";wrap.className="msg-wrap assistant";
  wrap.innerHTML='<div class="thinking"><span>Тоору думает</span><i></i><i></i><i></i></div>';$("chatBox").appendChild(wrap);$("chatBox").scrollTop=$("chatBox").scrollHeight;
}
function removeThinking(){const e=$("thinkingBubble");if(e)e.remove()}
function draftKey(chatId=activeChatId){return "tooru:chat-draft:"+(chatId||"new")}
function saveDraft(){if(activeChatId)try{localStorage.setItem(draftKey(),$("chatInput").value)}catch{}}
function restoreDraft(){let value="";if(activeChatId)try{value=localStorage.getItem(draftKey())||""}catch{};$("chatInput").value=value;resizeComposer();updateComposerAction()}
function clearDraft(){if(activeChatId)try{localStorage.removeItem(draftKey())}catch{}}
function resizeComposer(){const el=$("chatInput");el.style.height="auto";el.style.height=Math.min(180,Math.max(48,el.scrollHeight))+"px"}
let chatGenerating=false;
let chatUploading=false;
function setGenerating(active){
  chatGenerating=active;const btn=$("composerAction");
  btn.classList.toggle("stop",active);btn.classList.toggle("empty",!active&&!$("chatInput").value.trim());
  btn.textContent=active?"■":"↑";btn.title=active?"Остановить генерацию":"Отправить";
  $("chatInput").disabled=active;$("chatMode").disabled=active;$("chatRemember").disabled=active;
  $("chatAttach").disabled=active||chatUploading;$("chatFileInput").disabled=active||chatUploading;
}
function setChatUploading(active){
  chatUploading=active;
  $("chatAttach").disabled=active||chatGenerating;
  $("chatFileInput").disabled=active||chatGenerating;
  $("chatComposer").classList.toggle("uploading",active);
}
function updateComposerAction(){if(chatGenerating)return;$("composerAction").classList.toggle("empty",!$("chatInput").value.trim())}
async function loadChatList(query=""){
  try{
    const d=await api("/v1/chats?limit=100"+(query?"&query="+encodeURIComponent(query):""));
    const box=$("chatList");box.innerHTML="";
    if(!d.items.length){box.innerHTML='<div class="muted" style="padding:10px">Чаты не найдены.</div>';return}
    d.items.forEach(item=>{
      const el=document.createElement("div");el.className="chat-item"+(item.id===activeChatId?" active":"");el.dataset.chatId=item.id;
      const title=document.createElement("div");title.className="chat-item-title";title.textContent=item.title;
      const meta=document.createElement("div");meta.className="chat-item-meta";meta.textContent=(item.message_count||0)+" сообщ. · "+fmtChatDate(item.updated_at);
      el.append(title,meta);el.onclick=()=>loadChat(item.id);box.appendChild(el);
    });
  }catch(e){$("chatList").innerHTML='<div class="bad" style="padding:10px">Ошибка истории: '+escapeHtml(e.message)+'</div>'}
}
async function loadChat(chatId){
  if(chatGenerating)return;saveDraft();
  try{
    const d=await api("/v1/chats/"+encodeURIComponent(chatId));
    activeChatId=d.id;activeChatTitle=d.title;$("chatTitle").textContent=d.title;$("chatMeta").textContent=(d.message_count||0)+" сообщений · "+fmtChatDate(d.updated_at)+" · личный помощник · DeepSeek";
    renderChatMessages(d.messages||[]);restoreDraft();await loadChatList($("chatSearch").value.trim());$("chatInput").focus();
  }catch(e){$("chatStatus").textContent="Не удалось открыть чат: "+e.message}
}
async function createNewChat(){
  if(chatGenerating)return;saveDraft();
  try{
    const d=await api("/v1/chats",{method:"POST",body:JSON.stringify({})});
    activeChatId=d.id;activeChatTitle=d.title;$("chatTitle").textContent=d.title;$("chatMeta").textContent="Новый чат · личный помощник · документы · DeepSeek";emptyChat();restoreDraft();await loadChatList();$("chatInput").focus();
  }catch(e){$("chatStatus").textContent="Ошибка создания чата: "+e.message}
}
async function ensureChatReady(){
  if(chatLoaded){await loadChatList($("chatSearch").value.trim());return}
  chatLoaded=true;const d=await api("/v1/chats?limit=100");if(d.items.length)await loadChat(d.items[0].id);else await createNewChat();
}
function addChatUploadRow(file){
  const row=document.createElement("div");row.className="chat-upload-item";
  const name=document.createElement("b");name.textContent=file.name;
  const status=document.createElement("span");status.textContent="готовлю…";
  row.append(name,status);$("chatUploadQueue").append(row);$("chatUploadQueue").hidden=false;
  return{row,status};
}
async function uploadChatDocuments(fileList){
  const files=Array.from(fileList||[]);if(!files.length||chatUploading||chatGenerating)return;
  if(!activeChatId)await createNewChat();if(!activeChatId)return;
  $("chatUploadQueue").innerHTML="";setChatUploading(true);
  try{
    for(const file of files){
      const ui=addChatUploadRow(file);ui.status.textContent="загрузка · "+fmtBytes(file.size);
      $("chatStatus").textContent="Тоору сохраняет и изучает «"+file.name+"»…";
      try{
        const d=await api(
          "/v1/chat/documents?chat_id="+encodeURIComponent(activeChatId)+"&name="+encodeURIComponent(file.name),
          {method:"POST",headers:{"Content-Type":file.type||"application/octet-stream"},body:file}
        );
        activeChatId=d.chat_id;activeChatTitle=d.title;$("chatTitle").textContent=d.title;
        ui.row.classList.add(d.error?"bad":"good");
        ui.status.textContent=d.error?"сохранён · требуется внимание":("изучен · "+(d.memory_status||"память"));
        $("chatStatus").textContent=d.error?("Документ сохранён: "+d.error):("Изучено: "+file.name+" · "+d.indexed_chunks+" фрагментов");
        await loadChat(activeChatId);
      }catch(e){
        ui.row.classList.add("bad");ui.status.textContent="ошибка";
        $("chatStatus").textContent="Ошибка документа «"+file.name+"»: "+e.message;
      }
    }
    await loadChatList($("chatSearch").value.trim());
  }finally{
    setChatUploading(false);$("chatFileInput").value="";
    setTimeout(()=>{if(!chatUploading){$("chatUploadQueue").hidden=true;$("chatUploadQueue").innerHTML=""}},4500);
    $("chatInput").focus();
  }
}
async function sendChat(){
  if(chatGenerating)return stopChat();
  if(chatUploading){$("chatStatus").textContent="Сначала закончу изучение загруженных документов.";return}
  const text=$("chatInput").value.trim();if(!text)return;
  if(!activeChatId)await createNewChat();if(!activeChatId)return;
  clearDraft();$("chatInput").value="";resizeComposer();updateComposerAction();
  if($("chatBox").querySelector(".empty-chat"))$("chatBox").innerHTML="";
  addMsg("user",text);showThinking();setGenerating(true);$("chatStatus").textContent="DeepSeek формирует ответ…";
  currentRequestId=(crypto.randomUUID?crypto.randomUUID():Date.now()+"-"+Math.random());currentAbortController=new AbortController();
  try{
    const d=await api("/v1/chat",{method:"POST",signal:currentAbortController.signal,body:JSON.stringify({chat_id:activeChatId,request_id:currentRequestId,message:text,remember:$("chatRemember").checked,response_mode:$("chatMode").value})});
    removeThinking();activeChatId=d.chat_id;activeChatTitle=d.title;$("chatTitle").textContent=d.title;addMsg("assistant",d.answer,{retry:true});
    $("chatStatus").textContent="DeepSeek · использовано воспоминаний: "+d.context_memories;await loadChatList($("chatSearch").value.trim());
  }catch(e){
    removeThinking();if(e.name==="AbortError"){$("chatStatus").textContent="Ответ остановлен."}else{addMsg("system","Ошибка: "+e.message);$("chatStatus").textContent="Ошибка DeepSeek API"}
    await loadChat(activeChatId);
  }finally{setGenerating(false);currentRequestId=null;currentAbortController=null;$("chatInput").focus()}
}
async function stopChat(){
  if(!currentRequestId)return;const id=currentRequestId;
  $("chatStatus").textContent="Останавливаю ответ…";
  try{await api("/v1/chat/cancel/"+encodeURIComponent(id),{method:"POST"})}catch{}
  if(currentAbortController)currentAbortController.abort();
}
async function retryChat(){
  if(!activeChatId||chatGenerating)return;
  showThinking();setGenerating(true);$("chatStatus").textContent="Тоору формирует новый вариант…";
  currentRequestId=(crypto.randomUUID?crypto.randomUUID():Date.now()+"-"+Math.random());currentAbortController=new AbortController();
  try{
    const d=await api("/v1/chat/"+encodeURIComponent(activeChatId)+"/retry",{method:"POST",signal:currentAbortController.signal,body:JSON.stringify({request_id:currentRequestId,remember:$("chatRemember").checked,response_mode:$("chatMode").value})});
    $("chatStatus").textContent="Ответ обновлён · DeepSeek";await loadChat(activeChatId);await loadChatList($("chatSearch").value.trim());
  }catch(e){removeThinking();if(e.name==="AbortError")$("chatStatus").textContent="Ответ остановлен.";else $("chatStatus").textContent="Ошибка повтора: "+e.message}
  finally{removeThinking();setGenerating(false);currentRequestId=null;currentAbortController=null}
}
async function renameActiveChat(){
  if(!activeChatId||chatGenerating)return;const title=prompt("Новое название чата:",activeChatTitle);if(title===null||!title.trim())return;
  try{const d=await api("/v1/chats/"+encodeURIComponent(activeChatId),{method:"PATCH",body:JSON.stringify({title:title.trim()})});activeChatTitle=d.title;$("chatTitle").textContent=d.title;await loadChatList($("chatSearch").value.trim())}catch(e){$("chatStatus").textContent="Ошибка переименования: "+e.message}
}
async function deleteActiveChat(){
  if(!activeChatId||chatGenerating||!confirm("Удалить этот чат? Долговременная память Тоору останется."))return;
  try{try{localStorage.removeItem(draftKey())}catch{}await api("/v1/chats/"+encodeURIComponent(activeChatId),{method:"DELETE"});activeChatId=null;const d=await api("/v1/chats?limit=100");if(d.items.length)await loadChat(d.items[0].id);else await createNewChat()}catch(e){$("chatStatus").textContent="Ошибка удаления: "+e.message}
}
$("newChat").onclick=createNewChat;$("composerAction").onclick=()=>chatGenerating?stopChat():sendChat();$("renameChat").onclick=renameActiveChat;$("deleteChat").onclick=deleteActiveChat;
$("chatAttach").onclick=()=>$("chatFileInput").click();$("chatFileInput").onchange=e=>uploadChatDocuments(e.target.files);
$("chatComposer").addEventListener("dragover",e=>{e.preventDefault();if(!chatGenerating&&!chatUploading)$("chatComposer").classList.add("dragover")});
$("chatComposer").addEventListener("dragleave",e=>{if(!$("chatComposer").contains(e.relatedTarget))$("chatComposer").classList.remove("dragover")});
$("chatComposer").addEventListener("drop",e=>{e.preventDefault();$("chatComposer").classList.remove("dragover");if(e.dataTransfer&&e.dataTransfer.files.length)uploadChatDocuments(e.dataTransfer.files)});
$("chatInput").addEventListener("input",()=>{saveDraft();resizeComposer();updateComposerAction()});
$("chatInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendChat()}});
$("chatSearch").addEventListener("input",()=>{clearTimeout(chatSearchTimer);chatSearchTimer=setTimeout(()=>loadChatList($("chatSearch").value.trim()),250)});
document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="n"){e.preventDefault();createNewChat()}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();showView("chat",document.querySelector('.nav[data-view="chat"]'));$("chatSearch").focus();$("chatSearch").select()}});
const homeTelemetry={cpu:[],ram:[],vram:[],temp:[]};
let homeModules=[];
let homeLastDiag=null;
let homeLastUpdate=null;
let homeRecentChats=[];
let homeUpdateHistory=[];
let homeObservability=null;
let homeObsLoading=false;
let homeBrainReady=false;
let homeBrainPan={x:0,y:0,scale:1,dragging:false,lastX:0,lastY:0};
let homeCy=null;
let homeFlowFrame=null;
let homeFlowPhase=0;

function homePushMetric(name,value){
  const list=homeTelemetry[name];const numeric=Number(value);
  if(Number.isFinite(numeric))list.push(numeric);else list.push(null);
  if(list.length>36)list.shift();
}
function homeSpark(id,values,maxValue=100){
  const box=$(id);if(!box)return;box.innerHTML="";
  const clean=values.map((v,i)=>({v:Number.isFinite(v)?v:null,i})).filter(x=>x.v!==null);
  if(clean.length<2){const empty=document.createElement("span");empty.className="home-card-meta";empty.textContent="недостаточно данных";box.append(empty);return}
  const width=220,height=34,pad=2;
  const min=Math.min(0,...clean.map(x=>x.v));
  const max=Math.max(maxValue||0,...clean.map(x=>x.v),min+1);
  const points=clean.map(x=>{
    const px=pad+(x.i/Math.max(1,values.length-1))*(width-pad*2);
    const py=height-pad-((x.v-min)/(max-min))*(height-pad*2);
    return [px,py];
  });
  const ns="http://www.w3.org/2000/svg";const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox",`0 0 ${width} ${height}`);
  const path=document.createElementNS(ns,"path");path.setAttribute("d",points.map((p,i)=>(i?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1)).join(" "));svg.append(path);box.append(svg);
}
function homeUptime(seconds){
  const n=Math.max(0,Number(seconds||0));const d=Math.floor(n/86400),h=Math.floor((n%86400)/3600),m=Math.floor((n%3600)/60);
  return d?d+"д "+h+"ч":h?h+"ч "+m+"м":m+"м";
}
function homePercentPart(part,total){return total?Math.max(0,Math.min(100,(Number(part||0)/Number(total))*100)):0}
function homeStatusClass(ok,attention=false){return ok?"online":attention?"attention":""}
function homeModuleById(id){return homeModules.find(x=>x.id===id)||null}
function homeActiveModules(){
  const active=(homeObservability&&homeObservability.active)||[];
  const result=new Set();
  active.forEach(item=>{
    const module=item.module==="documents"?"drive":item.module;
    if(module)result.add(module);
    if(item.category==="ai")result.add("deepseek");
  });
  return result;
}
function homeNodeStatus(id){
  if(homeActiveModules().has(id))return"active";
  if(id==="deepseek")return homeLastDiag&&homeLastDiag.ai.configured?"online":"attention";
  if(id==="memory")return homeLastDiag&&homeLastDiag.memory_engine.health&&homeLastDiag.memory_engine.health.status==="ok"?"online":"attention";
  if(id==="guardian")return homeLastDiag&&Number(homeLastDiag.guardian.queued_dead||0)>0?"attention":"online";
  return"online";
}
function homeNodeVersion(id){
  if(id==="deepseek")return homeLastDiag?homeLastDiag.ai.model:"DeepSeek";
  if(id==="chat")return"локальная история";
  if(id==="guardian")return"Memory Guardian";
  if(id==="runtime")return"live telemetry";
  const m=homeModuleById(id);return m?"v"+m.version:"core";
}
function homeGraphNodes(){
  const virtual=[
    {id:"deepseek",title:"DeepSeek",icon:"AI",description:"Облачная модель рассуждения через Cloud.ru Foundation Models.",depends_on:["memory"]},
    {id:"chat",title:"Личный помощник",icon:"CH",description:"Чат Тоору, загрузка документов, их изучение, поиск по содержимому и долговременная память.",depends_on:["memory","deepseek","drive"]},
    {id:"guardian",title:"Guardian",icon:"GD",description:"Контроль, фильтрация и обслуживание долговременной памяти.",depends_on:["memory"]},
    {id:"runtime",title:"Runtime",icon:"RT",description:"Живое состояние локального процесса, CPU, RAM, температуры и диска.",depends_on:[]},
  ];
  return [...homeModules.filter(x=>x.id!=="dashboard"),...virtual];
}
function homeBrainTransform(){
  const vp=$("homeBrainViewport");if(vp)vp.setAttribute("transform",`translate(${homeBrainPan.x} ${homeBrainPan.y}) scale(${homeBrainPan.scale})`);
}
function renderHomeBrainFallback(){
  const vp=$("homeBrainViewport");if(!vp)return;vp.innerHTML="";
  const ns="http://www.w3.org/2000/svg";const nodes=homeGraphNodes();const center={id:"dashboard",title:"ТОИРУ",icon:"T",description:"Центральная оркестрация Dragon Tory.",x:380,y:260};
  const positions=new Map([[center.id,center]]);
  const rx=285,ry=202;
  nodes.forEach((node,i)=>{const angle=(-Math.PI/2)+(i/nodes.length)*Math.PI*2;positions.set(node.id,{...node,x:380+Math.cos(angle)*rx,y:260+Math.sin(angle)*ry})});
  const edges=[];
  nodes.forEach(node=>edges.push(["dashboard",node.id]));
  nodes.forEach(node=>(node.depends_on||[]).forEach(dep=>{if(positions.has(dep)&&dep!==node.id)edges.push([node.id,dep])}));
  edges.forEach(([from,to],idx)=>{
    const a=positions.get(from),b=positions.get(to);if(!a||!b)return;
    const line=document.createElementNS(ns,"line");line.setAttribute("x1",a.x);line.setAttribute("y1",a.y);line.setAttribute("x2",b.x);line.setAttribute("y2",b.y);line.setAttribute("class","brain-edge "+(idx%4===0?"hot":""));line.style.animationDelay=(-idx*.13)+"s";vp.append(line);
  });
  const drawNode=node=>{
    const isCenter=node.id==="dashboard";const g=document.createElementNS(ns,"g");g.setAttribute("class","brain-node "+homeNodeStatus(node.id)+(isCenter?" center":""));g.setAttribute("transform",`translate(${node.x} ${node.y})`);g.dataset.nodeId=node.id;
    const title=document.createElementNS(ns,"title");title.textContent=(node.title||node.id)+" · "+(node.description||"Нажмите для деталей");
    const ring=document.createElementNS(ns,"circle");ring.setAttribute("class","node-ring");ring.setAttribute("r",isCenter?"34":"24");
    const core=document.createElementNS(ns,"circle");core.setAttribute("class","node-core");core.setAttribute("r",isCenter?"17":"10");
    const label=document.createElementNS(ns,"text");label.setAttribute("text-anchor","middle");label.setAttribute("y",isCenter?"51":"39");label.textContent=(node.title||node.id).slice(0,20);
    const sub=document.createElementNS(ns,"text");sub.setAttribute("class","node-sub");sub.setAttribute("text-anchor","middle");sub.setAttribute("y",isCenter?"63":"50");sub.textContent=homeNodeVersion(node.id).slice(0,24);
    g.append(title,ring,core,label,sub);g.onclick=e=>{e.stopPropagation();openHomeNode(node.id,node)};vp.append(g);
  };
  drawNode(center);nodes.forEach(node=>drawNode(positions.get(node.id)));
  homeBrainTransform();
}
function renderHomeBrain(){
  const cyBox=$("homeBrainCy"),svg=$("homeBrainSvg");
  if(typeof window.cytoscape!=="function"){
    if(cyBox)cyBox.hidden=true;if(svg)svg.hidden=false;renderHomeBrainFallback();return
  }
  if(svg)svg.hidden=true;if(cyBox)cyBox.hidden=false;
  const nodes=homeGraphNodes();
  const byId=new Map(nodes.map(node=>[node.id,node]));
  const center={id:"dashboard",title:"Тоору · Системный мозг",description:"Центральная оркестрация Dragon Tory.",depends_on:[]};
  byId.set(center.id,center);
  const elements=[{data:{id:center.id,label:"ТОИРУ",version:"SYSTEM CORE",kind:"center",status:homeNodeStatus(center.id),meta:center}}];
  nodes.forEach(node=>{
    const area=node.area||(["deepseek","chat","guardian"].includes(node.id)?"core":"module");
    elements.push({data:{id:node.id,label:node.title||node.id,version:homeNodeVersion(node.id),kind:area,status:homeNodeStatus(node.id),meta:node}});
  });
  const edgeKeys=new Set();
  const addEdge=(source,target,type="flow")=>{
    if(source===target||!byId.has(source)||!byId.has(target))return;
    const key=source+"->"+target;if(edgeKeys.has(key))return;edgeKeys.add(key);
    elements.push({data:{id:"e-"+edgeKeys.size,source,target,type}});
  };
  nodes.forEach(node=>addEdge("dashboard",node.id,"core"));
  nodes.forEach(node=>(node.depends_on||[]).forEach(dep=>addEdge(dep,node.id,"dependency")));
  if(homeCy){homeCy.destroy();homeCy=null}
  homeCy=window.cytoscape({
    container:cyBox,
    elements,
    wheelSensitivity:.16,
    minZoom:.42,
    maxZoom:2.2,
    boxSelectionEnabled:false,
    selectionType:"single",
    layout:{
      name:"concentric",
      fit:true,
      padding:72,
      startAngle:-Math.PI/2,
      sweep:Math.PI*2,
      clockwise:true,
      minNodeSpacing:58,
      avoidOverlap:true,
      concentric:node=>node.id()==="dashboard"?12:(node.data("kind")==="system"||node.data("kind")==="core"?7:4),
      levelWidth:()=>2
    },
    style:[
      {selector:"node",style:{
        width:64,height:64,"background-color":"#ffffff","border-width":2,"border-color":"#9db7dd",
        label:"data(label)","text-wrap":"wrap","text-max-width":116,"text-valign":"bottom","text-margin-y":11,
        "font-size":10,"font-weight":700,color:"#40516a","overlay-opacity":0,
        "shadow-blur":22,"shadow-color":"#5c86c7","shadow-opacity":.12,"shadow-offset-x":0,"shadow-offset-y":6
      }},
      {selector:'node[status = "online"]',style:{"border-color":"#5bbf9d","shadow-color":"#52b99a","shadow-opacity":.18}},
      {selector:'node[status = "active"]',style:{"background-color":"#eef6ff","border-color":"#3d83df","border-width":4,"shadow-color":"#3d83df","shadow-opacity":.32,"shadow-blur":30}},
      {selector:'node[status = "attention"]',style:{"border-color":"#d5a35b","shadow-color":"#d5a35b","shadow-opacity":.18}},
      {selector:'node[kind = "center"]',style:{
        width:106,height:106,"background-color":"#edf4ff","border-width":3,"border-color":"#5c83ca",
        "font-size":12,"font-weight":800,color:"#244b8f","shadow-blur":34,"shadow-opacity":.22
      }},
      {selector:'node[kind = "system"]',style:{"background-color":"#f5f8ff","border-color":"#8ca8d5"}},
      {selector:'node[kind = "reference"]',style:{"background-color":"#f5fbf8","border-color":"#8bc8b3"}},
      {selector:'node[kind = "work"]',style:{"background-color":"#fffaf1","border-color":"#d8b57b"}},
      {selector:"node:selected",style:{"border-width":4,"border-color":"#315fb0","shadow-opacity":.28}},
      {selector:"edge",style:{
        width:1.25,"line-color":"#c6d2e2","target-arrow-color":"#a7b9d0","target-arrow-shape":"triangle",
        "arrow-scale":.62,"curve-style":"bezier","line-style":"dashed","line-dash-pattern":[5,9],
        opacity:.67,"overlay-opacity":0
      }},
      {selector:'edge[type = "core"]',style:{"line-color":"#a9bee0","target-arrow-color":"#8faad4",width:1.55,opacity:.78}},
      {selector:"edge:selected",style:{"line-color":"#4e78bf","target-arrow-color":"#4e78bf",width:2.2,opacity:1}}
    ]
  });
  const tooltip=$("homeBrainTooltip");
  homeCy.on("tap","node",evt=>{const meta=evt.target.data("meta")||{};openHomeNode(evt.target.id(),meta)});
  homeCy.on("mouseover","node",evt=>{const node=evt.target,meta=node.data("meta")||{};const pos=node.renderedPosition();tooltip.textContent=(meta.title||node.data("label"))+" · "+(meta.description||homeNodeVersion(node.id()));tooltip.style.left=Math.min(cyBox.clientWidth-275,Math.max(12,pos.x+36))+"px";tooltip.style.top=Math.max(54,pos.y-18)+"px";tooltip.classList.add("visible")});
  homeCy.on("mouseout","node",()=>tooltip.classList.remove("visible"));
  homeCy.on("drag pan zoom",()=>tooltip.classList.remove("visible"));
  if(homeFlowFrame)cancelAnimationFrame(homeFlowFrame);
  const animate=()=>{
    homeFlowPhase=(homeFlowPhase+0.55)%28;
    if(homeCy&&!homeCy.destroyed()){
      try{homeCy.edges().style("line-dash-offset",-homeFlowPhase)}catch{}
      const pulse=.10+.07*(1+Math.sin(Date.now()/520))/2;
      try{homeCy.$("#dashboard").style("shadow-opacity",pulse+.12)}catch{}
      homeFlowFrame=requestAnimationFrame(animate);
    }
  };
  homeFlowFrame=requestAnimationFrame(animate);
}
function homeLiveKpis(id){
  const d=homeLastDiag||{};if(id==="dashboard"&&homeObservability){const s=homeObservability.stats||{};return[["Сейчас",(homeObservability.active||[]).length],["AI latency",homeObsDuration(s.ai_avg_ms)],["AI retry",s.ai_retries||0],["Guardian block",s.guardian_blocked||0],["Записей памяти",s.memory_writes||0]]}
  if(id==="deepseek"){const s=(d.ai||{}).stats||{};return[["Состояние",d.ai&&d.ai.configured?"Подключён":"Не настроен"],["Запросов",s.requests||0],["Успешно",s.successes||0],["Ошибок",s.failures||0],["Последний",homeObsDuration(s.last_duration_ms)],["Retry всего",s.total_retries||0]]}
  if(id==="memory"){const m=d.memory_engine||{};return[["Активных",m.active||0],["Личных",m.personal||0],["Проектных",m.project||0],["Векторов",m.vectors||0]]}
  if(id==="guardian"){const g=d.guardian||{};return[["Ожидают",g.queued_pending||0],["Применено",g.queued_applied||0],["Отклонено",g.queued_rejected||0],["Dead-letter",g.queued_dead||0]]}
  if(id==="chat"){const h=d.chat_history||{};return[["Чатов",h.chats||0],["Сообщений",h.messages||0],["База",fmtBytes(h.database_bytes||0)]]}
  if(id==="runtime"){const sys=d.system||{},mem=d.system_memory||{},proc=d.process||{},disk=d.disk||{};return[["CPU",(sys.cpu_percent??0)+"%"],["RAM",(mem.percent??0)+"%"],["Dragon Tory",fmtBytes(proc.rss_bytes||0)],["Температура",sys.cpu_temperature_c==null?"н/д":sys.cpu_temperature_c+"°C"],["Диск свободно",fmtBytes(disk.free_bytes||0)]]}
  if(id==="updater"&&homeLastUpdate)return[["Локальная",homeLastUpdate.local_version||"—"],["GitHub",homeLastUpdate.remote_version||"—"],["Фаза",homeLastUpdate.phase||"—"],["Прогресс",(homeLastUpdate.progress_percent||0)+"%"]];
  return[];
}
function openHomeNode(id,fallback=null){
  const item=homeModuleById(id)||fallback||{id,title:id,description:"Системный модуль Dragon Tory.",depends_on:[]};
  $("homeDrawerIcon").textContent=item.icon||({deepseek:"AI",chat:"CH",guardian:"GD",runtime:"RT",dashboard:"🐉"}[id]||"◈");
  $("homeDrawerTitle").textContent=item.title||id;$("homeDrawerVersion").textContent=homeNodeVersion(id);
  const body=$("homeDrawerBody");body.innerHTML="";
  const desc=document.createElement("div");desc.className="home-drawer-block";const h=document.createElement("h4");h.textContent="Назначение";const p=document.createElement("p");p.textContent=item.description||"Компонент локальной AI-системы.";desc.append(h,p);body.append(desc);
  const live=homeLiveKpis(id);if(live.length){const block=document.createElement("div");block.className="home-drawer-block";const title=document.createElement("h4");title.textContent="Live";block.append(title);live.forEach(([k,v])=>{const row=document.createElement("div");row.className="home-drawer-kpi";const a=document.createElement("span");a.textContent=k;const b=document.createElement("b");b.textContent=String(v);row.append(a,b);block.append(row)});body.append(block)}
  const deps=item.depends_on||[];const dep=document.createElement("div");dep.className="home-drawer-block";const dh=document.createElement("h4");dh.textContent="Связи";const dp=document.createElement("p");dp.textContent=deps.length?"Зависит от: "+deps.join(", "):"Прямой системный узел без объявленных зависимостей.";dep.append(dh,dp);body.append(dep);
  if(item.last_update){const ch=document.createElement("div");ch.className="home-drawer-block";const hh=document.createElement("h4");hh.textContent="Последнее изменение";const pp=document.createElement("p");pp.textContent=item.last_update;ch.append(hh,pp);body.append(ch)}
  $("homeNodeDrawer").classList.add("open");$("homeNodeDrawer").setAttribute("aria-hidden","false");
}
function closeHomeNode(){$("homeNodeDrawer").classList.remove("open");$("homeNodeDrawer").setAttribute("aria-hidden","true")}
function initHomeBrain(){
  if(homeBrainReady)return;homeBrainReady=true;const svg=$("homeBrainSvg");
  if(typeof window.cytoscape==="function")return;
  svg.addEventListener("wheel",e=>{e.preventDefault();const next=Math.max(.55,Math.min(1.9,homeBrainPan.scale*(e.deltaY<0?1.09:.92)));homeBrainPan.scale=next;homeBrainTransform()},{passive:false});
  svg.addEventListener("pointerdown",e=>{if(e.target.closest&&e.target.closest(".brain-node"))return;homeBrainPan.dragging=true;homeBrainPan.lastX=e.clientX;homeBrainPan.lastY=e.clientY;svg.classList.add("dragging");svg.setPointerCapture(e.pointerId)});
  svg.addEventListener("pointermove",e=>{if(!homeBrainPan.dragging)return;homeBrainPan.x+=(e.clientX-homeBrainPan.lastX)/homeBrainPan.scale;homeBrainPan.y+=(e.clientY-homeBrainPan.lastY)/homeBrainPan.scale;homeBrainPan.lastX=e.clientX;homeBrainPan.lastY=e.clientY;homeBrainTransform()});
  const end=e=>{homeBrainPan.dragging=false;svg.classList.remove("dragging");try{svg.releasePointerCapture(e.pointerId)}catch{}};
  svg.addEventListener("pointerup",end);svg.addEventListener("pointercancel",end);
}
function resetHomeBrain(){if(homeCy&&!homeCy.destroyed()){homeCy.fit(undefined,72);return}homeBrainPan={x:0,y:0,scale:1,dragging:false,lastX:0,lastY:0};homeBrainTransform()}
function homeTask(title,sub,time,warn=false){
  const row=document.createElement("div");row.className="home-task";const dot=document.createElement("span");dot.className="home-task-dot"+(warn?" warn":"");const main=document.createElement("div");main.className="home-task-main";const t=document.createElement("div");t.className="home-task-title";t.textContent=title;const s=document.createElement("div");s.className="home-task-sub";s.textContent=sub;main.append(t,s);const tm=document.createElement("span");tm.className="home-task-time";tm.textContent=time;row.append(dot,main,tm);return row;
}
function renderHomeTasks(){
  const box=$("homeTaskList");if(!box||!homeLastDiag)return;box.innerHTML="";const d=homeLastDiag;const now=new Date().toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
  box.append(homeTask("Memory Guardian",Number(d.guardian.queued_pending||0)?"Ожидают проверки: "+d.guardian.queued_pending:"Очередь обработана",now,Number(d.guardian.queued_dead||0)>0));
  box.append(homeTask("Memory Automation",d.memory_automation.running?"Идёт обслуживание":"Автоматика активна",now,!d.memory_automation.started));
  if(d.garage&&Number(d.garage.insurance_alerts||0)>0){
    const expired=Number(d.garage.insurance_expired||0),upcoming=Number(d.garage.insurance_upcoming||0);
    box.append(homeTask("Гараж · страховка",(expired?"Просрочено: "+expired+" · ":"")+(upcoming?"Заканчивается ≤15 дней: "+upcoming:""),now,expired>0));
  }
  if(homeLastUpdate)box.append(homeTask("Центр обновления",(homeLastUpdate.message||homeLastUpdate.phase||"Готово")+" · "+(homeLastUpdate.local_version||""),homeLastUpdate.running?"live":"state",["failed","error"].includes(homeLastUpdate.phase)));
  if(homeRecentChats.length){const chat=homeRecentChats[0];box.append(homeTask("Последний чат",chat.title||"Новый чат",(chat.message_count||0)+" сообщ.",false))}
  else box.append(homeTask("Чат","История пока пуста","—",false));
}
function homeObsDuration(value){
  const ms=Number(value||0);if(!Number.isFinite(ms)||ms<=0)return"—";
  return ms<1000?Math.round(ms)+" ms":(ms/1000).toFixed(ms<10000?1:0)+" s";
}
function homeObsModuleLabel(value){
  return({chat:"Чат",memory:"Память",drive:"Мой диск",contracts:"Договоры",invoice_offers:"Счета-оферты",orders:"Приказы",directives:"Распоряжения",memos:"Служебные записки",garage:"Гараж",timesheet:"Табель",settings:"Настройки"}[value]||value||"Система");
}
function homeObsStepLabel(item){
  return({source:"Источник",analysis:"Анализ",ai:"AI",guardian:"Guardian",memory:"Память",policy:"Политика"}[item.category]||item.stage||item.category||"Шаг");
}
function homeObsOperationLabel(value){
  return({
    chat_response:"Ответ пользователю",
    memory_extract:"Извлечение памяти",
    memory_review:"Проверка памяти",
    local_document_analysis:"Локальный разбор",
    module_document_analysis:"Анализ модулем",
    document_deep_summary:"DeepSeek-анализ",
    document_qa:"Вопрос по документу",
    document_compare:"Сравнение документов",
    document_version_compare:"Сравнение версий",
    clean_room_answer:"Чистая комната",
    administrative_draft:"Проект документа",
    weekend_work_draft:"Служебная записка",
    deepseek_connection_test:"Проверка DeepSeek",
    create:"Создание",
    update:"Обновление",
    source_received:"Источник",
    module_document_selected:"Документ выбран",
    document_selected:"Документ выбран",
    garage_record_changed:"Изменение гаража",
    weekend_work_changed:"Работа в выходной",
    web_research:"Интернет-поиск",
    ai_contract:"ИИ-договор"
  }[value]||String(value||"операция").replaceAll("_"," "));
}
function refreshHomeBrainStatuses(){
  if(homeCy&&!homeCy.destroyed()){
    homeCy.nodes().forEach(node=>node.data("status",homeNodeStatus(node.id())));
  }else{
    document.querySelectorAll("#homeBrainViewport .brain-node").forEach(node=>{
      const id=node.dataset.nodeId||"";
      const center=node.classList.contains("center");
      node.setAttribute("class","brain-node "+homeNodeStatus(id)+(center?" center":""));
    });
  }
}
function renderHomeObservability(data){
  homeObservability=data||{active:[],stats:{},chains:[]};
  const stats=homeObservability.stats||{},active=homeObservability.active||[],current=homeObservability.current||null;
  $("homeObsActive").textContent=active.length;
  $("homeObsLatency").textContent=homeObsDuration(stats.ai_avg_ms);
  $("homeObsRetries").textContent=stats.ai_retries||0;
  $("homeObsBlocked").textContent=stats.guardian_blocked||0;
  $("homeObsMemory").textContent=stats.memory_writes||0;
  $("homeObsStamp").textContent=new Date().toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  const state=$("homeObsState"),currentBox=$("homeObsCurrent"),brainState=$("homeBrainActivity");
  currentBox.classList.remove("running","error");
  if(current){
    const label=homeObsModuleLabel(current.module)+" · "+homeObsOperationLabel(current.operation);
    state.textContent="Тоору сейчас: "+label;
    brainState.textContent="live · "+label;
    currentBox.classList.add(current.status==="error"?"error":"running");
    currentBox.querySelector("b").textContent=label;
    const source=current.document_id?("Document ID: "+current.document_id):(current.source_id?("Источник: "+current.source_id):"Выполняется локально");
    currentBox.querySelector("div span").textContent=source;
  }else{
    state.textContent="Сейчас активных анализов нет";
    brainState.textContent="перетаскивание · колесо = масштаб · клик = детали";
    currentBox.querySelector("b").textContent="Тоору ожидает задачу";
    currentBox.querySelector("div span").textContent="Активных анализов сейчас нет.";
  }
  const box=$("homeTraceList");box.innerHTML="";
  const chains=homeObservability.chains||[];
  if(!chains.length){const empty=document.createElement("div");empty.className="home-trace-empty";empty.textContent="События появятся после работы чата, документов, Guardian или памяти.";box.append(empty)}
  chains.slice(0,8).forEach(chain=>{
    const row=document.createElement("div");row.className="home-trace";
    const head=document.createElement("div");head.className="home-trace-head";
    const title=document.createElement("div");title.className="home-trace-title";title.textContent=homeObsModuleLabel(chain.module)+(chain.document_id?" · "+chain.document_id:"");
    const meta=document.createElement("span");meta.className="home-trace-meta";meta.textContent=chain.status+" · "+new Date(chain.started_at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
    head.append(title,meta);row.append(head);
    const flow=document.createElement("div");flow.className="home-trace-flow";
    (chain.steps||[]).forEach((step,index)=>{
      if(index){const arrow=document.createElement("span");arrow.className="home-trace-arrow";arrow.textContent="→";flow.append(arrow)}
      const card=document.createElement("div");card.className="home-trace-step "+(step.status||"");
      const strong=document.createElement("strong");strong.textContent=homeObsStepLabel(step)+" · "+homeObsOperationLabel(step.operation);
      const sub=document.createElement("span");
      const details=[];
      if(step.provider)details.push(step.provider);
      if(Number(step.retry_count||0)>0)details.push("retry "+step.retry_count);
      if(Number(step.duration_ms||0)>0)details.push(homeObsDuration(step.duration_ms));
      if(step.memory_id)details.push("Memory "+String(step.memory_id).slice(0,10));
      sub.textContent=details.join(" · ")||(step.message||step.status||"готово");
      card.append(strong,sub);flow.append(card);
    });
    row.append(flow);box.append(row);
  });
  refreshHomeBrainStatuses();
}
async function refreshHomeObservability(){
  if(homeObsLoading)return;homeObsLoading=true;
  try{renderHomeObservability(await api("/v1/observability/summary?limit=50&hours=24"))}
  catch(e){$("homeObsState").textContent="Наблюдаемость временно недоступна: "+e.message}
  finally{homeObsLoading=false}
}
async function loadHomeDashboard(){
  initHomeBrain();
  try{
    const [modules,update,chats,history]=await Promise.all([
      api("/v1/settings/modules"),
      api("/v1/update/status"),
      api("/v1/chats?limit=5"),
      api("/v1/update/history?limit=5")
    ]);
    homeModules=modules.items||[];homeLastUpdate=update;homeRecentChats=chats.items||[];homeUpdateHistory=history.items||[];renderHomeBrain();renderHomeTasks();refreshHomeObservability();
  }catch(e){const box=$("homeTaskList");if(box){box.innerHTML="";box.append(homeTask("Дашборд","Часть данных недоступна: "+e.message,"!",true))}}
}
function updateHomeDashboard(d){
  homeLastDiag=d;const health=(d.memory_engine.health||{}).status==="ok";const ai=!!d.ai.configured;const global=$("homeGlobalStatus");const healthy=health&&ai&&Number(d.guardian.queued_dead||0)===0;
  global.classList.toggle("attention",!healthy);global.querySelector("span:last-child").textContent=healthy?"Все системы в норме":(!ai?"Требуется настройка DeepSeek":"Есть компоненты, требующие внимания");
  const cpu=Number((d.system||{}).cpu_percent||0),ram=Number(d.system_memory.percent||0),temp=(d.system||{}).cpu_temperature_c;
  $("homeCpu").textContent=cpu.toFixed(1)+"%";$("homeRam").textContent=ram.toFixed(1)+"%";$("homeVram").textContent=(d.system&&d.system.gpu&&d.system.gpu.vram_total_bytes)?fmtBytes(d.system.gpu.vram_used_bytes||0)+" / "+fmtBytes(d.system.gpu.vram_total_bytes):"shared";$("homeTemp").textContent=temp==null?"н/д":Number(temp).toFixed(1)+"°C";
  homePushMetric("cpu",cpu);homePushMetric("ram",ram);homePushMetric("vram",null);homePushMetric("temp",temp);homeSpark("homeCpuSpark",homeTelemetry.cpu,100);homeSpark("homeRamSpark",homeTelemetry.ram,100);homeSpark("homeVramSpark",homeTelemetry.vram,100);homeSpark("homeTempSpark",homeTelemetry.temp,100);
  $("homePulseStamp").textContent=new Date().toLocaleTimeString();const total=Number(d.memory_engine.total||0),personal=Number(d.memory_engine.personal||0),project=Number(d.memory_engine.project||0),coverage=Number((d.memory_engine.health||{}).vector_coverage_percent||0);
  $("homeMemories").textContent=total;$("homePersonalMemory").textContent=personal;$("homeProjectMemory").textContent=project;$("homeVectorCoverage").textContent=coverage+"%";$("homePersonalBar").style.width=homePercentPart(personal,total)+"%";$("homeProjectBar").style.width=homePercentPart(project,total)+"%";$("homeVectorBar").style.width=Math.max(0,Math.min(100,coverage))+"%";$("homeMemoryRing").style.setProperty("--pct",Math.max(0,Math.min(100,coverage))+"%");$("homeMemoryHealth").textContent=health?"health · ok":"health · attention";
  $("homeChats").textContent=d.chat_history.chats||0;$("homeMessages").textContent=d.chat_history.messages||0;$("homeAiRequests").textContent=(d.ai.stats||{}).requests||0;$("homeUptime").textContent=homeUptime(d.backend.uptime_seconds);
  renderHomeTasks();if(homeModules.length)renderHomeBrain();
}
async function refreshDiag(){try{const d=await api("/v1/diagnostics/status");$("brandVersion").textContent=d.backend.version||"—";state($("homeBackend"),"Работает","ok");state($("homeAI"),d.ai.configured?"Подключён":"Не настроен",d.ai.configured?"ok":"warn");state($("homeGuardian"),d.guardian.queued_pending?"Ожидают: "+d.guardian.queued_pending:"Работает",d.guardian.queued_pending?"warn":"ok");updateHomeDashboard(d);
state($("dBackend"),"Работает","ok");state($("dAI"),d.ai.configured?"Подключён":"Нет ключа",d.ai.configured?"ok":"warn");state($("dGuardian"),"Работает","ok");state($("dMemoryAuto"),d.memory_automation.started?(d.memory_automation.running?"Выполняется":"Активна"):"Выключена",d.memory_automation.started?"ok":"warn");state($("dGuardianAuto"),d.guardian_automation.started?(d.guardian_automation.running?"Выполняется":"Активна"):"Выключена",d.guardian_automation.started?"ok":"warn");
$("dRam").textContent=fmtBytes(d.system_memory.used_bytes)+" / "+fmtBytes(d.system_memory.total_bytes)+" ("+d.system_memory.percent+"%)";$("dProcessRam").textContent=fmtBytes(d.process.rss_bytes);$("dDisk").textContent=fmtBytes(d.disk.free_bytes);$("dChats").textContent=d.chat_history.chats+" чатов / "+d.chat_history.messages+" сообщений";
$("mTotal").textContent=d.memory_engine.total;$("mActive").textContent=d.memory_engine.active;$("mArchived").textContent=d.memory_engine.archived;$("mSuperseded").textContent=d.memory_engine.superseded;$("mPersonal").textContent=d.memory_engine.personal;$("mProject").textContent=d.memory_engine.project;const mh=d.memory_engine.health||{};state($("mHealth"),mh.status==="ok"?"OK":(mh.status==="warning"?"Предупреждение":"Ошибка"),mh.status==="ok"?"ok":(mh.status==="warning"?"warn":"bad"));$("mVectors").textContent=(mh.active_vectors||0)+" · "+(mh.vector_coverage_percent||0)+"%";$("mDb").textContent=fmtBytes(d.memory_engine.database_bytes);
$("qPending").textContent=d.guardian.queued_pending;$("qApplied").textContent=d.guardian.queued_applied;$("qRejected").textContent=d.guardian.queued_rejected;$("qDead").textContent=d.guardian.queued_dead;$("autoErrors").textContent=(d.memory_automation.failure_count||0)+(d.guardian_automation.failure_count||0);$("diagStatus").textContent="Обновлено: "+new Date().toLocaleTimeString()}catch(e){state($("homeBackend"),"Ошибка","bad");state($("dBackend"),"Ошибка","bad");$("diagStatus").textContent=e.message}}
$("refreshDiag").onclick=refreshDiag;$("checkMemoryHealth").onclick=()=>withBusyButton("checkMemoryHealth","Проверяю…",async()=>{try{$("diagStatus").textContent="Глубокая проверка памяти…";const h=await api("/v1/memory/health?deep=true");state($("mHealth"),h.status==="ok"?"OK":(h.status==="warning"?"Предупреждение":"Ошибка"),h.status==="ok"?"ok":(h.status==="warning"?"warn":"bad"));$("mVectors").textContent=(h.active_vectors||0)+" · "+(h.vector_coverage_percent||0)+"%";$("diagStatus").textContent="Память: "+h.status.toUpperCase()+" · SQLite: "+h.integrity+" · FK ошибок: "+h.foreign_key_errors+" · неверных scope: "+h.invalid_scope_rows+" · orphan: "+(h.orphan_vectors+h.orphan_links+h.orphan_history)}catch(e){$("diagStatus").textContent="Ошибка проверки памяти: "+e.message}});$("runMaintenance").onclick=()=>withBusyButton("runMaintenance","Обслуживание…",async()=>{try{$("diagStatus").textContent="Обслуживание…";await api("/v1/memory/maintenance/run",{method:"POST"});await refreshDiag()}catch(e){$("diagStatus").textContent=e.message}});
async function loadSettings(){try{const [d,modules]=await Promise.all([api("/v1/settings/ai/deepseek"),api("/v1/settings/modules")]);$("apiKey").value="";$("apiKey").placeholder=d.configured?"Ключ сохранён ••••••••":"Вставьте Key Secret";$("settingsStatus").textContent=d.configured?"DeepSeek настроен"+(d.registered?" и активен.":"."):"API-ключ пока не сохранён.";const box=$("moduleRegistryList");box.innerHTML="";$("moduleRegistryCount").textContent=(modules.items||[]).length+" модулей";(modules.items||[]).forEach(item=>{const row=document.createElement("div");row.className="module-document";const left=document.createElement("div");const title=document.createElement("div");title.className="cloud-name";title.textContent=item.title+" · v"+item.version;const meta=document.createElement("div");meta.className="cloud-sub";meta.textContent=item.description+" Последнее: "+item.last_update;left.append(title,meta);const dep=document.createElement("div");dep.className="cloud-badge";dep.textContent=item.depends_on&&item.depends_on.length?"Связи: "+item.depends_on.join(", "):"Независимый";row.append(left,dep);box.append(row)})}catch(e){$("settingsStatus").textContent=e.message}}
$("saveSettings").onclick=()=>withBusyButton("saveSettings","Сохраняю…",async()=>{const key=$("apiKey").value.trim();if(!key){$("settingsStatus").textContent="Вставьте Key Secret.";return}try{$("settingsStatus").textContent="Сохранение…";const d=await api("/v1/settings/ai/deepseek",{method:"POST",body:JSON.stringify({api_key:key})});$("apiKey").value="";$("apiKey").placeholder="Ключ сохранён ••••••••";$("settingsStatus").textContent=d.registered?"Сохранено. DeepSeek активен без перезапуска.":"Сохранено.";await refreshDiag()}catch(e){$("settingsStatus").textContent="Ошибка: "+e.message}});
$("testSettings").onclick=()=>withBusyButton("testSettings","Проверяю…",async()=>{try{$("settingsStatus").textContent="Проверка API…";const d=await api("/v1/settings/ai/deepseek/test",{method:"POST"});$("settingsStatus").textContent="API работает: "+d.provider+" / "+d.model+" → "+d.response}catch(e){$("settingsStatus").textContent="Ошибка API: "+e.message}});

let updateWasStarted=false;
let updatePollTimer=null;
const phaseNames={idle:"Готово",checking:"Проверка GitHub…",current:"Актуальная версия",available:"Доступно обновление",starting:"Запуск процесса…",downloading:"Скачивание…",extracting:"Распаковка и сверка…",backing_up:"Резервная копия…",stopping:"Остановка…",installing:"Установка…",restarting:"Перезапуск…",verifying:"Проверка новой версии…",rolling_back:"Автоматический откат…",success:"Обновлено",failed:"Ошибка обновления",error:"Ошибка проверки"};
function renderFiles(id,files){const box=$(id);box.innerHTML="";if(!files||!files.length){box.textContent="Нет файлов.";return}files.forEach(name=>{const row=document.createElement("div");row.textContent=name;box.appendChild(row)})}
function fmtUpdateDate(value){if(!value)return"—";const d=new Date(value);return Number.isNaN(d.getTime())?value:d.toLocaleString()}
function renderUpdate(d){
  const phase=phaseNames[d.phase]||d.message||d.phase||"—";
  state($("updateState"),phase,d.phase==="available"?"warn":(["failed","error"].includes(d.phase)?"bad":(["success","current"].includes(d.phase)?"ok":"")));
  $("updateLocal").textContent=d.local_version||"—";
  $("updateRemote").textContent=d.remote_version||"—";
  $("updateSha").textContent=d.remote_sha?d.remote_sha.slice(0,12):"—";
  const pct=Math.max(0,Math.min(100,Number(d.progress_percent||0)));
  $("updatePercent").textContent=pct+"%";
  $("updateProgressBar").style.width=pct+"%";
  $("updateProgress").textContent=d.error?d.error:(d.message||"Автопроверка включена.");
  $("updateHeartbeat").textContent=(d.heartbeat_at?"Последний статус: "+fmtUpdateDate(d.heartbeat_at):"")+(d.stalled?" · ВНИМАНИЕ: процесс не передаёт статус более 3 минут.":"");
  $("installUpdate").disabled=!d.update_available||!!d.running;
  $("checkUpdate").disabled=!!d.running;
  const downloaded=d.downloaded_files||[],changed=d.changed_files||[],fresh=d.new_files||[],removed=d.removed_files||[];
  $("filesDownloadedCount").textContent=downloaded.length;$("filesChangedCount").textContent=changed.length;$("filesNewCount").textContent=fresh.length;$("filesRemovedCount").textContent=removed.length;
  renderFiles("downloadedFiles",downloaded);renderFiles("changedFiles",changed);renderFiles("newFiles",fresh);renderFiles("removedFiles",removed);
  if(d.running)startUpdatePolling();
  if(updateWasStarted&&d.phase==="success"){updateWasStarted=false;refreshUpdateHistory();setTimeout(()=>location.reload(),1200)}
}
async function updateStatus(){
  try{renderUpdate(await api("/v1/update/status"))}
  catch(e){if(updateWasStarted){state($("updateState"),"Перезапуск…","warn");$("updateProgress").textContent="Сервер временно недоступен. Жду автоматического запуска…";startUpdatePolling()}else{state($("updateState"),"Недоступно","bad");$("updateProgress").textContent=e.message;$("checkUpdate").disabled=false;$("installUpdate").disabled=true}}
}
async function refreshUpdateHistory(){
  try{const d=await api("/v1/update/history?limit=30");const box=$("updateHistory");box.innerHTML="";if(!d.items.length){box.innerHTML='<div class="card muted">История пока пуста.</div>';return}d.items.forEach(item=>{const el=document.createElement("div");el.className="history-item";const ok=item.result==="success";const files=(item.downloaded_files||[]).length;el.innerHTML='<div class="history-head"><div><div class="history-title '+(ok?"ok":"bad")+'">'+(item.description||"Обновление")+'</div><div class="update-meta">'+(item.from_version||"—")+' → '+(item.to_version||"—")+(item.sha?" · "+item.sha.slice(0,10):"")+'</div></div><div class="history-date">'+fmtUpdateDate(item.finished_at)+'</div></div><div class="update-meta" style="margin-top:8px">Скачано файлов: '+files+' · изменено: '+((item.changed_files||[]).length)+' · новых: '+((item.new_files||[]).length)+' · удалено: '+((item.removed_files||[]).length)+(item.rolled_back?" · выполнен автоматический откат":"")+'</div>'+(item.error?'<div class="statusbar bad">'+item.error+'</div>':"");box.appendChild(el)})}catch(e){$("updateHistory").innerHTML='<div class="card bad">Не удалось загрузить историю: '+e.message+'</div>'}
}
async function checkForUpdate(){
  $("checkUpdate").disabled=true;
  try{renderUpdate(await api("/v1/update/check",{method:"POST"}));await refreshUpdateHistory()}
  catch(e){state($("updateState"),"Ошибка проверки","bad");$("updateProgress").textContent=e.message}
  finally{await updateStatus()}
}
async function installUpdate(){
  if(!confirm("Скачать и установить обновление Дракончика Тоору? Локальная память, ключи, runtime и журналы будут сохранены."))return;
  updateWasStarted=true;$("installUpdate").disabled=true;$("checkUpdate").disabled=true;
  try{
    renderUpdate(await api("/v1/update/install",{method:"POST",body:JSON.stringify({force:false})}));
    startUpdatePolling();
  }catch(e){
    state($("updateState"),"Проверка процесса…","warn");
    $("updateProgress").textContent="Соединение с сервером прервалось. Это нормально при перезапуске; проверяю состояние обновления…";
    startUpdatePolling();
  }
}
function startUpdatePolling(){
  if(updatePollTimer)return;
  updatePollTimer=setInterval(async()=>{try{const d=await api("/v1/update/status");renderUpdate(d);if(!d.running&&["success","failed","error","current","available"].includes(d.phase)){clearInterval(updatePollTimer);updatePollTimer=null;await refreshUpdateHistory()}}catch{state($("updateState"),"Перезапуск…","warn");$("updateProgress").textContent="Сервер временно недоступен. Жду автоматического запуска…"}},2000)
}
$("checkUpdate").onclick=checkForUpdate;
$("installUpdate").onclick=installUpdate;

loadHomeDashboard();refreshDiag();setInterval(refreshDiag,3000);setInterval(()=>{if($("home").classList.contains("active"))refreshHomeObservability()},1800);
updateStatus();setTimeout(checkForUpdate,1200);setInterval(checkForUpdate,600000);

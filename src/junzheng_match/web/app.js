/**
 * SJTU 䇹政盲审导师匹配与数据库维护平台 — 前端交互逻辑 (app.js)
 * 特性：
 * 1. 匹配预览与数据库表均采用固定列宽、固定单元格高度、无任何内部滚动条
 * 2. 匹配预览中的「同学课题」支持 2–3 行自然换行完整显示；「学生学号」以前三位加省略号显示
 * 3. 匹配预览中导师与评审学院显示简称（如电院、数院、高金），数据库与导出保留去掉“上海交通大学”前缀后的完整院系名
 * 4. 数据库院系概览按拼音A–Z排列；新增/编辑教师弹窗提供已有院系下拉选项，若输入未出现过的新院系则实时警告并二次确认
 */

let currentMatchFileBase64 = "";
let currentMatchFilename = "";
let currentMatchData = null;
let previewViewMode = "merged"; // "merged" (合并单元格视图) | "horizontal" (横式单行视图)

// 匹配预览分页状态
let matchCurrentPage = 1;
const MATCH_PAGE_SIZE_MERGED = 5;      // 合并视图每页显示 5 名学生（约 15 行，刚好一屏无内部滚动条）
const MATCH_PAGE_SIZE_HORIZONTAL = 10; // 横式单行视图每页显示 10 名学生

let currentMergeFileBase64 = "";
let currentMergeFilename = "";

// 数据库分页与已知院系集合
let dbCurrentPage = 1;
let dbTotalPages = 1;
const DB_PAGE_SIZE = 15;
let dbCurrentItems = [];
let knownCollegesSet = new Set();
let scriptPollTimer = null;

// 前端院系前缀清理辅助函数
function stripSjtuPrefix(name) {
  let s = String(name || "").trim();
  for (const prefix of ["上海交通大学", "上海交大"]) {
    if (s.startsWith(prefix)) {
      s = s.slice(prefix.length).trim();
    }
  }
  return s;
}

// 短字段按整份结果测量后固定像素宽度；长字段分配剩余空间。
function formatShortStudentId(sid) { const value=String(sid || "").trim(); return value.length>3 ? value.slice(0,3)+"..." : value||"-"; }
const widthCanvas = document.createElement("canvas");
function fittedWidth(header, values, {mono=false,bold=false,extra=0}={}) {
  const ctx = widthCanvas.getContext("2d");
  const css=getComputedStyle(document.documentElement);
  ctx.font=`600 12px ${css.getPropertyValue("--font-sans")}`;
  let max=ctx.measureText(header).width;
  ctx.font=`${bold?600:400} ${mono?11.5:12.5}px ${css.getPropertyValue(mono?"--font-mono":"--font-sans")}`;
  for (const value of values) max=Math.max(max,ctx.measureText(String(value || "-")).width+extra);
  return Math.ceil(max)+18; // 左右8px内边距+边框；不使用百分比压缩短字段。
}
function fittedColumns(specs, availableWidth, compact=false) {
  availableWidth=Math.max(0,availableWidth-2); // 容器边框，不占用短字段宽度。
  const widths=specs.map(s=>s.width||s.min||120);
  const base=widths.reduce((a,b)=>a+b,0);
  const weights=specs.reduce((n,s)=>n+(s.width?0:(s.weight||1)),0);
  if (availableWidth>base && weights) specs.forEach((s,i)=>{if(!s.width)widths[i]+=(availableWidth-base)*(s.weight||1)/weights;});
  if(compact && base>availableWidth){const fixed=specs.reduce((n,s)=>n+(s.width||0),0); const flexible=specs.reduce((n,s)=>n+(s.width?0:(s.min||120)),0); specs.forEach((s,i)=>{if(!s.width)widths[i]=(s.min||120)*Math.max(0,availableWidth-fixed)/flexible;});}
  const integers=widths.map(Math.floor);
  let remainder=Math.max(0,Math.round(widths.reduce((a,b)=>a+b,0))-integers.reduce((a,b)=>a+b,0));
  specs.forEach((s,i)=>{if(!s.width&&remainder>0){integers[i]++;remainder--;}});
  return {html:integers.map((w,i)=>`<col data-fit="${specs[i].width?"fixed":"flex"}" style="width:${w}px"/>`).join(""),width:integers.reduce((a,b)=>a+b,0)};
}
function labelPreviewCells(){
  const table=document.querySelector("#match-preview-wrap table");if(!table)return;
  const headers=Array.from(table.querySelectorAll("thead th"),e=>e.textContent.trim());
  const spans=[];
  for(const row of table.querySelectorAll("tbody tr")){
    let col=0;
    for(const cell of row.cells){
      while(spans[col]>0)col++;
      cell.dataset.label=headers[col]||"";
      for(let n=0;n<cell.colSpan;n++)spans[col+n]=cell.rowSpan;
      col+=cell.colSpan;
    }
    for(let i=0;i<spans.length;i++)if(spans[i]>0)spans[i]--;
  }
}
function applyDatabaseWidths() {
  const table=document.getElementById("db-faculty-table");if(!table)return;
  const rows=dbLayoutSamples.length?dbLayoutSamples:dbCurrentItems;
  const specs=[
    {width:fittedWidth("序号/ID",["#99999"],{mono:true})},
    {width:Math.min(100,fittedWidth("姓名",rows.map(r=>r.name),{bold:true,extra:15}))},
    {width:Math.min(112,fittedWidth("职称",rows.map(r=>r.title),{extra:18}))},
    {width:140},
    {width:Math.min(220,fittedWidth("邮箱 / 电话",rows.map(r=>r.email||r.phone||r.mobile||"-")))},
    {min:340,weight:1}, {width:100}
  ];
  const fitted=fittedColumns(specs,table.parentElement.clientWidth,true);
  table.querySelector("colgroup").innerHTML=fitted.html;table.style.width=`${fitted.width}px`;
}
let dbLayoutSamples=[];
let fitResizeTimer;
window.addEventListener("resize",()=>{clearTimeout(fitResizeTimer);fitResizeTimer=setTimeout(()=>{if(currentMatchData)renderMatchPreviewTable();applyDatabaseWidths();},100);});
document.fonts.ready.then(()=>{if(currentMatchData)renderMatchPreviewTable();applyDatabaseWidths();});

// ==================== 页面与导航切换 ====================
function switchPage(pageKey) {
  document.querySelectorAll(".page-view").forEach((el) => el.classList.remove("active"));
  document.getElementById("nav-match").classList.remove("active");
  document.getElementById("nav-db").classList.remove("active");
  document.getElementById("nav-preferences").classList.remove("active");

  if(pageKey === "preferences"){
    document.getElementById("page-preferences").classList.add("active");document.getElementById("nav-preferences").classList.add("active");loadPreferences();
  } else if (pageKey === "db") {
    document.getElementById("page-db").classList.add("active");
    document.getElementById("nav-db").classList.add("active");
    loadDbStats();
    loadFacultyList(dbCurrentPage);
  } else {
    document.getElementById("page-match").classList.add("active");
    document.getElementById("nav-match").classList.add("active");
  }
  refreshSlidingTabs();
}

function switchDbSubtab(subKey) {
  const keys = ["browse", "merge", "colleges"];
  keys.forEach((k) => {
    const view = document.getElementById(`db-subview-${k}`);
    const btn = document.getElementById(`subtab-btn-${k}`);
    if (k === subKey) {
      view.style.display = "block";
      btn.classList.add("active");
    } else {
      view.style.display = "none";
      btn.classList.remove("active");
    }
  });
  if (subKey === "merge") {
    refreshScriptTasks();
  }
  refreshSlidingTabs();
}

function toggleParamsDrawer() {
  const drawer = document.getElementById("params-drawer");
  drawer.classList.toggle("open");
  updateParamsSummaryLabel();
}

function updateParamsSummaryLabel() {
  const isOpen=document.getElementById('params-drawer').classList.contains('open');
  document.getElementById('params-summary-label').textContent=`匹配参数 ${isOpen?'▴':'▾'}`;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ==================== 顶部 README & ARCHITECTURE 查看器（带左侧 TOC 目录） ====================
async function openDocModal(docName, section = "") {
  const modal = document.getElementById("doc-modal");
  const titleEl = document.getElementById("doc-modal-title");
  const contentEl = document.getElementById("doc-modal-content");
  const tocEl = document.getElementById("doc-modal-toc");
  modal.classList.add("open");
  titleEl.textContent = docName === "ARCHITECTURE" ? "ARCHITECTURE.md — 技术架构详解" : "README.md — 操作指南";
  contentEl.innerHTML = "正在加载文档...";
  if (tocEl) tocEl.innerHTML = "";

  try {
    const resp = await fetch(`/api/docs?name=${encodeURIComponent(docName)}`);
    const data = await resp.json();
    const rendered = renderMarkdownWithToc(data.content || "");
    contentEl.innerHTML = rendered.html;
    if (tocEl) {
      tocEl.innerHTML = rendered.toc
        .map(
          (item) =>
            `<a class="toc-item toc-h${item.level}" onclick="scrollToDocHeading('${item.id}')" title="${escapeHtml(item.text)}">${escapeHtml(item.text)}</a>`
        )
        .join("");
    }
    const pane = document.getElementById("doc-content-pane");
    if (pane) pane.scrollTop = 0;
    if(section){const heading=rendered.toc.find(item=>item.text===section);if(heading)requestAnimationFrame(()=>scrollToDocHeading(heading.id));}
  } catch (err) {
    contentEl.innerHTML = `<div style="color:#c2410c;">加载失败: ${escapeHtml(err.message)}</div>`;
  }
}

function scrollToDocHeading(id) {
  const el = document.getElementById(id);
  const pane = document.getElementById('doc-content-pane');
  if (el && pane) {
    pane.scrollTo({top:pane.scrollTop+el.getBoundingClientRect().top-pane.getBoundingClientRect().top-20,behavior:'instant'});
  }
}

function closeDocModal() {
  document.getElementById("doc-modal").classList.remove("open");
}

function renderMarkdownWithToc(md) {
  const codeBlocks = [];
  let text = md.replace(/```([\s\S]*?)```/g, (_, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre><code>${escapeHtml(code.replace(/^[a-zA-Z0-9_-]+\n/, ""))}</code></pre>`);
    return `@@CODEBLOCK_${idx}@@`;
  });

  const lines = text.split("\n");
  let html = [];
  let toc = [];
  let headingSeq = 0;
  let inTable = false;
  let tableRows = [];

  function flushTable() {
    if (!inTable || !tableRows.length) return;
    let tbl = "<table>";
    tableRows.forEach((r, idx) => {
      const cells = r
        .trim()
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((c) => c.trim());
      if (idx === 1 && cells.every((c) => /^[-:]+$/.test(c))) return;
      const tag = idx === 0 ? "th" : "td";
      tbl += "<tr>" + cells.map((c) => `<${tag}>${formatInline(c)}</${tag}>`).join("") + "</tr>";
    });
    tbl += "</table>";
    html.push(tbl);
    inTable = false;
    tableRows = [];
  }

  function formatInline(s) {
    return escapeHtml(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([^\]]+)\]\((https:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      inTable = true;
      tableRows.push(line);
      continue;
    } else if (inTable) {
      flushTable();
    }

    if (/^@@CODEBLOCK_\d+@@$/.test(line.trim())) {
      const idx = parseInt(line.trim().replace(/\D/g, ""), 10);
      html.push(codeBlocks[idx]);
    } else if (line.startsWith("### ")) {
      headingSeq++;
      const hText = line.slice(4).trim();
      const hid = `doc-h-${headingSeq}`;
      toc.push({ id: hid, level: 3, text: hText });
      html.push(`<h3 id="${hid}">${formatInline(hText)}</h3>`);
    } else if (line.startsWith("## ")) {
      headingSeq++;
      const hText = line.slice(3).trim();
      const hid = `doc-h-${headingSeq}`;
      toc.push({ id: hid, level: 2, text: hText });
      html.push(`<h2 id="${hid}">${formatInline(hText)}</h2>`);
    } else if (line.startsWith("# ")) {
      headingSeq++;
      const hText = line.slice(2).trim();
      const hid = `doc-h-${headingSeq}`;
      toc.push({ id: hid, level: 1, text: hText });
      html.push(`<h1 id="${hid}">${formatInline(hText)}</h1>`);
    } else if (line.startsWith("- ")) {
      html.push(`<div style="margin-left:16px;">• ${formatInline(line.slice(2))}</div>`);
    } else if (line.trim() === "---") {
      html.push(`<hr style="border:none;border-top:1px solid var(--border-light);margin:14px 0;" />`);
    } else if (line.trim() !== "") {
      html.push(`<p style="margin:6px 0;">${formatInline(line)}</p>`);
    }
  }
  if (inTable) flushTable();
  return { html: html.join("\n"), toc };
}

// ==================== 通用点击分页按钮渲染器 ====================
function buildPaginationButtonsHtml(currentPage, totalPages, onClickFnName) {
  let html = "";
  html += `<button class="page-num-btn" ${currentPage <= 1 ? "disabled" : ""} onclick="${onClickFnName}(${currentPage - 1})">上一页</button>`;

  const pages = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (currentPage > 3) pages.push("...");
    const start = Math.max(2, currentPage - 1);
    const end = Math.min(totalPages - 1, currentPage + 1);
    for (let i = start; i <= end; i++) pages.push(i);
    if (currentPage < totalPages - 2) pages.push("...");
    pages.push(totalPages);
  }

  for (const p of pages) {
    if (p === "...") {
      html += `<span style="padding:0 4px;color:var(--ink-muted);">…</span>`;
    } else {
      const activeCls = p === currentPage ? "active" : "";
      html += `<button class="page-num-btn ${activeCls}" onclick="${onClickFnName}(${p})">${p}</button>`;
    }
  }

  html += `<button class="page-num-btn" ${currentPage >= totalPages ? "disabled" : ""} onclick="${onClickFnName}(${currentPage + 1})">下一页</button>`;
  return html;
}

// ==================== 盲审匹配与文件上传 ====================
function onFilterModeChange() {
  const mode = document.getElementById("param-filter-mode").value;
  const label = document.getElementById("param-filter-value-label");
  const input = document.getElementById("param-filter-value");

  if (mode === "all") {
    label.textContent = "筛选条件值";
    input.value = "";
    input.placeholder = "全部学生无需填写";
    input.disabled = true;
  } else if (mode === "range") {
    label.textContent = "起止序号范围 (--range)";
    input.placeholder = "如: 1-10";
    input.disabled = false;
  } else if (mode === "student") {
    label.textContent = "单个学生序号 (--student)";
    input.placeholder = "如: 3";
    input.disabled = false;
  } else if (mode === "name") {
    label.textContent = "学生姓名关键词 (--name)";
    input.placeholder = "如: 朱耔润";
    input.disabled = false;
  }
  updateParamsSummaryLabel();
}

function resetMatchParams() {
  document.getElementById("param-filter-mode").value = "all";
  document.getElementById("param-filter-value").value = "";
  document.getElementById("param-pick").value = "3";
  document.getElementById("param-max-uses").value = "2";
  document.getElementById("param-pool").value = "20";
  document.getElementById("param-strategy").value = "top";
  document.getElementById("param-seed").value = "42";
  document.getElementById("param-min-score").value = "0.05";
  document.getElementById("param-rel-score").value = "0.4";
  document.getElementById("param-strict").checked = false;
  document.getElementById("param-allow-unknown").checked = false;
  onFilterModeChange();
}

function onMatchFileSelected(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  readFileToBase64(file, (b64) => {
    currentMatchFileBase64 = b64;
    currentMatchFilename = file.name;
    document.getElementById("match-file-label").textContent = `已选择文件：${file.name}`;
  });
}

function readFileToBase64(file, callback) {
  const reader = new FileReader();
  reader.onload = () => callback(reader.result);
  reader.readAsDataURL(file);
}

// 绑定拖拽上传与初始化
window.addEventListener("DOMContentLoaded", () => {
  const dz = document.getElementById("match-dropzone");
  if (dz) {
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
      const file = e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) {
        readFileToBase64(file, (b64) => {
          currentMatchFileBase64 = b64;
          currentMatchFilename = file.name;
          document.getElementById("match-file-label").textContent = `已选择文件：${file.name}`;
        });
      }
    });
  }
  loadDbStats();
  initializeApplication();
});

function collectMatchParams() {
  const mode = document.getElementById("param-filter-mode").value;
  const val = document.getElementById("param-filter-value").value.trim();
  const params = {
    filter_mode: mode,
    pool_size: parseInt(document.getElementById("param-pool").value || "20", 10),
    max_teacher_uses: Number(document.getElementById("param-max-uses").value),
    pick_count: parseInt(document.getElementById("param-pick").value || "3", 10),
    strategy: document.getElementById("param-strategy").value,
    seed: parseInt(document.getElementById("param-seed").value || "42", 10),
    min_score: parseFloat(document.getElementById("param-min-score").value || "0.05"),
    relative_score: parseFloat(document.getElementById("param-rel-score").value || "0.4"),
    strict: document.getElementById("param-strict").checked,
    allow_unknown_title: document.getElementById("param-allow-unknown").checked,
  };
  if (mode === "range") params.range_str = val;
  if (mode === "student") params.student_seq = parseInt(val || "1", 10);
  if (mode === "name") params.student_name = val;
  return params;
}

function setPreviewCollapsed(collapsed) {
  const card=document.getElementById('match-result-card');
  const button=document.getElementById('btn-fold-preview');
  const content=document.getElementById('match-preview-content');
  if(!card||!button||!content)return;
  card.classList.toggle('is-collapsed',collapsed);
  content.hidden=collapsed;
  button.setAttribute('aria-expanded',String(!collapsed));
  button.setAttribute('aria-label',collapsed?'展开预览':'收起预览');
  button.title=collapsed?'展开预览':'收起预览';
  if(!collapsed&&currentMatchData)requestAnimationFrame(()=>renderMatchPreviewTable());
}
function togglePreviewCollapsed() {
  setPreviewCollapsed(!document.getElementById('match-preview-content').hidden);
}

async function runMatch(useSample = false) {
  if (!useSample && !currentMatchFileBase64) {
    alert("请先上传学生课题表（.xlsx 或 .csv），或点击「载入示例表」！");
    return;
  }

  const btn = document.getElementById("btn-run-match");
  const wrap = document.getElementById("match-preview-wrap");
  document.getElementById("page-match").classList.remove("is-empty");
  setPreviewCollapsed(false);
  btn.disabled = true;
  btn.textContent = "匹配计算中...";
  wrap.innerHTML = `<div style="padding:48px 20px;text-align:center;color:var(--ink-secondary);">正在运行 TF-IDF 学科扩展匹配引擎，请稍候...</div>`;

  try {
    const payload = {
      use_sample: useSample,
      filename: useSample ? "虚构学生示例.xlsx" : currentMatchFilename,
      file_base64: useSample ? "" : currentMatchFileBase64,
      params: collectMatchParams(),
    };

    const resp = await fetch("/api/match/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      throw new Error(data.error || "匹配失败");
    }

    currentMatchData = data;
    matchCurrentPage = 1;
    updateMatchStatsUI(data);
    renderMatchPreviewTable();

    document.getElementById("btn-toggle-view").disabled = false;
    document.getElementById("btn-export-csv").disabled = false;
    document.getElementById("btn-export-xlsx").disabled = false;
  } catch (err) {
    wrap.innerHTML = `<div style="padding:42px 20px;text-align:center;color:#c2410c;font-weight:600;">匹配出错：${escapeHtml(err.message)}</div>`;
    document.getElementById("match-pagination-bar").style.display = "none";
  } finally {
    btn.disabled = false;
    btn.textContent = "匹配预览";
  }
}

function updateMatchStatsUI(data) {
  document.getElementById("match-stats-bar").style.display = "flex";
  document.getElementById("stat-stu-count").textContent = data.total_matched_students;
  document.getElementById("stat-full-count").textContent = `${data.matched_full}/${data.total_matched_students}`;
  document.getElementById("stat-rev-count").textContent = data.unique_reviewers_used;
  document.getElementById("stat-elapsed").textContent = `${data.elapsed_sec}s`;
  document.getElementById("match-summary-text").textContent = `${data.filename} · 每位教师上限 ${data.max_teacher_uses} 次${data.matched_full<data.total_matched_students?" · 候选不足的位置已留空，请调整次数上限或匹配参数":""}`;
}

function togglePreviewMode() {
  previewViewMode = previewViewMode === "merged" ? "horizontal" : "merged";
  matchCurrentPage = 1;
  const btn = document.getElementById("btn-toggle-view");
  btn.textContent = previewViewMode === "merged" ? "视图：合并单元格 ⇄ 横式单行" : "视图：横式单行 ⇄ 合并单元格";
  renderMatchPreviewTable();
}

function goMatchPage(p) {
  matchCurrentPage = p;
  renderMatchPreviewTable();
}

function renderMatchPreviewTable() {
  const wrap = document.getElementById("match-preview-wrap");
  const pagBar = document.getElementById("match-pagination-bar");
  if (!currentMatchData || !currentMatchData.items || !currentMatchData.items.length) {
    wrap.innerHTML = `<div style="padding:48px;text-align:center;color:var(--ink-muted);">未筛选到符合条件的学生记录</div>`;
    pagBar.style.display = "none";
    return;
  }

  const allItems = currentMatchData.items;
  const pickCount = currentMatchData.pick_count || 3;
  const pageSize = previewViewMode === "merged" ? MATCH_PAGE_SIZE_MERGED : MATCH_PAGE_SIZE_HORIZONTAL;
  const totalPages = Math.max(1, Math.ceil(allItems.length / pageSize));
  if (matchCurrentPage > totalPages) matchCurrentPage = totalPages;
  if (matchCurrentPage < 1) matchCurrentPage = 1;

  const startIdx = (matchCurrentPage - 1) * pageSize;
  const pageItems = allItems.slice(startIdx, startIdx + pageSize);

  // 更新底部分页条
  pagBar.style.display = "flex";
  document.getElementById("match-page-info").textContent =
    `共 ${allItems.length} 名学生 · 当前显示第 ${startIdx + 1}–${Math.min(startIdx + pageSize, allItems.length)} 名 · 第 ${matchCurrentPage} / ${totalPages} 页`;
  document.getElementById("match-page-btns").innerHTML = buildPaginationButtonsHtml(
    matchCurrentPage,
    totalPages,
    "goMatchPage"
  );

  if (previewViewMode === "horizontal") {
    // 横式单行展开视图：课题支持 2-3 行自然换行完整显示，学号显示前三位+…，导师与评审学院显示简称
    const kShow = Math.min(pickCount, 4);
    const fixed=[
      {width:fittedWidth("序号",allItems.map(s=>s.seq))},
      {width:fittedWidth("姓名",allItems.map(s=>s.name),{bold:true})},
      {width:fittedWidth("学号",allItems.map(s=>formatShortStudentId(s.student_id)),{mono:true})},
      {min:180,weight:2},
      {width:fittedWidth("导师",allItems.map(s=>s.advisor))},
      {min:80,weight:.6},
      ...Array.from({length:kShow},()=>({min:180,weight:1}))
    ];
    const horizontalFit=fittedColumns(fixed,wrap.clientWidth,true);
    const colgroup=horizontalFit.html;

    let ths = `
      <th>序号</th>
      <th>姓名</th>
      <th>学号</th>
      <th>课题中文</th>
      <th>导师</th>
      <th>导师院系</th>
    `;
    for (let k = 1; k <= kShow; k++) {
      ths += `<th>评审${k}（姓名 · 学院 · 职称 · 相近度）</th>`;
    }

    let trs = "";
    for (const s of pageItems) {
      const shortSid = formatShortStudentId(s.student_id);
      const shortAdvDept = s.short_advisor_dept || s.advisor_dept || "-";
      let rowHtml = `
        <td title="${escapeHtml(s.seq)}">${escapeHtml(s.seq)}</td>
        <td style="font-weight:600;" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</td>
        <td style="font-family:var(--font-mono);font-size:11.5px;color:var(--ink-secondary);" title="完整学号: ${escapeHtml(s.student_id)}">${escapeHtml(shortSid)}</td>
        <td class="topic-wrap-cell" title="${escapeHtml(s.topic)}"><div class="topic-clamp-box">${escapeHtml(s.topic)}</div></td>
        <td title="${escapeHtml(s.advisor)}">${escapeHtml(s.advisor)}</td>
        <td title="完整院系: ${escapeHtml(s.advisor_dept)}">${escapeHtml(shortAdvDept)}</td>
      `;
      for (let j = 0; j < kShow; j++) {
        const rev = s.reviewers[j];
        if (rev) {
          const shortRevDept = rev.short_department || rev.department || "-";
          const fullTip = `姓名: ${rev.name}\n院系: ${rev.department}\n职称: ${rev.title}\n邮箱: ${rev.email}\n电话: ${rev.phone}\n研究方向: ${rev.research_direction}\n匹配方向: ${rev.match_direction}\n相近程度: ${rev.similarity.toFixed(4)}`;
          rowHtml += `
            <td title="${escapeHtml(fullTip)}">
              <div class="cell-clip">
                <strong style="color:var(--orange-deep-text);">${escapeHtml(rev.name)}</strong>
                <span style="color:var(--ink-secondary);margin-left:4px;">${escapeHtml(shortRevDept)} · ${escapeHtml(rev.title)}</span>
                <span class="score-pill" style="margin-left:4px;">${rev.similarity.toFixed(3)}</span>
              </div>
            </td>
          `;
        } else {
          rowHtml += `<td>-</td>`;
        }
      }
      trs += `<tr>${rowHtml}</tr>`;
    }

    wrap.innerHTML = `<table class="fixed-table" style="width:${horizontalFit.width}px"><colgroup>${colgroup}</colgroup><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
    labelPreviewCells();
    return;
  }

  // 默认：合并单元格原表视图
  // 同学课题中文用 2-3 行完整表示；学号仅显示前三位 + …；导师院系与评审学院均用简称（如电院、数院、高金）
  const reviewers=allItems.flatMap(s=>s.reviewers);
  const specs=[
    {width:fittedWidth("序号",allItems.map(s=>s.seq))},
    {width:fittedWidth("课题类别",allItems.map(s=>s.category))},
    {width:fittedWidth("学生姓名",allItems.map(s=>s.name),{bold:true})},
    {width:fittedWidth("学号",allItems.map(s=>formatShortStudentId(s.student_id)),{mono:true})},
    {min:170,weight:2},
    {width:fittedWidth("导师",allItems.map(s=>s.advisor))},
    {min:76,weight:.7},
    {width:fittedWidth("拟定评审",reviewers.map(r=>r.name),{bold:true})},
    {min:76,weight:.7},
    {width:fittedWidth("职称",reviewers.map(r=>r.title))},
    {min:135,weight:.8}, {min:150,weight:1.2}, {width:fittedWidth("匹配方向",["课题方向"],{extra:12})},
    {width:fittedWidth("相近度",["0.000"],{mono:true,bold:true,extra:12})}
  ];
  const mergedFit=fittedColumns(specs,wrap.clientWidth,true);
  let html = `
    <table class="fixed-table" style="width:${mergedFit.width}px">
      <colgroup>${mergedFit.html}</colgroup>
      <thead>
        <tr>
          <th style="text-align:center;">序号</th>
          <th>课题类别</th>
          <th>学生姓名</th>
          <th>学号</th>
          <th>课题中文</th>
          <th>导师</th>
          <th>导师院系</th>
          <th>拟定评审</th>
          <th>评审学院</th>
          <th>职称</th>
          <th>邮箱 / 电话</th>
          <th>研究方向</th>
          <th>匹配方向</th>
          <th style="text-align:center;">相近度</th>
        </tr>
      </thead>
      <tbody>
  `;

  for (const s of pageItems) {
    const k = Math.max(pickCount, s.reviewers.length, 1);
    const shortSid = formatShortStudentId(s.student_id);
    const shortAdvDept = s.short_advisor_dept || s.advisor_dept || "-";
    for (let j = 0; j < k; j++) {
      const rev = s.reviewers[j];
      html += `<tr>`;
      if (j === 0) {
        html += `
          <td rowspan="${k}" class="merged-student-cell" style="text-align:center;" title="序号: ${escapeHtml(s.seq)}">${escapeHtml(s.seq)}</td>
          <td rowspan="${k}" class="merged-student-cell" title="${escapeHtml(s.category)}">${escapeHtml(s.category)}</td>
          <td rowspan="${k}" class="merged-student-cell" style="font-weight:600;" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</td>
          <td rowspan="${k}" class="merged-student-cell" style="font-family:var(--font-mono);font-size:11.5px;color:var(--ink-secondary);" title="完整学号: ${escapeHtml(s.student_id)}">${escapeHtml(shortSid)}</td>
          <td rowspan="${k}" class="merged-student-cell topic-wrap-cell" title="${escapeHtml(s.topic)}"><div class="topic-clamp-box">${escapeHtml(s.topic)}</div></td>
          <td rowspan="${k}" class="merged-student-cell" title="${escapeHtml(s.advisor)}">${escapeHtml(s.advisor)}</td>
          <td rowspan="${k}" class="merged-student-cell" title="完整院系: ${escapeHtml(s.advisor_dept)}">${escapeHtml(shortAdvDept)}</td>
        `;
      }
      if (rev) {
        const badgeCls = rev.match_level.includes("低置信")
          ? "badge-warning"
          : rev.match_level.includes("相近")
          ? "badge-info"
          : "badge-success";
        const contactStr = rev.email || rev.phone || "-";
        const contactTip = [rev.email, rev.phone].filter(Boolean).join(" / ");
        const shortRevDept = rev.short_department || rev.department || "-";
        html += `
          <td style="font-weight:600;color:var(--orange-deep-text);" title="${escapeHtml(rev.name)}">${escapeHtml(rev.name)}</td>
          <td title="完整院系: ${escapeHtml(rev.department)}">${escapeHtml(shortRevDept)}</td>
          <td title="${escapeHtml(rev.title)}">${escapeHtml(rev.title)}</td>
          <td style="font-size:11.5px;" title="${escapeHtml(contactTip)}">${escapeHtml(contactStr)}</td>
          <td title="${escapeHtml(rev.research_direction)}">${escapeHtml(rev.research_direction || "-")}</td>
          <td title="${escapeHtml(rev.match_direction)}"><span class="badge ${badgeCls}">${escapeHtml((rev.match_direction||"-").slice(0,4))}</span></td>
          <td style="text-align:center;" title="推荐相近度: ${rev.similarity.toFixed(4)}"><span class="score-pill">${rev.similarity.toFixed(3)}</span></td>
        `;
      } else {
        html += `<td colspan="7" style="color:var(--ink-muted);text-align:center;">(满足约束的候选不足，留空)</td>`;
      }
      html += `</tr>`;
    }
  }

  html += `</tbody></table>`;
  wrap.innerHTML = html;
  labelPreviewCells();
}

function exportMatchedResult(format) {downloadAppFile(`/api/match/export?format=${encodeURIComponent(format)}`,`评审匹配结果.${format}`);}

// ==================== 数据库查询、检索与人工维护 ====================
async function loadDbStats() {
  try {
    const resp = await fetch("/api/db/stats");
    const data = await resp.json();
    if (data.error) return;

    document.getElementById("top-db-count").textContent = `${data.total}人`;
    document.getElementById("db-stat-total").textContent = `${data.total}`;
    document.getElementById("db-stat-dept").textContent = `${data.dept_pct}%`;
    document.getElementById("db-stat-dept-sub").textContent = `${data.with_dept} / ${data.total} 人含院系`;
    document.getElementById("db-stat-rd").textContent = `${data.research_pct}%`;
    document.getElementById("db-stat-rd-sub").textContent = `${data.with_research} / ${data.total} 人含研究方向`;
    document.getElementById("db-stat-email").textContent = `${data.email_pct}%`;
    document.getElementById("db-stat-email-sub").textContent = `${data.with_email} / ${data.total} 人含邮箱`;

    // 记录已知完整院系名（已去除“上海交通大学”前缀，按拼音排列），填充 datalist
    const pinyinOrder=new Intl.Collator("zh-Hans-CN-u-co-pinyin");
    const byPinyin=(a,b)=>(a==="(未填院系)")-(b==="(未填院系)")||pinyinOrder.compare(a,b);
    data.known_colleges=(data.known_colleges||[]).sort(byPinyin);
    data.colleges=(data.colleges||[]).sort((a,b)=>byPinyin(a.name,b.name));
    knownCollegesSet = new Set(data.known_colleges);
    const datalist = document.getElementById("college-options-datalist");
    if (datalist && data.known_colleges) {
      datalist.innerHTML = data.known_colleges
        .map((name) => `<option value="${escapeHtml(name)}"></option>`)
        .join("");
    }

    // 院系概览（前端按拼音排序，显示去掉上海交通大学后的完整名称与简称）
    const grid = document.getElementById("college-stats-grid");
    if (grid && data.colleges) {
      grid.innerHTML = data.colleges
        .map(
          (c) => `
          <div style="padding:10px 14px;border:1px solid var(--border-light);border-radius:var(--radius-sm);background:var(--bg-warm-tint);display:flex;justify-content:space-between;align-items:center;cursor:pointer;"
               data-college="${escapeHtml(c.name)}" onclick="filterByCollege(this.dataset.college)">
            <span style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(c.name)} (${escapeHtml(c.short)})">${escapeHtml(c.name)}</span>
            <span class="badge badge-info" style="flex-shrink:0;margin-left:6px;">${c.count} 人</span>
          </div>
        `
        )
        .join("");
    }
  } catch (err) {
    console.error("Failed to load DB stats:", err);
  }
}

function filterByCollege(collegeName) {
  switchDbSubtab("browse");
  document.getElementById("db-q-dept").value = collegeName === "(未填院系)" ? "" : collegeName;
  loadFacultyList(1);
}

function resetDbFilters() {
  document.getElementById("db-q-keyword").value = "";
  document.getElementById("db-q-dept").value = "";
  document.getElementById("db-q-title").value = "";
  document.getElementById("db-q-research").value = "";
  document.getElementById("db-q-nosenior").checked = false;
  document.getElementById("db-q-hasrd").checked = false;
  loadFacultyList(1);
}

async function loadFacultyList(page = 1) {
  dbCurrentPage = page;
  const kw = document.getElementById("db-q-keyword").value.trim();
  const dept = document.getElementById("db-q-dept").value.trim();
  const title = document.getElementById("db-q-title").value.trim();
  const research = document.getElementById("db-q-research").value.trim();
  const noSenior = document.getElementById("db-q-nosenior").checked;
  const hasRd = document.getElementById("db-q-hasrd").checked;

  const qs = new URLSearchParams({
    keyword: kw,
    department: dept,
    title: title,
    research: research,
    exclude_senior: String(noSenior),
    only_has_research: String(hasRd),
    page: String(page),
    page_size: String(DB_PAGE_SIZE),
  });

  const tbody = document.getElementById("db-table-body");
  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--ink-muted);">正在检索数据库...</td></tr>`;

  try {
    const resp = await fetch(`/api/db/list?${qs.toString()}`);
    const data = await resp.json();
    if (data.error) throw new Error(data.error);

    dbCurrentItems = data.items || [];
    dbLayoutSamples = data.layout_samples || dbCurrentItems;
    dbTotalPages = data.total_pages || 1;
    dbCurrentPage = data.page || 1;

    document.getElementById("db-page-info").textContent = `共检索到 ${data.total} 位教师 · 第 ${dbCurrentPage} / ${dbTotalPages} 页（每页 ${DB_PAGE_SIZE} 条）`;
    document.getElementById("db-page-btns").innerHTML = buildPaginationButtonsHtml(
      dbCurrentPage,
      dbTotalPages,
      "loadFacultyList"
    );

    if (!dbCurrentItems.length) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--ink-muted);">没有找到符合筛选条件的教师记录</td></tr>`;
      return;
    }

    const baseSeq = (dbCurrentPage - 1) * DB_PAGE_SIZE;
    tbody.innerHTML = dbCurrentItems
      .map((item, idx) => {
        const contactStr = item.email || item.phone || item.mobile || "-";
        const contactTip = [item.email, item.phone, item.mobile].filter(Boolean).join(" / ");
        const titleBadge = item.is_senior
          ? `<span class="badge badge-warning" title="正高级默认在盲审中回避：${escapeHtml(item.title)}">${escapeHtml(item.title || "-")}</span>`
          : `<span class="badge badge-success" title="${escapeHtml(item.title)}">${escapeHtml(item.title || "-")}</span>`;
        const nameHtml = item.profile_url
          ? `<a href="${escapeHtml(safeProfileUrl(item.profile_url))}" target="_blank" style="color:var(--orange-deep-text);font-weight:600;text-decoration:none;" title="点击打开个人主页">${escapeHtml(item.name)} ↗</a>`
          : `<span style="font-weight:600;">${escapeHtml(item.name)}</span>`;

        // 数据库表格统一显示去掉“上海交通大学”前缀后的完整院系名称
        const fullCleanDept = stripSjtuPrefix(item.department || item.college) || "-";

        return `
          <tr>
            <td style="font-family:var(--font-mono);font-size:11.5px;color:var(--ink-muted);" title="数据库ID: ${escapeHtml(item.teacher_id || item.id)}">#${baseSeq + idx + 1}</td>
            <td title="${escapeHtml(item.name)}">${nameHtml}</td>
            <td>${titleBadge}</td>
            <td title="${escapeHtml(fullCleanDept)}">${escapeHtml(fullCleanDept)}</td>
            <td style="font-size:12px;" title="${escapeHtml(contactTip)}">${escapeHtml(contactStr)}</td>
            <td class="research-cell" title="${escapeHtml(item.research_direction || "")}">${item.research_direction ? `<div class="research-clamp">${escapeHtml(item.research_direction)}</div>` : '<span class="empty-value">—</span>'}</td>
            <td style="text-align:center;">
              <button class="btn btn-xs" onclick="openFacultyModal(${idx})">编辑</button>
              <button class="btn btn-xs btn-danger" style="margin-left:4px;" onclick="deleteFacultyRecord(${item.id})">删除</button>
            </td>
          </tr>
        `;
      })
      .join("");
    applyDatabaseWidths();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:#c2410c;">查询出错：${escapeHtml(err.message)}</td></tr>`;
  }
}

function checkDepartmentInput() {
  const input = document.getElementById("edit-faculty-dept");
  const warnEl = document.getElementById("edit-dept-warning");
  if (!input || !warnEl) return;

  const rawVal = input.value.trim();
  const cleaned = stripSjtuPrefix(rawVal);

  if (!cleaned) {
    warnEl.style.display = "none";
    warnEl.textContent = "";
    return;
  }

  if (knownCollegesSet.size > 0 && !knownCollegesSet.has(cleaned)) {
    warnEl.style.display = "block";
    warnEl.innerHTML = `⚠️ 提示：当前输入的院系「<strong>${escapeHtml(cleaned)}</strong>」不在数据库已有院系列表中，保存时将作为新院系写入。`;
  } else {
    warnEl.style.display = "none";
    warnEl.textContent = "";
  }
}

function openFacultyModal(itemIdx) {
  const modal = document.getElementById("faculty-modal");
  const titleEl = document.getElementById("faculty-modal-title");
  modal.classList.add("open");

  if (itemIdx === null || itemIdx === undefined) {
    titleEl.textContent = "新增教师记录";
    document.getElementById("edit-faculty-id").value = "";
    document.getElementById("edit-faculty-name").value = "";
    document.getElementById("edit-faculty-title").value = "";
    document.getElementById("edit-faculty-dept").value = "";
    document.getElementById("edit-faculty-email").value = "";
    document.getElementById("edit-faculty-phone").value = "";
    document.getElementById("edit-faculty-mobile").value = "";
    document.getElementById("edit-faculty-url").value = "";
    document.getElementById("edit-faculty-rd").value = "";
    document.getElementById("edit-faculty-profile").value = "";
  } else {
    const item = dbCurrentItems[itemIdx];
    titleEl.textContent = `编辑教师信息 — ${item.name}`;
    document.getElementById("edit-faculty-id").value = item.id;
    document.getElementById("edit-faculty-name").value = item.name || "";
    document.getElementById("edit-faculty-title").value = item.title || "";
    document.getElementById("edit-faculty-dept").value = stripSjtuPrefix(item.department || item.college || "");
    document.getElementById("edit-faculty-email").value = item.email || "";
    document.getElementById("edit-faculty-phone").value = item.phone || item.mobile || "";
    document.getElementById("edit-faculty-mobile").value = item.mobile || "";
    document.getElementById("edit-faculty-url").value = item.profile_url || "";
    document.getElementById("edit-faculty-rd").value = item.research_direction || "";
    document.getElementById("edit-faculty-profile").value = item.profile_text || "";
  }
  checkDepartmentInput();
}

function closeFacultyModal() {
  document.getElementById("faculty-modal").classList.remove("open");
}

async function saveFacultyRecord() {
  const idVal = document.getElementById("edit-faculty-id").value.trim();
  const name = document.getElementById("edit-faculty-name").value.trim();
  if (!name) {
    alert("教师姓名不能为空！");
    return;
  }

  const rawDept = document.getElementById("edit-faculty-dept").value.trim();
  const cleanDept = stripSjtuPrefix(rawDept);

  // 如果输入的院系是之前数据库没有的，弹出警告确认
  if (cleanDept && knownCollegesSet.size > 0 && !knownCollegesSet.has(cleanDept)) {
    const ok = confirm(`警告：院系「${cleanDept}」在当前数据库中从未出现过。\n是否确认将该新院系写入数据库？`);
    if (!ok) return;
  }

  const payload = {
    id: idVal ? parseInt(idVal, 10) : undefined,
    name: name,
    title: document.getElementById("edit-faculty-title").value.trim(),
    department: cleanDept,
    college: cleanDept,
    email: document.getElementById("edit-faculty-email").value.trim(),
    phone: document.getElementById("edit-faculty-phone").value.trim(),
    mobile: document.getElementById("edit-faculty-mobile").value.trim(),
    profile_url: document.getElementById("edit-faculty-url").value.trim(),
    research_direction: document.getElementById("edit-faculty-rd").value.trim(),
    profile_text: document.getElementById("edit-faculty-profile").value.trim(),
  };

  const url = idVal ? "/api/db/update" : "/api/db/create";
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "保存失败");
    closeFacultyModal();
    loadDbStats();
    loadFacultyList(dbCurrentPage);
  } catch (err) {
    alert(`保存失败：${err.message}`);
  }
}

async function deleteFacultyRecord(id, name) {
  name = name || (dbCurrentItems.find(item=>item.id===id)?.name) || "该教师";
  if (!confirm(`确定要从数据库中删除教师「${name}」吗？`)) return;
  try {
    const resp = await fetch("/api/db/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "删除失败");
    loadDbStats();
    loadFacultyList(dbCurrentPage);
  } catch (err) {
    alert(`删除失败：${err.message}`);
  }
}

// ==================== 外部教师表格增量合并 & 脚本运行 ====================
function onMergeFileSelected(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  readFileToBase64(file, (b64) => {
    currentMergeFileBase64 = b64;
    currentMergeFilename = file.name;
    document.getElementById("merge-file-label").textContent = `已选择待合并教师表：${file.name}`;
  });
}

async function runTeacherMerge(dryRun = true) {
  if (!currentMergeFileBase64) {
    alert("请先选择要增量合并的外部教师 Excel / CSV 文件！");
    return;
  }

  const box = document.getElementById("merge-result-box");
  box.style.display = "block";
  box.innerHTML = `<div style="padding:12px;color:var(--ink-secondary);">正在执行${dryRun ? "合并预览 (--dry-run)" : "增量写入"}...</div>`;

  try {
    const resp = await fetch("/api/db/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: currentMergeFilename,
        file_base64: currentMergeFileBase64,
        dry_run: dryRun,
        conflict_policy: document.getElementById("merge-conflict-policy").value,
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "合并失败");

    box.innerHTML = `
      <div style="padding:14px 18px;border-radius:var(--radius-md);background:${dryRun ? "var(--bg-warm-tint)" : "var(--sage-bg)"};border:1px solid ${dryRun ? "var(--orange-soft-border)" : "var(--sage-border)"};">
        <div style="font-weight:600;margin-bottom:6px;color:${dryRun ? "var(--orange-deep-text)" : "var(--sage-text)"};">
          ${dryRun ? "预览结果 (--dry-run，尚未写入数据库)" : "增量合并写入完成"}
        </div>
        <div style="font-size:12.5px;line-height:1.7;color:var(--ink-primary);">
          • 解析有效教师行：<strong>${data.total_rows_parsed}</strong> 条<br/>
          • 库中无此姓名（直接新增）：<strong>${data.added_count}</strong> 人<br/>
          • 同名同院系（自动合并保留更丰富字段）：<strong>${data.merged_same_dept_count}</strong> 人<br/>
          • 同名不同院系（追加新记录）：<strong>${data.appended_diff_dept_count}</strong> 人<br/>
          • 同名但院系缺失（按所选策略处理）：<strong>${data.ambiguous_dept_count}</strong> 人
        </div>
      </div>
    `;
    if (!dryRun) {
      loadDbStats();
      loadFacultyList(1);
    }
  } catch (err) {
    box.innerHTML = `<div style="padding:12px;color:#c2410c;font-weight:600;">合并失败：${escapeHtml(err.message)}</div>`;
  }
}

async function triggerScript(scriptKey) {
  const options = {};
  if (scriptKey === "scraper") {
    options.force = document.getElementById("scr-opt-force").checked;
    options.with_research = document.getElementById("scr-opt-research").checked;
  } else if (scriptKey === "research") {
    options.force = document.getElementById("res-opt-force").checked;
  }

  try {
    const resp = await fetch("/api/scripts/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script_key: scriptKey, options }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "启动脚本失败");
    refreshScriptTasks();
    if (!scriptPollTimer) {
      scriptPollTimer = setInterval(refreshScriptTasks, 2000);
    }
  } catch (err) {
    alert(`启动脚本失败：${err.message}`);
  }
}

async function refreshScriptTasks() {
  try {
    const resp = await fetch("/api/scripts/tasks");
    const data = await resp.json();
    const tasks = data.tasks || [];
    const logBox = document.getElementById("script-log-box");
    if (!tasks.length) {
      logBox.textContent = "尚无正在运行或已执行的后台脚本任务。";
      return;
    }

    const latest = tasks[0];
    const header = `[任务] ${latest.name} | 状态: ${latest.status} | 启动时间: ${latest.start_time}\n` +
                   `[命令] ${latest.command}\n` +
                   `------------------------------------------------------------\n`;
    logBox.textContent = header + (latest.logs || []).join("\n");
    logBox.scrollTop = logBox.scrollHeight;

    const anyRunning = tasks.some((t) => t.status === "running");
    if (!anyRunning && scriptPollTimer) {
      clearInterval(scriptPollTimer);
      scriptPollTimer = null;
      loadDbStats();
    }
  } catch (err) {
    console.error("Failed to poll script tasks:", err);
  }
}

function safeProfileUrl(value) { try { const url=new URL(value); return ["http:","https:"].includes(url.protocol)?url.href:"#"; } catch{return "#";} }

// Shared runtime preferences and explicit application exit.
let appPreferences=null;
let heartbeatTimer=null;
const clientId=crypto.randomUUID();
const desktopInterface=new URLSearchParams(location.search).get('interface')==='desktop';
const preferenceFields=[
 ['max_teacher_uses','教师复用上限','number',2],['pick_count','每人评审数','number',3],['pool_size','候选池大小','number',20],
 ['strategy','选取策略','select','top'],['seed','随机种子','number',42],['min_score','最低相近分数','number',.05],['relative_score','相对分数阈值','number',.4],
 ['strict','严格阈值模式','checkbox',false],['allow_unknown_title','允许职称不明','checkbox',false]
];
async function appRequest(path,body){
 const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const result=await response.json();if(!response.ok||result.error)throw new Error(result.error||'操作失败');return result;
}
function populatePreferences(data){
 appPreferences=data;document.getElementById('pref-data-dir').value=data.data_dir;
 document.getElementById('pref-default-path').textContent=`默认位置：${data.default_data_dir}${data.managed_storage?' · 当前由Docker挂载管理':''}`;

 document.getElementById('pref-data-dir').disabled=data.managed_storage;
 document.getElementById('pref-pick-dir').disabled=data.managed_storage;
 document.getElementById('pref-match-defaults').innerHTML=preferenceFields.map(([key,label,type,fallback])=>{
  const value=data.match_defaults[key]??fallback;
  const field=type==='select'?`<select id="pref-${key}" class="select"><option value="top" ${value==='top'?'selected':''}>排名优先</option><option value="weighted" ${value==='weighted'?'selected':''}>加权抽样</option></select>`:type==='checkbox'?`<input id="pref-${key}" type="checkbox" ${value?'checked':''}/>`:`<input id="pref-${key}" class="input" type="number" step="${['min_score','relative_score'].includes(key)?'.01':'1'}" value="${escapeHtml(value)}"/>`;
  return `<div class="form-group"><label for="pref-${key}" class="form-label">${label}</label>${field}</div>`;
 }).join('')+`<div class="form-group pref-save-cell"><button class="btn btn-primary btn-sm" id="pref-save" onclick="savePreferences()">保存设置</button></div>`;
}
function applyDefaults(data){
 const map={pick_count:'pick',pool_size:'pool',max_teacher_uses:'max-uses',strategy:'strategy',seed:'seed',min_score:'min-score',relative_score:'rel-score',strict:'strict',allow_unknown_title:'allow-unknown'};
 for(const [key,suffix] of Object.entries(map)){const field=document.getElementById('param-'+suffix);if(field.type==='checkbox')field.checked=data.match_defaults[key];else field.value=data.match_defaults[key];}
 updateParamsSummaryLabel();
}
async function loadPreferences(){try{populatePreferences(await appRequest('/api/preferences'));}catch(error){document.getElementById('pref-feedback').textContent=error.message;}}
async function initializeApplication(){
 try{
  await loadPreferences();if(appPreferences)applyDefaults(appPreferences);
  const status=await appRequest('/api/app/status');document.getElementById('btn-exit-app').hidden=!status.can_exit;
  const heartbeat=()=>appRequest('/api/app/client',{id:clientId,mode:desktopInterface?'desktop':'browser'}).catch(()=>{});
  await heartbeat();heartbeatTimer=setInterval(heartbeat,15000);
  if(appPreferences&&!appPreferences.storage_confirmed){document.getElementById('first-storage-path').textContent=appPreferences.data_dir;document.getElementById('first-storage-modal').classList.add('open');}
  window.JZReady=true;
 }catch(error){document.getElementById('pref-feedback').textContent=error.message;}
}
window.addEventListener('pagehide',()=>navigator.sendBeacon('/api/app/client',new Blob([JSON.stringify({id:clientId,closed:true})],{type:'application/json'})));
async function confirmInitialStorage(){
 try{populatePreferences(await appRequest('/api/preferences',{data_dir:appPreferences.data_dir}));document.getElementById('first-storage-modal').classList.remove('open');}
 catch(error){document.getElementById('first-storage-error').textContent=error.message;}
}
function configureInitialStorage(){document.getElementById('first-storage-modal').classList.remove('open');switchPage('preferences');}
async function choosePreferenceDirectory(){
 try{
  const path=window.pywebview?.api?await window.pywebview.api.choose_data_dir():(await appRequest('/api/preferences/choose-folder',{})).path;
  if(path)document.getElementById('pref-data-dir').value=path;
 }catch(error){document.getElementById('pref-feedback').textContent=error.message;}
}
async function savePreferences(){
 const button=document.getElementById('pref-save');button.disabled=true;
 try{
  const defaults={};for(const [key,,type] of preferenceFields){const field=document.getElementById('pref-'+key);defaults[key]=type==='checkbox'?field.checked:type==='number'?Number(field.value):field.value;}
  const path=document.getElementById('pref-data-dir').value.trim();
  if(path!==appPreferences.data_dir&&!confirm('切换存储位置将影响所有界面。目标已有教师库时将使用该库，否则迁移现有数据。原位置文件保留，是否继续？'))return;
  populatePreferences(await appRequest('/api/preferences',{data_dir:path,migration:'auto',retain_uploads:false,match_defaults:defaults}));
  applyDefaults(appPreferences);document.getElementById('pref-feedback').textContent='已保存';loadDbStats();
 }catch(error){document.getElementById('pref-feedback').textContent=error.message;}finally{button.disabled=false;}
}
async function openStorageFolder(kind){try{await appRequest('/api/preferences/open-folder',{kind});}catch(error){alert(error.message);}}
async function downloadAppFile(url,fallback){
 try{
  const response=await fetch(url);if(!response.ok){const data=await response.json();throw new Error(data.error||'导出失败');}
  const blob=await response.blob();
  if(window.pywebview?.api){
   const reader=new FileReader();reader.onload=async()=>{try{await window.pywebview.api.save_export(fallback,String(reader.result).split(',')[1]);}catch(error){alert(error.message);}};reader.readAsDataURL(blob);
  }else{const address=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=address;anchor.download=fallback;anchor.click();setTimeout(()=>URL.revokeObjectURL(address),30000);}
 }catch(error){alert(error.message);}
}
async function restoreDatabase(event){
 const file=event.target.files?.[0];if(!file)return;
 if(!confirm('导入数据将替换当前教师库，原库会自动备份。是否继续？'))return;
 try{const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});const result=await appRequest('/api/preferences/restore',{file_base64:encoded});document.getElementById('pref-feedback').textContent=result.message;await loadPreferences();loadDbStats();}
 catch(error){document.getElementById('pref-feedback').textContent=error.message;}finally{event.target.value='';}
}
async function exitApplication(){
 try{
  const status=await appRequest('/api/app/status');if(status.busy)throw new Error('请等待匹配或维护任务结束后再退出。');
  if(status.clients>1&&!confirm(`当前有 ${status.clients} 个界面连接共享后台。退出后其他界面也会断开，是否继续？`))return;
  await appRequest('/api/app/shutdown',{token:status.exit_token,confirm_all:status.clients>1});clearInterval(heartbeatTimer);
  if(window.pywebview?.api){await window.pywebview.api.close_window();return;}
  document.body.innerHTML='<main style="padding:12vh 8vw;font-family:system-ui"><h1>程序已退出</h1><p>共享后台已停止，可以关闭此页面。再次使用时请启动程序。</p></main>';
 }catch(error){alert(error.message);}
}

// 匹配结果出现后页面可能新增纵向滚动条，容器随之变窄；重新分配长字段。
const tableContainerWidths=new WeakMap();
const tableContainerObserver=new ResizeObserver(entries=>{
 let changed=false;for(const entry of entries){const width=entry.contentRect.width;if(width>0&&tableContainerWidths.get(entry.target)!==width){tableContainerWidths.set(entry.target,width);changed=true;}}
 if(changed){clearTimeout(fitResizeTimer);fitResizeTimer=setTimeout(()=>{if(currentMatchData)renderMatchPreviewTable();applyDatabaseWidths();},100);}
});
for(const id of ['match-preview-wrap','db-faculty-table']){const element=document.getElementById(id);if(element)tableContainerObserver.observe(id==='db-faculty-table'?element.parentElement:element);}

function refreshSlidingTabs(){
 for(const group of document.querySelectorAll('.nav-pills,.db-action-tabs')){
  const selected=group.querySelector('button.active');
  if(!selected||!group.clientWidth||!selected.offsetWidth)continue;
  group.classList.add('sliding-tabs');
  for(const button of group.querySelectorAll('button'))button.setAttribute('aria-pressed',String(button===selected));
  group.style.setProperty('--tab-x',selected.offsetLeft+'px');
  group.style.setProperty('--tab-y',selected.offsetTop+'px');
  group.style.setProperty('--tab-width',selected.offsetWidth+'px');
  group.style.setProperty('--tab-height',selected.offsetHeight+'px');
  if(!group.classList.contains('slider-ready'))requestAnimationFrame(()=>group.classList.add('slider-ready'));
 }
}
window.addEventListener('DOMContentLoaded',()=>{
 const observer=new ResizeObserver(refreshSlidingTabs);
 for(const group of document.querySelectorAll('.nav-pills,.db-action-tabs'))observer.observe(group);
 refreshSlidingTabs();document.fonts.ready.then(refreshSlidingTabs);
});
window.addEventListener('resize',refreshSlidingTabs);

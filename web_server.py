#!/usr/bin/env python3
"""
SJTU 䇹政盲审导师自动匹配与数据库维护 Web 平台后端
启动方式:
  python3 web_server.py            # 默认监听 http://127.0.0.1:8765
  python3 web_server.py --port 8080
"""
import argparse
from contextlib import closing
import secrets
import hmac
import shutil
from http.cookies import SimpleCookie
import base64
import csv
import io
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sjtu_excel_io as xio
import sjtu_match_reviewers as matcher
import sjtu_query_db as qdb

SCRIPT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if os.getenv("JZ_DATA_DIR"):
    DATA_DIR = Path(os.environ["JZ_DATA_DIR"]).resolve()
elif (SCRIPT_DIR / "sjtu_faculty_data" / "sjtu_faculty_data.db").exists():
    DATA_DIR = SCRIPT_DIR / "sjtu_faculty_data"  # 保留本机原工程的真实数据库。
else:
    base = Path(os.getenv("LOCALAPPDATA", Path.home() / "Library/Application Support" if sys.platform == "darwin" else os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")))
    DATA_DIR = base / "SJTU-JunZhengMatch"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sjtu_faculty_data.db"
if not DB_PATH.exists():
    seed = SCRIPT_DIR / "data" / "faculty.db"
    if not seed.exists(): raise RuntimeError("未找到公开教师数据库。请保持发布包完整，或设置 JZ_DATA_DIR。")
    shutil.copy2(seed, DB_PATH)
matcher.DB_PATH = qdb.DB_PATH = DB_PATH
FRONTEND_DIR = SCRIPT_DIR / "frontend"

_REQUEST_STATE=threading.local()
MATCH_SESSIONS={}
MAX_BODY=20*1024*1024
DB_WRITE_LOCK=threading.RLock()

# 后台脚本任务状态管理
TASK_LOCK = threading.Lock()
TASKS = {}  # task_id -> {id, name, command, status, start_time, end_time, logs: []}

# 最近一次匹配会话缓存（用于直接导出 CSV 或合并单元格 XLSX）
SESSION_LOCK = threading.Lock()
LAST_MATCH_SESSION = {
    "students": [],
    "results": [],
    "pick_count": 3,
    "banner_text": "",
    "filename": "matched",
}

COLUMN_MAP = {
    "姓名": "name", "名字": "name", "name": "name", "教师姓名": "name", "拟定评审": "name",
    "职称": "title", "title": "title",
    "院系": "department", "学院": "department", "department": "department",
    "邮箱": "email", "email": "email", "mail": "email",
    "电话": "phone", "手机": "mobile", "phone": "phone", "mobile": "mobile",
    "研究方向": "research_direction", "研究领域": "research_direction", "research": "research_direction",
    "个人主页": "profile_url", "url": "profile_url",
    "个人简介": "profile_text", "简介": "profile_text",
}
EXCLUDE_COLS = ["导师", "学生", "指导", "课题", "序号"]
DB_FIELDS = ["title", "department", "college", "email", "phone", "mobile", "research_direction", "profile_url", "profile_text"]


def current_match_session():
    token=getattr(_REQUEST_STATE,'token',None)
    if not token:return LAST_MATCH_SESSION
    with SESSION_LOCK:
        now=time.time()
        for key in list(MATCH_SESSIONS):
            if now-MATCH_SESSIONS[key]['seen']>86400:del MATCH_SESSIONS[key]
        if token not in MATCH_SESSIONS:
            if len(MATCH_SESSIONS)>=100:
                oldest=min(MATCH_SESSIONS,key=lambda k:MATCH_SESSIONS[k]['seen']);del MATCH_SESSIONS[oldest]
            MATCH_SESSIONS[token]=dict(seen=now,data=dict(students=[],results=[],pick_count=3,banner_text='',filename='matched'))
        MATCH_SESSIONS[token]['seen']=now
        return MATCH_SESSIONS[token]['data']


def database_backup():
    folder=DATA_DIR/'backups';folder.mkdir(exist_ok=True)
    path=folder/f'faculty-{time.time_ns()}.db'
    with closing(sqlite3.connect(DB_PATH)) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
    for old in sorted(folder.glob('*.db'))[:-20]:old.unlink(missing_ok=True)


def get_db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_db_stats():
    conn = get_db_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]
        with_rd = conn.execute("SELECT COUNT(*) FROM faculty WHERE research_direction IS NOT NULL AND research_direction != ''").fetchone()[0]
        with_email = conn.execute("SELECT COUNT(*) FROM faculty WHERE email IS NOT NULL AND email != ''").fetchone()[0]
        with_dept = conn.execute(
            "SELECT COUNT(*) FROM faculty WHERE (college IS NOT NULL AND college != '') OR (department IS NOT NULL AND department != '')"
        ).fetchone()[0]
        colleges = conn.execute("""
            SELECT COALESCE(NULLIF(department,''), NULLIF(college,''), '(未填院系)') AS dept, COUNT(*) AS cnt
            FROM faculty GROUP BY dept
        """).fetchall()
        # 清理前缀并合并可能因前缀不同而分散的同名院系，按字典序排列
        merged_counts = Counter()
        for r in colleges:
            cleaned_name = qdb.clean_college_full(r["dept"]) or "(未填院系)"
            merged_counts[cleaned_name] += r["cnt"]

        # 字典序排序（将 '(未填院系)' 放在末尾）
        sorted_depts = sorted(merged_counts.keys(), key=lambda x: (x == "(未填院系)", x))
        college_list = [
            {"name": k, "short": qdb.short_college(k), "count": merged_counts[k]}
            for k in sorted_depts
        ]
        known_colleges = [k for k in sorted_depts if k != "(未填院系)"]
        return {
            "total": total,
            "with_research": with_rd,
            "with_email": with_email,
            "with_dept": with_dept,
            "research_pct": round(100 * with_rd / max(total, 1), 1),
            "email_pct": round(100 * with_email / max(total, 1), 1),
            "dept_pct": round(100 * with_dept / max(total, 1), 1),
            "colleges": college_list,
            "known_colleges": known_colleges,
        }
    finally:
        conn.close()


def layout_samples(items):
    import unicodedata
    def units(value):return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in str(value or ''))
    indices=set()
    for field in ('name','title','department','college','email','phone','mobile'):
        indices.update(sorted(range(len(items)),key=lambda i:units(items[i].get(field)),reverse=True)[:12])
    return [{k:items[i].get(k,'') for k in ('name','title','department','college','email','phone','mobile')} for i in sorted(indices)]


def query_faculty(keyword="", department="", title="", research="", exclude_senior=False, only_has_research=False, page=1, page_size=25):
    conn = get_db_conn()
    try:
        conds = []
        params = []
        if keyword:
            conds.append("(name LIKE ? OR email LIKE ? OR phone LIKE ? OR mobile LIKE ? OR research_direction LIKE ? OR profile_text LIKE ? OR department LIKE ? OR college LIKE ?)")
            params.extend([f"%{keyword}%"] * 8)
        if department:
            clean_dep = qdb.clean_college_full(department)
            conds.append("(department LIKE ? OR college LIKE ?)")
            params.extend([f"%{clean_dep}%", f"%{clean_dep}%"])
        if title:
            conds.append("(title LIKE ?)")
            params.append(f"%{title}%")
        if research:
            conds.append("(research_direction LIKE ? OR profile_text LIKE ?)")
            params.extend([f"%{research}%", f"%{research}%"])
        if only_has_research:
            conds.append("(research_direction IS NOT NULL AND research_direction != '')")

        where_sql = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = conn.execute(f"""
            SELECT id, teacher_id, name, name_en, title,
                   COALESCE(NULLIF(department,''), college, '') AS department,
                   COALESCE(college, '') AS college,
                   COALESCE(email, '') AS email,
                   COALESCE(phone, '') AS phone,
                   COALESCE(mobile, '') AS mobile,
                   COALESCE(research_direction, '') AS research_direction,
                   COALESCE(profile_text, '') AS profile_text,
                   COALESCE(profile_url, '') AS profile_url,
                   COALESCE(address, '') AS address
            FROM faculty {where_sql}
            ORDER BY COALESCE(NULLIF(department,''), college, 'zzzz'), name, teacher_id
        """, params).fetchall()

        items = []
        for r in rows:
            d = dict(r)
            d["is_senior"] = matcher.is_senior_title(d.get("title", ""))
            if exclude_senior and d["is_senior"]:
                continue
            d["department"] = qdb.clean_college_full(d["department"] or d["college"])
            d["college"] = qdb.clean_college_full(d["college"] or d["department"])
            d["short_dept"] = qdb.short_college(d["department"])
            items.append(d)

        total = len(items)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        start = (page - 1) * page_size
        paged_items = items[start:start + page_size]

        return {
            "items": paged_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "layout_samples": layout_samples(items),
        }
    finally:
        conn.close()


def create_faculty(data):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("教师姓名不能为空")
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        max_tid = cur.execute("SELECT COALESCE(MAX(teacher_id), 100000) FROM faculty").fetchone()[0]
        tid = data.get("teacher_id") or (int(max_tid) + 1)
        dept = qdb.clean_college_full(data.get("department") or data.get("college") or "")
        college = qdb.clean_college_full(data.get("college") or dept)
        cur.execute("""
            INSERT INTO faculty (teacher_id, name, name_en, title, department, college, email, phone, mobile, research_direction, profile_text, profile_url, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tid,
            name,
            (data.get("name_en") or "").strip(),
            (data.get("title") or "").strip(),
            dept,
            college,
            (data.get("email") or "").strip(),
            (data.get("phone") or "").strip(),
            (data.get("mobile") or "").strip(),
            (data.get("research_direction") or "").strip(),
            (data.get("profile_text") or "").strip(),
            (data.get("profile_url") or "").strip(),
            (data.get("address") or "").strip(),
        ))
        conn.commit()
        return {"id": cur.lastrowid, "teacher_id": tid, "name": name}
    finally:
        conn.close()


def update_faculty(record_id, data):
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT id, teacher_id FROM faculty WHERE id = ? OR teacher_id = ?", (record_id, record_id)).fetchone()
        if not row:
            raise ValueError("未找到该教师记录")
        pk = row["id"]
        dept = qdb.clean_college_full(data.get("department") or "")
        college = qdb.clean_college_full(data.get("college") or dept)
        cur.execute("""
            UPDATE faculty
            SET name = ?, name_en = ?, title = ?, department = ?, college = ?,
                email = ?, phone = ?, mobile = ?, research_direction = ?,
                profile_text = ?, profile_url = ?, address = ?
            WHERE id = ?
        """, (
            (data.get("name") or "").strip(),
            (data.get("name_en") or "").strip(),
            (data.get("title") or "").strip(),
            dept,
            college,
            (data.get("email") or "").strip(),
            (data.get("phone") or "").strip(),
            (data.get("mobile") or "").strip(),
            (data.get("research_direction") or "").strip(),
            (data.get("profile_text") or "").strip(),
            (data.get("profile_url") or "").strip(),
            (data.get("address") or "").strip(),
            pk,
        ))
        conn.commit()
        return {"updated": pk}
    finally:
        conn.close()


def delete_faculty(record_id):
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM faculty WHERE id = ? OR teacher_id = ?", (record_id, record_id))
        deleted = cur.rowcount
        conn.commit()
        return {"deleted": deleted}
    finally:
        conn.close()


def run_match_pipeline(file_bytes, filename, params):
    """
    执行盲审导师匹配流水线，支持全部 CLI 参数
    """
    rows = xio.read_tabular_rows(file_bytes, filename)
    all_students, headers, banner_text = xio.parse_students_from_rows(rows)
    for s in all_students:
        s["advisor_dept"] = qdb.clean_college_full(s.get("advisor_dept", ""))

    filter_mode = params.get("filter_mode", "all")
    students = list(all_students)
    if filter_mode == "range":
        range_str = str(params.get("range_str", "")).strip()
        if range_str:
            parts = range_str.split("-")
            start = int(parts[0])
            end = int(parts[-1])
            students = [s for s in students if start <= s["seq"] <= end]
    elif filter_mode == "student":
        seq_target = int(params.get("student_seq", 1))
        students = [s for s in students if s["seq"] == seq_target]
    elif filter_mode == "name":
        name_kw = str(params.get("student_name", "")).strip()
        if name_kw:
            students = [s for s in students if name_kw in s["name"]]

    pool_size = max(1, int(params.get("pool_size", 20)))
    pick_count = max(1, int(params.get("pick_count", 3)))
    if pool_size < pick_count:
        pool_size = pick_count
    strategy = params.get("strategy", "top")
    if strategy not in ("top", "weighted"):
        strategy = "top"
    seed = int(params.get("seed", 42))
    min_score = float(params.get("min_score", 0.05))
    relative_score = float(params.get("relative_score", 0.4))
    strict = bool(params.get("strict", False))
    allow_unknown_title = bool(params.get("allow_unknown_title", False))

    if not 1 <= pick_count <= 15 or not pick_count <= pool_size <= 2000:
        raise ValueError("评审人数须为1—15，候选池须不少于评审人数且最多2000。")
    if not 0 <= min_score <= 1 or not 0 <= relative_score <= 1:
        raise ValueError("相似度阈值须在0—1之间。")
    t0 = time.time()
    teachers = matcher.load_teachers()
    for t in teachers:
        t["department"] = qdb.clean_college_full(t.get("department", "") or t.get("college", ""))
        t["college"] = qdb.clean_college_full(t.get("college", "") or t.get("department", ""))
    engine = matcher.build_engine(teachers)

    results = []
    used_names = set()
    usage_counts = Counter()
    rng = random.Random(seed)

    preview_items = []
    for s in students:
        if strict:
            matches, reused = matcher.find_matches(
                s["topic"], teachers, engine, s["advisor"], used_names,
                pool_size=pool_size, pick_count=pick_count,
                min_score=min_score, relative_score=relative_score,
                strategy=strategy, rng=rng, allow_unknown_title=allow_unknown_title,
            )
        else:
            matches, reused = matcher.find_complete_matches(
                s, teachers, engine, usage_counts,
                pool_size=pool_size, pick_count=pick_count,
                strategy=strategy, rng=rng, allow_unknown_title=allow_unknown_title,
                min_score=min_score,
            )

        results.append(matches)
        for t, _ in matches:
            used_names.add(t["name"])
            usage_counts[matcher.normalize_name(t["name"])] += 1

        reviewer_list = []
        for idx, (t, score) in enumerate(matches, 1):
            match_dir = xio.format_match_direction(s["topic"], t, matcher.tokenize)
            full_dept = qdb.clean_college_full(t.get("department", "") or t.get("college", ""))
            reviewer_list.append({
                "index": idx,
                "teacher_id": t.get("teacher_id"),
                "name": t.get("name", ""),
                "department": full_dept,
                "short_department": qdb.short_college(full_dept),
                "title": t.get("title", ""),
                "phone": xio.clean_cell_str(t.get("phone", "")),
                "email": t.get("email", ""),
                "research_direction": t.get("research_direction", ""),
                "match_direction": match_dir,
                "match_level": t.get("_match_level", "严格匹配"),
                "similarity": round(float(score), 4),
                "is_reused": t.get("name", "") in reused,
            })

        full_adv_dept = qdb.clean_college_full(s["advisor_dept"])
        preview_items.append({
            "seq": s["seq"],
            "category": s["category"],
            "name": s["name"],
            "student_id": xio.clean_cell_str(s.get("student_id", "")),
            "topic": s["topic"],
            "advisor": s["advisor"],
            "advisor_dept": full_adv_dept,
            "short_advisor_dept": qdb.short_college(full_adv_dept),
            "reviewers": reviewer_list,
        })

    elapsed = round(time.time() - t0, 3)

    base_stem = Path(filename or "matched").stem
    cache = current_match_session()
    with SESSION_LOCK:
        cache["students"] = students
        cache["results"] = results
        cache["pick_count"] = pick_count
        cache["banner_text"] = banner_text
        cache["filename"] = base_stem

    matched_any = sum(1 for r in results if r)
    matched_full = sum(1 for r in results if len(r) >= pick_count)

    return {
        "filename": filename,
        "total_uploaded": len(all_students),
        "total_matched_students": len(students),
        "matched_any": matched_any,
        "matched_full": matched_full,
        "unique_reviewers_used": len(used_names),
        "pick_count": pick_count,
        "pool_size": pool_size,
        "strategy": strategy,
        "strict": strict,
        "elapsed_sec": elapsed,
        "items": preview_items,
    }


def merge_teachers_from_bytes(file_bytes, filename, dry_run=True, conflict_policy="richer"):
    """
    增量合并外部 Excel/CSV 教师数据到数据库（保留 sjtu_merge_teachers.py 四路分类逻辑）：
    1. DB 无此姓名 -> 新增 (added)
    2. DB 有此姓名 + 同一院系 -> 自动合并保留更丰富信息 (merged)
    3. DB 有此姓名 + 不同院系 -> 当作同名不同人追加 (appended)
    4. 院系信息缺失无法判断 -> 根据 conflict_policy ('richer' 合并 / 'add' 新增 / 'skip' 跳过)
    """
    rows = xio.read_tabular_rows(file_bytes, filename)
    if not rows:
        raise ValueError("上传的教师表格为空")

    # 寻找表头行
    hr = 0
    for i, r in enumerate(rows):
        cells = [xio.clean_cell_str(v) for v in r if xio.clean_cell_str(v)]
        short = [c for c in cells if len(c) < 12]
        if len(short) >= 2 and any("姓名" in c or "拟定评审" in c or c.lower() == "name" for c in cells):
            hr = i
            break

    headers = [xio.clean_cell_str(c) for c in rows[hr]]
    col_map = {}
    for idx, col in enumerate(headers):
        k = col.strip().lower().replace(" ", "").replace("\n", "")
        if not k or any(e in k for e in EXCLUDE_COLS):
            continue
        for pat, field in COLUMN_MAP.items():
            pk = pat.lower()
            if pk in k or k in pk:
                # 若同一个字段（比如学院/职称）出现多次（如横式展开评审1/2/3），记录所有列分组
                col_map[idx] = field
                break

    if "name" not in col_map.values():
        raise ValueError("未检测到教师姓名列（支持列名：姓名 / 教师姓名 / 拟定评审 / name）")

    # 提取教师记录
    extracted_records = []
    for r in rows[hr + 1:]:
        rec = {}
        for c_idx, field in col_map.items():
            if c_idx < len(r):
                val = xio.clean_cell_str(r[c_idx])
                if val and not rec.get(field):
                    rec[field] = val
        if rec.get("name"):
            extracted_records.append(rec)

    conn = get_db_conn()
    try:
        cur = conn.cursor()
        adds, merges, sames, ambs = [], [], [], []

        def filled_count(rec_dict):
            return sum(1 for f in DB_FIELDS if rec_dict.get(f, ""))

        def merge_richer(r1, r2):
            base, supp = (dict(r1), r2) if filled_count(r1) >= filled_count(r2) else (dict(r2), r1)
            for f in DB_FIELDS:
                if not base.get(f, "") and supp.get(f, ""):
                    base[f] = supp[f]
            base["name"] = r1["name"]
            return base

        for rec in extracted_records:
            name = rec["name"]
            if "department" in rec:
                rec["department"] = qdb.clean_college_full(rec["department"])
            if "college" in rec:
                rec["college"] = qdb.clean_college_full(rec["college"])
            db_rows = [dict(row) for row in cur.execute("SELECT * FROM faculty WHERE name = ?", (name,)).fetchall()]
            if not db_rows:
                adds.append(rec)
            else:
                dbr = db_rows[0]
                d1 = qdb.clean_college_full(rec.get("department") or rec.get("college") or "")
                d2 = qdb.clean_college_full(dbr.get("department") or dbr.get("college") or "")
                if d1 and d2:
                    if qdb.short_college(d1) == qdb.short_college(d2) or d1 == d2:
                        merges.append((rec, dbr))
                    else:
                        sames.append(rec)
                else:
                    ambs.append((rec, dbr))

        max_tid = cur.execute("SELECT COALESCE(MAX(teacher_id), 100000) FROM faculty").fetchone()[0]
        next_tid = int(max_tid) + 1

        def insert_one(r):
            nonlocal next_tid
            dept = qdb.clean_college_full(r.get("department", "") or r.get("college", ""))
            cur.execute("""
                INSERT INTO faculty (teacher_id, name, title, department, college, email, phone, mobile, research_direction, profile_url, profile_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                next_tid, r.get("name", ""), r.get("title", ""), dept, dept,
                r.get("email", ""), r.get("phone", ""), r.get("mobile", ""),
                r.get("research_direction", ""), r.get("profile_url", ""), r.get("profile_text", "")
            ))
            next_tid += 1

        def update_one(pk_id, mg):
            dept = qdb.clean_college_full(mg.get("department", "") or mg.get("college", ""))
            cur.execute("""
                UPDATE faculty SET title=?, department=?, college=?, email=?, phone=?, mobile=?, research_direction=?, profile_url=?, profile_text=?
                WHERE id=?
            """, (
                mg.get("title", ""), dept, qdb.clean_college_full(mg.get("college", dept)),
                mg.get("email", ""), mg.get("phone", ""), mg.get("mobile", ""),
                mg.get("research_direction", ""), mg.get("profile_url", ""), mg.get("profile_text", ""),
                pk_id
            ))

        if not dry_run:
            for r in adds:
                insert_one(r)
            for r, dbr in merges:
                mg = merge_richer(r, dbr)
                update_one(dbr["id"], mg)
            for r in sames:
                insert_one(r)
            for r, dbr in ambs:
                if conflict_policy == "richer":
                    mg = merge_richer(r, dbr)
                    update_one(dbr["id"], mg)
                elif conflict_policy == "add":
                    insert_one(r)
            conn.commit()

        return {
            "dry_run": dry_run,
            "total_rows_parsed": len(extracted_records),
            "added_count": len(adds),
            "merged_same_dept_count": len(merges),
            "appended_diff_dept_count": len(sames),
            "ambiguous_dept_count": len(ambs),
            "conflict_policy": conflict_policy,
            "sample_adds": adds[:10],
            "sample_merges": [{"name": r["name"], "dept": r.get("department", ""), "title": r.get("title", "")} for r, _ in merges[:10]],
            "sample_ambiguous": [
                {"name": r["name"], "excel_dept": r.get("department", ""), "db_dept": dbr.get("department") or dbr.get("college", "")}
                for r, dbr in ambs[:10]
            ],
        }
    finally:
        conn.close()


def start_script_task(script_key, options):
    """
    启动爬虫或补全脚本任务（保留已有全部脚本及参数接口）：
    - scraper: sjtu_faculty_scraper.py [--force] [--with-research]
    - research: sjtu_scrape_research.py [--force]
    - fix_college: sjtu_fix_college.py
    - web_fix_college: sjtu_web_fix_college.py
    """
    script_map = {
        "scraper": ("全量/增量爬取教师基本信息", "sjtu_faculty_scraper.py"),
        "research": ("增量/全量爬取研究方向与简介", "sjtu_scrape_research.py"),
        "fix_college": ("从教师主页补扫缺失院系", "sjtu_fix_college.py"),
        "web_fix_college": ("从网络搜索补全缺失院系", "sjtu_web_fix_college.py"),
    }
    if script_key not in script_map:
        raise ValueError(f"未知脚本类型: {script_key}")

    label, script_name = script_map[script_key]
    if any(t.get("status")=="running" for t in TASKS.values()):
        raise ValueError("已有维护脚本正在运行，请完成后再启动。")
    database_backup()
    cmd = [sys.executable, "--internal-script", script_name] if getattr(sys,"frozen",False) else [sys.executable,"-u",str(SCRIPT_DIR/script_name)]
    if script_key == "scraper":
        if options.get("force"):
            cmd.append("--force")
        if options.get("with_research"):
            cmd.append("--with-research")
    elif script_key == "research":
        if options.get("force"):
            cmd.append("--force")

    task_id = f"task_{int(time.time() * 1000)}"
    task_info = {
        "id": task_id,
        "script_key": script_key,
        "name": label,
        "command": " ".join(cmd),
        "status": "running",
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": None,
        "logs": [f"[启动] {' '.join(cmd)}"],
    }

    with TASK_LOCK:
        TASKS[task_id] = task_info

    def _runner():
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(DATA_DIR),
                env={**os.environ,"JZ_DATA_DIR":str(DATA_DIR),"FACULTY_DB":str(DB_PATH)},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                clean_line = line.rstrip("\r\n")
                if clean_line:
                    with TASK_LOCK:
                        task_info["logs"].append(clean_line)
                        if len(task_info["logs"]) > 300:
                            task_info["logs"] = task_info["logs"][-300:]
            proc.wait()
            with TASK_LOCK:
                task_info["status"] = "completed" if proc.returncode == 0 else f"failed (code {proc.returncode})"
                task_info["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            with TASK_LOCK:
                task_info["logs"].append(f"[异常] {e}")
                task_info["status"] = "failed"
                task_info["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    return task_info


class FacultyRequestHandler(BaseHTTPRequestHandler):
    def _prepare_request(self):
        password=os.getenv("JZ_PASSWORD","")
        if password:
            supplied=""
            try:
                auth=self.headers.get("Authorization","")
                if auth.startswith("Basic "):supplied=base64.b64decode(auth[6:],validate=True).decode().split(":",1)[1]
            except (ValueError,IndexError,UnicodeError):pass
            if not hmac.compare_digest(supplied.encode(),password.encode()):
                self.send_response(401);self.send_header("WWW-Authenticate",'Basic realm="JunZheng Match", charset="UTF-8"');self.end_headers();return False
        origin=self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc.lower()!=self.headers.get("Host","").lower():
            self._send_json({"error":"请求来源不匹配。"},HTTPStatus.FORBIDDEN);return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site' and self.command!='GET':
            self._send_json({"error":"不接受跨站写入。"},HTTPStatus.FORBIDDEN);return False
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:cookie=SimpleCookie()
        token=cookie.get('jz_session')
        token=token.value if token else ''
        if not re.fullmatch('[a-f0-9]{64}',token):token=secrets.token_hex(32)
        self._session_token=token;_REQUEST_STATE.token=token
        return True

    def _security_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        if getattr(self,'_session_token',None):
            self.send_header('Set-Cookie',f'jz_session={self._session_token}; HttpOnly; SameSite=Strict; Path=/')

    def log_message(self, fmt, *args):
        # 保持终端输出简洁
        pass

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, content, content_type, download_filename=None):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        if download_filename:
            encoded_name = urllib.parse.quote(download_filename)
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"{encoded_name}\"; filename*=UTF-8''{encoded_name}",
            )
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length<0 or length>MAX_BODY:raise ValueError("请求过大，上传文件请控制在12MB以内。")
        if not self.headers.get('Content-Type','').startswith('application/json'):raise ValueError('请求须为JSON。')
        raw = self.rfile.read(length) if length > 0 else b"{}"
        result=json.loads(raw.decode("utf-8"))
        if not isinstance(result,dict):raise ValueError('请求须为JSON对象。')
        return result

    def do_GET(self):
        if self.path=="/health":return self._send_json({"status":"ok","service":"SJTU-JunZhengMatch"})
        if not self._prepare_request():return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            # 1. 静态页面文件
            if path in ("/", "/index.html"):
                content = (FRONTEND_DIR / "index.html").read_bytes()
                return self._send_bytes(content, "text/html; charset=utf-8")
            if path == "/theme.css":
                content = (FRONTEND_DIR / "theme.css").read_bytes()
                return self._send_bytes(content, "text/css; charset=utf-8")
            if path == "/app.js":
                content = (FRONTEND_DIR / "app.js").read_bytes()
                return self._send_bytes(content, "application/javascript; charset=utf-8")

            # 2. 文档接口 (README & ARCHITECTURE)
            if path == "/api/docs":
                doc_name = (qs.get("name", ["README"])[0]).upper()
                target = SCRIPT_DIR / ("ARCHITECTURE.md" if "ARCH" in doc_name else "README.md")
                text = target.read_text(encoding="utf-8") if target.exists() else "# 文档不存在"
                return self._send_json({"name": target.name, "content": text})

            # 3. 数据库统计与查询
            if path == "/api/db/stats":
                return self._send_json(get_db_stats())

            if path == "/api/db/list":
                res = query_faculty(
                    keyword=qs.get("keyword", [""])[0].strip(),
                    department=qs.get("department", [""])[0].strip(),
                    title=qs.get("title", [""])[0].strip(),
                    research=qs.get("research", [""])[0].strip(),
                    exclude_senior=qs.get("exclude_senior", ["false"])[0].lower() == "true",
                    only_has_research=qs.get("only_has_research", ["false"])[0].lower() == "true",
                    page=int(qs.get("page", ["1"])[0]),
                    page_size=int(qs.get("page_size", ["25"])[0]),
                )
                return self._send_json(res)

            if path == "/api/db/export_csv":
                conn = get_db_conn()
                try:
                    rows = conn.execute("""
                        SELECT name, title, COALESCE(NULLIF(department,''), college) AS dept,
                               email, phone, mobile, research_direction, profile_url
                        FROM faculty ORDER BY college, name
                    """).fetchall()
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow(["姓名", "职称", "院系", "邮箱", "电话", "手机", "研究方向", "个人主页"])
                    for r in rows:
                        writer.writerow(list(r))
                    return self._send_bytes(
                        buf.getvalue().encode("utf-8-sig"),
                        "text/csv; charset=utf-8",
                        "sjtu_faculty_database.csv",
                    )
                finally:
                    conn.close()

            # 4. 下载空白上传模板（单横行对齐格式，支持 .xlsx 和 .csv）
            if path == "/api/template":
                fmt = qs.get("format", ["xlsx"])[0].lower()
                tpl_type = qs.get("type", ["student"])[0].lower()
                if tpl_type == "example":
                    return self._send_bytes(xio.generate_example_template_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "虚构学生示例模板.xlsx")
                if fmt == "csv":
                    data = xio.generate_blank_template_csv(tpl_type)
                    fname = "教师增量导入空白模板.csv" if tpl_type == "teacher" else "学生课题上传空白模板.csv"
                    return self._send_bytes(data, "text/csv; charset=utf-8", fname)
                else:
                    data = xio.generate_blank_template_xlsx(tpl_type)
                    fname = "教师增量导入空白模板.xlsx" if tpl_type == "teacher" else "学生课题上传空白模板.xlsx"
                    return self._send_bytes(
                        data,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        fname,
                    )

            # 5. 导出最近一次匹配结果（横式 CSV 或 原表合并单元格 XLSX）
            if path == "/api/match/export":
                fmt = qs.get("format", ["csv"])[0].lower()
                cache = current_match_session()
                with SESSION_LOCK:
                    students = list(cache["students"])
                    results = list(cache["results"])
                    pick_count = cache["pick_count"]
                    banner_text = cache["banner_text"]
                    stem = cache["filename"] or "matched"

                if not students:
                    return self._send_json({"error": "当前暂无匹配结果，请先上传表格或载入示例数据进行匹配预览"}, status=HTTPStatus.BAD_REQUEST)

                if fmt == "csv":
                    csv_bytes = xio.generate_horizontal_csv(
                        students, results, pick_count=pick_count, tokenize_fn=matcher.tokenize
                    )
                    return self._send_bytes(
                        csv_bytes,
                        "text/csv; charset=utf-8",
                        f"{stem}_评审匹配结果_横式.csv",
                    )
                else:
                    xlsx_bytes = xio.generate_merged_table_xlsx(
                        students, results, pick_count=pick_count, banner_text=banner_text,
                        include_match_meta=False, tokenize_fn=matcher.tokenize,
                    )
                    return self._send_bytes(
                        xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        f"{stem}_评审匹配结果_合并单元格表.xlsx",
                    )

            # 6. 脚本后台任务状态查询
            if path == "/api/scripts/tasks":
                with TASK_LOCK:
                    task_list = list( reversed(list(TASKS.values())) )
                return self._send_json({"tasks": task_list})

            return self._send_json({"error": f"Not found: {path}"}, status=HTTPStatus.NOT_FOUND)
        except Exception as e:
            return self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        if not self._prepare_request():return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()

            # 1. 执行盲审匹配预览（支持上传文件 base64 或使用内置 sample.xlsx）
            if path == "/api/match/run":
                use_sample = bool(body.get("use_sample", False))
                if use_sample:
                    file_bytes = xio.generate_example_template_xlsx()
                    filename = "虚构学生示例.xlsx"
                else:
                    b64 = body.get("file_base64", "")
                    filename = body.get("filename", "uploaded.xlsx")
                    if not b64:
                        raise ValueError("请先选择要上传的学生课题表格文件（.xlsx 或 .csv）")
                    if "," in b64:
                        b64 = b64.split(",", 1)[1]
                    file_bytes = base64.b64decode(b64)

                res = run_match_pipeline(file_bytes, filename, body.get("params", {}))
                return self._send_json(res)

            if path.startswith('/api/db/'):
                if any(t.get('status')=='running' for t in TASKS.values()):raise ValueError('维护脚本运行中，暂不能人工修改数据库。')
                if not body.get('dry_run',False):database_backup()

            # 2. 数据库人工维护：新增、编辑、删除
            if path == "/api/db/create":
                res = create_faculty(body)
                return self._send_json(res)

            if path == "/api/db/update":
                rec_id = body.get("id") or body.get("teacher_id")
                if not rec_id:
                    raise ValueError("缺少教师记录 ID")
                res = update_faculty(rec_id, body)
                return self._send_json(res)

            if path == "/api/db/delete":
                rec_id = body.get("id") or body.get("teacher_id")
                if not rec_id:
                    raise ValueError("缺少教师记录 ID")
                res = delete_faculty(rec_id)
                return self._send_json(res)

            # 3. 外部教师 Excel/CSV 增量合并接口
            if path == "/api/db/merge":
                b64 = body.get("file_base64", "")
                filename = body.get("filename", "teachers.xlsx")
                dry_run = bool(body.get("dry_run", True))
                conflict_policy = body.get("conflict_policy", "richer")
                if not b64:
                    raise ValueError("请先选择要合并的教师数据表格（.xlsx 或 .csv）")
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                file_bytes = base64.b64decode(b64)
                res = merge_teachers_from_bytes(file_bytes, filename, dry_run=dry_run, conflict_policy=conflict_policy)
                return self._send_json(res)

            # 4. 启动爬虫/维护脚本接口
            if path == "/api/scripts/run":
                script_key = body.get("script_key", "")
                options = body.get("options", {})
                task_info = start_script_task(script_key, options)
                return self._send_json(task_info)

            return self._send_json({"error": f"Unknown endpoint: {path}"}, status=HTTPStatus.NOT_FOUND)
        except Exception as e:
            return self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)


def run_server(host="127.0.0.1", port=8765):
    if host not in ('127.0.0.1','localhost','::1') and len(os.getenv('JZ_PASSWORD',''))<12:
        raise ValueError('非本机访问须设置至少12字符的 JZ_PASSWORD。')
    server = ThreadingHTTPServer((host, port), FacultyRequestHandler)
    server.daemon_threads=True
    print(f"🚀 SJTU 䇹政盲审导师匹配与数据库维护平台已启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 服务已停止")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SJTU 䇹政盲审导师匹配与数据库管理 Web 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run_server(args.host, args.port)

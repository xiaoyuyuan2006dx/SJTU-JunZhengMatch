#!/usr/bin/env python3
"""
教师信息合并 —— Excel 教师数据 → SQLite

自动处理规则:
  1. DB 无此姓名 → 直接新增
  2. DB 有此姓名 + 同一院系 → 自动合并（保留信息更丰富的版本）
  3. DB 有此姓名 + 不同院系 → 直接追加（可能是同名不同人）
  4. 院系信息缺失无法判断 → 交互抛出

Usage:
  python sjtu_merge_teachers.py <excel>            # 正式合并
  python sjtu_merge_teachers.py <excel> --dry-run  # 预览
"""
import sys
import sqlite3
import os
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("需要: pip install pandas openpyxl")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("JZ_DATA_DIR", SCRIPT_DIR / "sjtu_faculty_data"))
DB_PATH = Path(os.getenv("FACULTY_DB", DATA_DIR / "sjtu_faculty_data.db"))

COLUMN_MAP = {
    "姓名": "name", "名字": "name", "name": "name", "教师姓名": "name",
    "拟定评审": "name",
    "职称": "title", "title": "title",
    "院系": "department", "学院": "department", "department": "department",
    "邮箱": "email", "email": "email", "mail": "email",
    "电话": "phone", "手机": "mobile", "phone": "phone", "mobile": "mobile",
    "研究方向": "research_direction", "研究领域": "research_direction", "research": "research_direction",
    "个人主页": "profile_url", "url": "profile_url",
}
EXCLUDE_COLS = ["导师", "学生", "指导", "课题", "序号"]
DB_FIELDS = ["title", "department", "college", "email", "phone",
             "mobile", "research_direction", "profile_url"]


def norm(s):
    return str(s).strip().lower().replace(" ", "").replace("\n", "")


def detect_columns(df):
    m = {}
    for col in df.columns:
        k = norm(col)
        if any(e in k for e in EXCLUDE_COLS):
            continue
        for pat, field in COLUMN_MAP.items():
            if norm(pat) in k or k in norm(pat):
                m[col] = field
                break
    return m


def read_excel(fp):
    raw = pd.read_excel(fp, header=None)
    hr = 0
    for i, row in raw.iterrows():
        cells = [str(v).strip() for v in row if pd.notna(v) and str(v).strip()]
        short = [c for c in cells if len(c) < 10]
        if len(short) >= 3 and any("姓名" in c or c in ("序号",) or c.startswith("序号") for c in cells):
            hr = i
            break
    df = pd.read_excel(fp, header=hr)
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how="all").reset_index(drop=True)


def db_by_name(cur, name):
    cur.execute("SELECT * FROM faculty WHERE name = ?", (name,))
    rows = cur.fetchall()
    if rows:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    return []


def filled(r):
    return sum(1 for f in DB_FIELDS if r.get(f, ""))


def richer(r1, r2):
    """保留信息更丰富的版本"""
    base, supp = (dict(r1), r2) if filled(r1) >= filled(r2) else (dict(r2), r1)
    for f in DB_FIELDS:
        if not base.get(f, "") and supp.get(f, ""):
            base[f] = supp[f]
    base["name"] = r1["name"]
    return base


def dept_of(r):
    return (r.get("department", "") or r.get("college", "")).strip()


def same_dept(r1, r2):
    d1, d2 = dept_of(r1), dept_of(r2)
    if not d1 or not d2:
        return None
    return d1 == d2


def show(r):
    parts = []
    for lb, k in [("姓名","name"),("职称","title"),("院系","department"),
                  ("邮箱","email"),("电话","phone"),("手机","mobile"),
                  ("研究方向","research_direction")]:
        v = r.get(k, "")
        if v:
            vs = str(v)[:80] + "..." if len(str(v)) > 80 else str(v)
            parts.append(f"{lb}:{vs}")
    return " | ".join(parts) if parts else "(无信息)"


def do_insert(cur, r):
    cur.execute("""INSERT INTO faculty
        (name,title,department,college,email,phone,mobile,research_direction,profile_url)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (r.get("name",""), r.get("title",""), r.get("department",""),
         r.get("department",""), r.get("email",""), r.get("phone",""),
         r.get("mobile",""), r.get("research_direction",""), r.get("profile_url","")))


def do_update(cur, name, merged):
    cur.execute("""UPDATE faculty SET
        name=?,title=?,department=?,college=?,
        email=?,phone=?,mobile=?,research_direction=?,profile_url=?
        WHERE name=?""",
        (merged.get("name",""), merged.get("title",""), merged.get("department",""),
         merged.get("college", merged.get("department","")), merged.get("email",""),
         merged.get("phone",""), merged.get("mobile",""), merged.get("research_direction",""),
         merged.get("profile_url",""), name))


def merge(fp, dry=False):
    print(f"\n📂 {fp}")
    df = read_excel(fp)
    print(f"   {len(df)} 行, 列: {list(df.columns)}")

    col_map = detect_columns(df)
    print(f"   映射:")
    for c, f in col_map.items():
        print(f"     {c} → {f}")
    if "name" not in col_map.values():
        print("\n❌ 无姓名列")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    all_names = [r[0] for r in cur.execute("SELECT name FROM faculty").fetchall()]

    adds, merges, sames, ambs = [], [], [], []

    for _, row in df.iterrows():
        rec = {}
        for ec, df_ in col_map.items():
            v = row[ec]
            if pd.notna(v) and str(v).strip():
                rec[df_] = str(v).strip()
        if "name" not in rec or not rec["name"]:
            continue
        dbr = db_by_name(cur, rec["name"])
        if not dbr:
            adds.append(rec)
        else:
            sd = same_dept(rec, dbr[0])
            if sd is True:
                merges.append((rec, dbr[0]))
            elif sd is False:
                sames.append(rec)
            else:
                ambs.append((rec, dbr[0]))

    print(f"\n{'='*50}")
    print(f"自动: 新增 {len(adds)} | 合并(同院系) {len(merges)} | 追加(不同院系) {len(sames)}")
    if ambs:
        print(f"需确认: {len(ambs)} (院系缺失，无法判断)")
    print(f"{'='*50}")

    an, mn, sn = 0, 0, 0

    for rec in adds:
        if not dry:
            do_insert(cur, rec)
        an += 1

    for rec, dbr in merges:
        mg = richer(rec, dbr)
        if dry:
            diffs = []
            for f in DB_FIELDS:
                o, n = str(dbr.get(f,"") or "")[:30], str(mg.get(f,"") or "")[:30]
                if o != n:
                    diffs.append(f"{f}: [{o}]→[{n}]")
            if diffs:
                print(f"  ✓ {rec['name']} | {'; '.join(diffs[:3])}")
        else:
            do_update(cur, dbr["name"], mg)
        mn += 1

    for rec in sames:
        if not dry:
            do_insert(cur, rec)
        if dry:
            print(f"  + {rec['name']} (同姓名不同院系，追加)")
        sn += 1

    # --- ambiguous ---
    if not ambs:
        conn.commit(); conn.close()
        print(f"\n✅ 全部自动: 新增 {an+sn}, 合并 {mn}")
        if dry:
            print("   (--dry-run)")
        return

    print(f"\n{'='*50}")
    print(f"⚠ 需确认 {len(amb)} 人 — DB有同名但院系信息不足")
    print(f"{'='*50}")
    for i, (rec, dbr) in enumerate(amb, 1):
        print(f"  [{i}] Excel: {show(rec)}")
        print(f"       DB:    {show(dbr)}")
        print()

    print("  [A]全加 [S]全跳 [1-5]范围加 [3]单处理 [Q]退出")
    done = set()
    aa, ak, am = 0, 0, 0

    while len(done) < len(amb):
        c = input("\n👉 ").strip()
        ch = c.upper()

        if ch == "A":
            for i in range(1, len(amb)+1):
                if i not in done:
                    if not dry:
                        do_insert(cur, amb[i-1][0])
                    done.add(i)
                    aa += 1
        elif ch == "S":
            for i in range(1, len(amb)+1):
                if i not in done:
                    done.add(i)
                    ak += 1
        elif ch == "Q":
            break
        elif "-" in c:
            try:
                a, b = map(int, c.split("-", 1))
                for i in range(a, b+1):
                    if 1 <= i <= len(amb) and i not in done:
                        if not dry:
                            do_insert(cur, amb[i-1][0])
                        done.add(i)
                        aa += 1
            except ValueError:
                print("   ❌ 格式: 1-5")
        elif c.isdigit():
            i = int(c)
            if 1 <= i <= len(amb) and i not in done:
                rec, dbr = amb[i-1]
                print(f"   [{i}] {show(rec)}")
                print(f"   DB:  {show(dbr)}")
                s = input("   [A]新增 [S]跳过 [M]合并: ").strip().upper()
                if s == "A":
                    if not dry:
                        do_insert(cur, rec)
                    done.add(i); aa += 1
                elif s == "S":
                    done.add(i); ak += 1
                elif s == "M":
                    mg = richer(rec, dbr)
                    if not dry:
                        do_update(cur, dbr["name"], mg)
                    done.add(i); am += 1
                    print(f"   ✓ 已合并")
        else:
            print("   ❌ A/S/1-5/3/Q")

    conn.commit(); conn.close()
    print(f"\n{'='*50}")
    print(f"✅ 新增(DB无) {an} | 合并(同院) {mn} | 追加(不同院) {sn}")
    print(f"   确认新增 {aa} | 确认合并 {am} | 跳过 {ak}")
    if dry:
        print("   (--dry-run)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sjtu_merge_teachers.py <excel> [--dry-run]")
        sys.exit(1)
    fp = sys.argv[1]
    dry = "--dry-run" in sys.argv
    if not Path(fp).exists():
        print(f"❌ 文件不存在: {fp}")
        sys.exit(1)
    merge(fp, dry=dry)

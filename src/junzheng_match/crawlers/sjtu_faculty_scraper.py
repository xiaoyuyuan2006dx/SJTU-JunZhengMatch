#!/usr/bin/env python3
"""
上海交通大学教师信息爬虫
Scrapes faculty data from https://faculty.sjtu.edu.cn/
Output: SQLite database with fields: 姓名, 职称, 院系, 电话, 邮箱, 研究方向, 个人主页

Usage:
  python sjtu_faculty_scraper.py                  # 跳过已有，只追加新教师
  python sjtu_faculty_scraper.py --force           # 全量重爬，覆盖已有
  python sjtu_faculty_scraper.py --with-research   # 同时爬研究方向（慢）
"""

import requests
import sqlite3
import re
import time
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path

# ============================================================
# Configuration
# ============================================================
BASE_URL = "https://faculty.sjtu.edu.cn"
JSON_ENDPOINT = f"{BASE_URL}/system/resource/tsites/advancesearch.jsp"
LISTING_URL = f"{BASE_URL}/xyjs_list.jsp"
# 数据保存到脚本所在目录下的 sjtu_faculty_data 文件夹
from ..preferences import PreferenceStore
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = PreferenceStore().data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR = DATA_DIR / "profiles"
DB_PATH = Path(os.getenv("FACULTY_DB", DATA_DIR / "sjtu_faculty_data.db"))
CSV_PATH = DATA_DIR / "sjtu_faculty.csv"

# Rate limiting
REQUEST_DELAY = 0.3  # seconds between requests
MAX_WORKERS = 8      # concurrent workers for profile scraping

# ============================================================
# All colleges/departments with their IDs
# ============================================================
COLLEGES = {
    1643: "船舶海洋与建筑工程学院",
    1664: "机械与动力工程学院",
    1701: "电子信息与电气工程学院",
    1744: "材料科学与工程学院",
    1889: "环境科学与工程学院",
    1801: "生物医学工程学院",
    1989: "航空航天学院",
    2881: "智慧能源创新学院",
    2901: "溥渊未来技术学院",
    1774: "数学科学学院",
    1776: "物理与天文学院",
    1831: "化学化工学院",
    1922: "致远学院",
    2038: "海洋学院",
    1793: "生命科学技术学院",
    1865: "农业与生物学院",
    2198: "医学院",
    1894: "药学院",
    1842: "安泰经济与管理学院",
    1898: "凯原法学院",
    1861: "外国语学院",
    1820: "人文学院",
    1921: "马克思主义学院",
    1857: "国际与公共事务学院",
    1911: "媒体与传播学院",
    1926: "体育系",
    1955: "上海交通大学上海高级金融学院",
    2028: "设计学院",
    1948: "教育学院",
    1954: "上海交大密西根学院",
    1928: "巴黎高科卓越工程师学院",
    1929: "上海交大-南加州大学文化创意产业学院",
    1950: "中欧国际工商学院",
    1934: "上海交通大学中英国际低碳学院",
    2891: "区域光纤通信网与新型光通信系统国家重点实验室",
    2758: "转化医学研究院",
    2642: "测试专用学院",
    2322: "中国金融研究院",
    2323: "空天技术研究院",
    2324: "新农村发展研究院",
    2325: "Med-X 研究院",
    2326: "Bio-X 研究院",
    2327: "创新设计研究中心",
    2328: "出版传媒研究院",
    2329: "中国城市治理研究院",
    2330: "董浩云航运与物流研究院",
    2331: "航空发动机研究院",
    2332: "燃气轮机研究院",
    2333: "汽车工程研究院",
    2334: "能源研究院",
    2335: "海洋研究院",
    1997: "系统生物医学研究院",
    2001: "人文艺术研究院",
    2002: "先进产业技术研究院",
    2336: "科学史与科学文化研究院",
    2007: "自然科学研究院",
    2337: "中国医院发展研究院",
    2339: "慕课研究院",
    2340: "李政道研究所",
    2341: "中国质量发展研究院",
    2023: "个性化医学研究院",
}

# ============================================================
# Database setup
# ============================================================
def init_db():
    """Create SQLite database with faculty table."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faculty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER UNIQUE,
            name TEXT NOT NULL,
            name_en TEXT,
            title TEXT,
            department TEXT,
            college TEXT,
            email TEXT,
            phone TEXT,
            mobile TEXT,
            research_direction TEXT,
            profile_url TEXT,
            address TEXT,
            fax TEXT,
            raw_json TEXT
        )
    """)
    # Indexes for matching
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON faculty(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_college ON faculty(college)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_department ON faculty(department)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_title ON faculty(title)")
    conn.commit()
    return conn


# ============================================================
# Step 1: Fetch all teachers from JSON endpoint
# ============================================================
def fetch_all_teachers_json():
    """
    Fetch all faculty from advancesearch.jsp JSON endpoint.
    Returns list of dicts with: teacherId, name, showName, url, mail, phone, mobilephone, address, fax
    """
    print("=" * 60)
    print("Step 1: Fetching all teachers from JSON endpoint...")
    print("=" * 60)

    params = {
        "collegeid": 0,
        "disciplineid": 0,
        "enrollid": 0,
        "pageindex": 1,
        "pagesize": 700,  # Get all in one request
        "rankid": 0,
        "degreeid": 0,
        "honorid": 0,
        "pinyin": "",
        "profilelen": 200,
        "teacherName": "",
        "searchDirection": "",
        "viewmode": 8,
        "viewid": 0,
        "siteOwner": 0,
        "viewUniqueId": 0,
        "showlang": "",
        "ispreview": "false",
        "ellipsis": "",
        "alignright": "false",
        "productType": 99,
    }

    try:
        resp = requests.get(JSON_ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"ERROR fetching JSON: {e}")
        return []

    teachers = data.get("teacherData", [])
    total = data.get("totalnum", 0)
    print(f"  Got {len(teachers)} teachers (total reported: {total})")

    # Normalize data
    result = []
    for t in teachers:
        result.append({
            "teacher_id": t.get("teacherId"),
            "name": t.get("name", "").strip(),
            "name_en": t.get("showName", "").strip(),
            "profile_url": t.get("url", "").strip(),
            "email": t.get("mail", "").strip(),
            "phone": t.get("phone", "").strip(),
            "mobile": t.get("mobilephone", "").strip(),
            "address": t.get("address", "").strip(),
            "fax": t.get("fax", "").strip(),
            "raw_json": json.dumps(t, ensure_ascii=False),
        })

    return result


# ============================================================
# Step 2: Scrape college listing pages for title & department
# ============================================================
def scrape_college_listing(college_id, college_name):
    """
    Scrape all listing pages for a given college.
    Returns list of dicts with: name, url, department, title
    """
    results = []
    page = 1

    while True:
        params = {
            "urltype": "tsites.CollegeTeacherList",
            "wbtreeid": 1001,
            "st": 0,
            "id": college_id,
            "lang": "zh_CN",
        }
        if page > 1:
            params["PAGENUM"] = page

        try:
            resp = requests.get(LISTING_URL, params=params, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            print(f"  ERROR fetching {college_name} page {page}: {e}")
            break

        # Parse teacher data embedded in JavaScript addimg() calls
        # Pattern: addimg("photo_url", "profile_url", "name", "id")
        js_teachers = re.findall(
            r'addimg\(["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\'](\d+)["\']\s*\)',
            html
        )

        # Parse HTML for department and title
        # Each teacher block: <div class="name">NAME</div> followed by <p> tags
        html_blocks = re.findall(
            r'<div class="name">([^<]+)</div>\s*(.*?)(?=<div class="name">|$)',
            html, re.DOTALL
        )

        # Build lookup: name -> {department, title} from HTML
        html_data = {}
        for name, block_html in html_blocks:
            name = name.strip()
            dept_match = re.search(r'所在单位[：:]\s*([^<]+)', block_html)
            title_match = re.search(r'职称[：:]\s*([^<]+)', block_html)
            html_data[name] = {
                "department": dept_match.group(1).strip() if dept_match else "",
                "title": title_match.group(1).strip() if title_match else "",
            }

        # Combine JS URLs with HTML department/title by matching names
        for photo_url, profile_url, name, teacher_id in js_teachers:
            name = name.strip()
            dept_title = html_data.get(name, {"department": "", "title": ""})
            results.append({
                "name": name,
                "url": f"{BASE_URL}{profile_url}" if profile_url.startswith("/") else profile_url,
                "department": dept_title.get("department", ""),
                "title": dept_title.get("title", ""),
                "college": college_name,
            })

        # Check if there are more pages
        total_pages_match = re.search(r'共(\d+)条.*?(\d+)/(\d+)', html)
        if total_pages_match:
            total_items = int(total_pages_match.group(1))
            current_page = int(total_pages_match.group(2))
            total_pages = int(total_pages_match.group(3))
            if current_page >= total_pages:
                break
        else:
            # Also check "下页" link
            if '下页' not in html or 'Next' not in html:
                # No next page link - might be only one page
                if not js_teachers:
                    break
                # Try next page anyway, break if empty
                if page >= 10:  # Safety limit
                    break

        page += 1
        time.sleep(REQUEST_DELAY)

    return results


def scrape_all_college_listings():
    """Scrape all college listing pages to get department and title."""
    print("\n" + "=" * 60)
    print("Step 2: Scraping college listing pages for title & department...")
    print("=" * 60)

    all_results = []
    total_colleges = len(COLLEGES)
    start_time = time.time()

    for i, (college_id, college_name) in enumerate(COLLEGES.items(), 1):
        # 动态 ETA
        elapsed = time.time() - start_time
        speed = i / elapsed if elapsed > 0 and i > 1 else 0
        remaining = total_colleges - i
        eta_sec = remaining / speed if speed > 0 else 0
        eta_str = f"{int(eta_sec // 60)}m{int(eta_sec % 60)}s" if eta_sec > 0 else "..."

        print(f"  [{i}/{total_colleges}] {college_name} (id={college_id})...",
              end=" ", flush=True)
        teachers = scrape_college_listing(college_id, college_name)
        all_results.extend(teachers)
        print(f"{len(teachers)} 位教师 | 速度:{speed:.1f}学院/s | 预计剩余:{eta_str}")

        time.sleep(REQUEST_DELAY)

    total_elapsed = time.time() - start_time
    print(f"\n  总耗时: {int(total_elapsed // 60)}m{int(total_elapsed % 60)}s")
    print(f"  Total teachers from college listings: {len(all_results)}")
    return all_results


# ============================================================
# Step 3: Match and merge data
# ============================================================
def match_and_merge(json_teachers, listing_teachers):
    """
    Match teachers from JSON endpoint with those from college listings.
    Matching by URL (primary) then by name.
    """
    print("\n" + "=" * 60)
    print("Step 3: Matching and merging data...")
    print("=" * 60)

    # Normalize URL: remove protocol and trailing slash for comparison
    def normalize_url(u):
        return re.sub(r'^https?://', '', u.lower().rstrip('/'))

    # Build lookup from listing data by URL
    listing_by_url = {}
    listing_by_name = {}
    for t in listing_teachers:
        url = normalize_url(t["url"])
        listing_by_url[url] = t
        name = t["name"].strip()
        if name not in listing_by_name:
            listing_by_name[name] = []
        listing_by_name[name].append(t)

    merged = []
    matched = 0
    unmatched = []

    for jt in json_teachers:
        url = normalize_url(jt["profile_url"])
        name = jt["name"].strip()

        # Try match by URL first
        listing_match = listing_by_url.get(url)

        # If no URL match, try by name
        if not listing_match:
            candidates = listing_by_name.get(name, [])
            if len(candidates) == 1:
                listing_match = candidates[0]
            elif len(candidates) > 1:
                # Multiple matches - try fuzzy URL matching
                for c in candidates:
                    if name.lower().replace(" ", "") in c["url"].lower():
                        listing_match = c
                        break

        if listing_match:
            matched += 1
        else:
            unmatched.append(jt)

        merged.append({
            "teacher_id": jt["teacher_id"],
            "name": jt["name"],
            "name_en": jt["name_en"],
            "title": listing_match["title"] if listing_match else "",
            "department": listing_match["department"] if listing_match else "",
            "college": listing_match["college"] if listing_match else "",
            "email": jt["email"],
            "phone": jt["phone"],
            "mobile": jt["mobile"],
            "profile_url": jt["profile_url"],
            "address": jt["address"],
            "fax": jt["fax"],
            "research_direction": "",  # To be filled in optional step
            "raw_json": jt["raw_json"],
        })

    print(f"  Matched: {matched}/{len(json_teachers)}")
    print(f"  Unmatched: {len(unmatched)}")

    if unmatched:
        print("  Unmatched teachers:")
        for t in unmatched[:10]:
            print(f"    - {t['name']} ({t['profile_url']})")
        if len(unmatched) > 10:
            print(f"    ... and {len(unmatched) - 10} more")

    return merged


# ============================================================
# Step 4 (Optional): Scrape individual profile pages for research direction
# ============================================================
def scrape_profile_page(url):
    """
    Scrape an individual faculty profile page.
    Returns dict with: research_direction, department, title
    """
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        return {"research_direction": "", "department": "", "title": ""}

    result = {
        "research_direction": "",
        "department": "",
        "title": "",
    }

    # Extract research direction - look for 研究方向 section
    # Pattern 1: In profile info section
    rd_patterns = [
        r'研究方向[：:]\s*<[^>]*>\s*([^<]+)',
        r'研究方向[：:]\s*([^<]+)',
        r'<span[^>]*>研究方向</span>[^<]*<[^>]*>([^<]+)',
    ]
    for pattern in rd_patterns:
        match = re.search(pattern, html)
        if match:
            result["research_direction"] = match.group(1).strip()
            break

    # Also look for multi-line research directions (in <p> or <div> blocks)
    if not result["research_direction"]:
        # Find the 研究方向 label and get the following content
        rd_block = re.search(
            r'研究方向[：:]\s*</[^>]+>\s*<[^>]+>\s*<[^>]*>\s*(.*?)\s*</',
            html, re.DOTALL
        )
        if rd_block:
            text = re.sub(r'<[^>]+>', ' ', rd_block.group(1)).strip()
            text = re.sub(r'\s+', ' ', text)
            result["research_direction"] = text

    # If still not found, try broader pattern
    if not result["research_direction"]:
        rd_match = re.search(
            r'研究方向[：:]\s*</div>\s*<div[^>]*>\s*(.*?)\s*</div>',
            html, re.DOTALL
        )
        if rd_match:
            text = re.sub(r'<[^>]+>', ' ', rd_match.group(1)).strip()
            text = re.sub(r'\s+', ' ', text)
            result["research_direction"] = text

    # Try to get department if we need it
    if not result["department"]:
        dept_match = re.search(r'所在单位[：:]\s*([^<\n]+)', html)
        if dept_match:
            result["department"] = dept_match.group(1).strip()

    # Try to get title if we need it
    if not result["title"]:
        title_match = re.search(r'职称[：:]\s*([^<\n]+)', html)
        if title_match:
            result["title"] = title_match.group(1).strip()

    return result


def scrape_research_directions(merged_data, max_workers=MAX_WORKERS):
    """
    For teachers missing research direction, scrape individual profile pages.
    Also fills in missing department/title if still empty.
    """
    print("\n" + "=" * 60)
    print("Step 4 (Optional): Scraping profile pages for research directions...")
    print("=" * 60)

    # Only scrape those missing research direction OR missing department/title
    to_scrape = [
        t for t in merged_data
        if not t["research_direction"] or not t["department"] or not t["title"]
    ]
    print(f"  Teachers to scrape: {len(to_scrape)}/{len(merged_data)}")

    if not to_scrape:
        print("  All data complete, skipping profile scraping.")
        return merged_data

    completed = 0
    errors = 0

    def process_one(teacher):
        nonlocal completed, errors
        url = teacher["profile_url"]
        if not url:
            return teacher

        time.sleep(REQUEST_DELAY)
        try:
            profile_data = scrape_profile_page(url)
            if profile_data.get("research_direction"):
                teacher["research_direction"] = profile_data["research_direction"]
            if profile_data.get("department") and not teacher["department"]:
                teacher["department"] = profile_data["department"]
            if profile_data.get("title") and not teacher["title"]:
                teacher["title"] = profile_data["title"]
        except Exception as e:
            errors += 1

        return teacher

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, t): t for t in to_scrape}
        for future in as_completed(futures):
            completed += 1
            if completed % 50 == 0 or completed == len(to_scrape):
                print(f"  Progress: {completed}/{len(to_scrape)} "
                      f"({100*completed//len(to_scrape)}%), errors: {errors}")

    print(f"  Done. {completed} profiles scraped, {errors} errors.")
    return merged_data


# ============================================================
# Step 5: Save to SQLite
# ============================================================
def save_to_db(conn, data, force=False):
    """Save merged faculty data to SQLite database."""
    print("\n" + "=" * 60)
    print("Step 5: Saving to database...")
    print("=" * 60)

    cursor = conn.cursor()
    inserted = 0
    updated = 0
    skipped = 0

    # 获取已有 teacher_id 集合
    if not force:
        existing_ids = set(r[0] for r in cursor.execute("SELECT teacher_id FROM faculty").fetchall())
    else:
        existing_ids = set()

    for t in data:
        tid = t["teacher_id"]

        if not force and tid in existing_ids:
            # 默认模式：跳过已有教师
            skipped += 1
            continue

        cursor.execute("""
            INSERT INTO faculty
                (teacher_id, name, name_en, title, department, college,
                 email, phone, mobile, research_direction, profile_url,
                 address, fax, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(teacher_id) DO UPDATE SET
                name=excluded.name,
                name_en=excluded.name_en,
                title=excluded.title,
                department=excluded.department,
                college=excluded.college,
                email=excluded.email,
                phone=excluded.phone,
                mobile=excluded.mobile,
                research_direction=excluded.research_direction,
                profile_url=excluded.profile_url,
                address=excluded.address,
                fax=excluded.fax,
                raw_json=excluded.raw_json
        """, (
            t["teacher_id"], t["name"], t["name_en"], t["title"],
            t["department"], t["college"], t["email"], t["phone"],
            t["mobile"], t["research_direction"], t["profile_url"],
            t["address"], t["fax"], t["raw_json"]
        ))
        if cursor.rowcount == 1:
            inserted += 1
        else:
            updated += 1

    conn.commit()
    print(f"  Inserted: {inserted}, Updated: {updated}, Skipped (already in DB): {skipped}")
    print(f"  Total records in DB: {conn.execute('SELECT COUNT(*) FROM faculty').fetchone()[0]}")


# ============================================================
# Summary report
# ============================================================
def print_summary(conn):
    """Print a summary of the scraped data."""
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("DATABASE SUMMARY")
    print("=" * 60)

    total = cursor.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]
    print(f"Total faculty: {total}")

    # Completeness stats
    stats = {
        "邮箱 (email)": "email",
        "电话 (phone or mobile)": "COALESCE(phone, '') || COALESCE(mobile, '')",
        "职称 (title)": "title",
        "院系 (department or college)": "COALESCE(department, '') || COALESCE(college, '')",
        "研究方向 (research direction)": "research_direction",
    }

    for label, field in stats.items():
        if "COALESCE" in field:
            count = cursor.execute(
                f"SELECT COUNT(*) FROM faculty WHERE {field} != ''"
            ).fetchone()[0]
        else:
            count = cursor.execute(
                f"SELECT COUNT(*) FROM faculty WHERE {field} IS NOT NULL AND {field} != ''"
            ).fetchone()[0]
        pct = 100 * count / total if total > 0 else 0
        print(f"  {label}: {count}/{total} ({pct:.1f}%)")

    # College distribution
    print("\n  Top colleges by faculty count:")
    colleges = cursor.execute("""
        SELECT college, COUNT(*) as cnt FROM faculty
        WHERE college != ''
        GROUP BY college ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    for college, cnt in colleges:
        print(f"    {college}: {cnt}")

    # Sample data
    print("\n  Sample entries:")
    rows = cursor.execute("""
        SELECT name, title, department, college, email, phone, research_direction
        FROM faculty WHERE email != '' LIMIT 5
    """).fetchall()
    for row in rows:
        name, title, dept, college, email, phone, rd = row
        rd_short = (rd[:50] + "...") if rd and len(rd) > 50 else rd
        print(f"    {name} | {title} | {dept or college} | {email} | {phone} | {rd_short}")


# ============================================================
# Export to CSV (optional convenience)
# ============================================================
def export_csv(conn, csv_path=None):
    if csv_path is None:
        csv_path = str(CSV_PATH)
    """Export faculty data to CSV."""
    import csv
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT name, title, COALESCE(NULLIF(department,''), college) as department_or_college,
               email, phone, mobile, research_direction, profile_url
        FROM faculty ORDER BY college, name
    """).fetchall()

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["姓名", "职称", "院系", "邮箱", "电话", "手机", "研究方向", "个人主页"])
        for row in rows:
            writer.writerow(row)

    print(f"\n  CSV exported to: {csv_path} ({len(rows)} rows)")


# ============================================================
# Main
# ============================================================
def main():
    force = "--force" in sys.argv
    with_research = "--with-research" in sys.argv

    print("=" * 60)
    print("上海交通大学教师信息爬虫")
    print("Shanghai Jiao Tong University Faculty Scraper")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Colleges to scan: {len(COLLEGES)}")
    print(f"Request delay: {REQUEST_DELAY}s")

    if force:
        print("Mode: --force (覆盖已有数据)")
    else:
        print("Mode: 默认 (跳过已有教师，只追加新教师)")

    if with_research:
        print("       --with-research (同时爬研究方向)")
    print()

    # Check dependencies
    try:
        import requests
    except ImportError:
        print("ERROR: 'requests' library not found. Install with: pip install requests")
        sys.exit(1)

    # Initialize database
    conn = init_db()

    # 检查是否已有数据
    existing_count = conn.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]
    if existing_count > 0 and not force:
        print(f"⚠ 数据库已有 {existing_count} 条记录，默认跳过已有教师。")
        print("  使用 --force 覆盖全部数据，或先删除数据库。")
        print()

    # Step 1: Fetch all teachers from JSON endpoint
    json_teachers = fetch_all_teachers_json()
    if not json_teachers:
        print("ERROR: Failed to fetch teacher data. Aborting.")
        sys.exit(1)

    # Step 2: Scrape college listing pages for title & department
    listing_teachers = scrape_all_college_listings()

    # Step 3: Match and merge
    merged_data = match_and_merge(json_teachers, listing_teachers)

    # Step 4 (Optional): Scrape profile pages for research direction
    if with_research:
        merged_data = scrape_research_directions(merged_data)
    else:
        missing_rd = sum(1 for t in merged_data if not t["research_direction"])
        print(f"\n  Skipping research direction scraping ({missing_rd} teachers missing).")
        print("  To include research direction scraping, run with: --with-research")

    # Step 5: Save to database
    save_to_db(conn, merged_data, force=force)

    # Print summary
    print_summary(conn)

    # Export CSV
    export_csv(conn)

    conn.close()
    print("\n✅ Done! Database saved to:", DB_PATH)
    print("   CSV saved to:", CSV_PATH)


if __name__ == "__main__":
    main()

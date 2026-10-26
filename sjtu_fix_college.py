#!/usr/bin/env python3
"""补扫缺失的院系信息 — 从个人主页文本中提取"""
import requests
import sqlite3
import re
import time
import os
from pathlib import Path
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("FACULTY_DB", SCRIPT_DIR / "sjtu_faculty_data" / "sjtu_faculty_data.db"))
MAX_WORKERS = 8
TIMEOUT = 12


def extract_college(html, soup):
    """从页面文本中提取院系名"""
    candidates = []

    # 方法1: "上海交通大学XXX学院/研究院/系/中心/实验室"
    for m in re.finditer(r'上海交通大[学學]([^\s，,。；;<\n]{2,30}?(?:学院|研究院|研究所|系|中心|实验室|基地))', html):
        name = '上海交通大学' + m.group(1)
        if name not in candidates and len(name) > 8:
            candidates.append(name)

    # 方法2: "(电子信息)与电气工程学院" → 电子信息与电气工程学院
    for m in re.finditer(r'(?:电子[^<]{0,5})?与电气工程学院', html):
        name = m.group(0).strip()
        if '电子' not in name:
            name = '电子信息' + name
        name = '上海交通大学' + name
        if name not in candidates:
            candidates.append(name)

    # 方法3: "XX学院" 独立出现（前后有交大上下文）
    body = soup.get_text()
    for m in re.finditer(r'(?:上海交通大学|SJTU|sjtu)[^\n]{0,30}?([^\s，,。；;]{2,16}(?:学院|研究院|研究所))', body):
        if m.group(1) not in [c.replace('上海交通大学','') for c in candidates]:
            candidates.append('上海交通大学' + m.group(1))

    # 方法4: 工作经历 tab-con
    for tc in soup.select('div.tab-con'):
        text = tc.get_text()
        for m in re.finditer(r'上海交通大[学學]([^\s，,。；;]{2,30}?(?:学院|研究院|研究所|系|中心|实验室))', text):
            name = '上海交通大学' + m.group(1)
            if name not in candidates:
                candidates.append(name)

    # 方法5: 个人简介 TabbedPanelsContent
    for tab in soup.select('div.TabbedPanelsContent'):
        text = tab.get_text()
        for m in re.finditer(r'上海交通大[学學]([^\s，,。；;]{2,30}?(?:学院|研究院|研究所|系|中心|实验室))', text):
            name = '上海交通大学' + m.group(1)
            if name not in candidates:
                candidates.append(name)

    # 方法6: "材料学院" → "材料科学与工程学院"
    short_map = {
        '材料学院': '上海交通大学材料科学与工程学院',
        '电信学院': '上海交通大学电子信息与电气工程学院',
        '电院': '上海交通大学电子信息与电气工程学院',
        '机动学院': '上海交通大学机械与动力工程学院',
        '船建学院': '上海交通大学船舶海洋与建筑工程学院',
        '生医学院': '上海交通大学生物医学工程学院',
        '空天学院': '上海交通大学航空航天学院',
        '化工学院': '上海交通大学化学化工学院',
        '数学学院': '上海交通大学数学科学学院',
        '物理学院': '上海交通大学物理与天文学院',
        '生命学院': '上海交通大学生命科学技术学院',
        '农生学院': '上海交通大学农业与生物学院',
        '药学院': '上海交通大学药学院',
        '法学院': '上海交通大学凯原法学院',
        '外国语学院': '上海交通大学外国语学院',
        '人文学院': '上海交通大学人文学院',
        '媒传学院': '上海交通大学媒体与传播学院',
        '设计学院': '上海交通大学设计学院',
        '教育学院': '上海交通大学教育学院',
        '体育系': '上海交通大学体育系',
        '密西根学院': '上海交通大学上海交大密西根学院',
        '环境学院': '上海交通大学环境科学与工程学院',
    }
    for short, full in short_map.items():
        if short in html or short in body:
            if full not in candidates:
                candidates.append(full)

    # 过滤太泛的
    filtered = [c for c in candidates if len(c) > 8 and c.count('学院') + c.count('系') + c.count('中心') + c.count('研究院') >= 1]
    return filtered[0] if filtered else ""


def fix_one(tid, url):
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        resp.encoding = 'utf-8'
    except Exception:
        return tid, None

    soup = BeautifulSoup(resp.text, 'html.parser')
    college = extract_college(resp.text, soup)
    return tid, college


def main():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT teacher_id, profile_url, name FROM faculty
        WHERE (college IS NULL OR college = '')
          AND (department IS NULL OR department = '')
          AND profile_url NOT LIKE '%tipmsg%'
          AND profile_url != ''
    """).fetchall()

    print(f"待补扫: {len(rows)} 人")
    found = 0

    def process(r):
        tid, url, name = r
        time.sleep(0.1)
        tid2, college = fix_one(tid, url)
        return tid2, college, name

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process, r): r for r in rows}
        for i, f in enumerate(as_completed(futures), 1):
            tid, college, name = f.result()
            if college:
                cur.execute("""
                    UPDATE faculty SET college = ?, department = ? WHERE teacher_id = ?
                """, (college, college, tid))
                found += 1
                print(f"  [{i}/{len(rows)}] {name} → {college}")
            else:
                print(f"  [{i}/{len(rows)}] {name} → 未找到")
            if i % 10 == 0:
                conn.commit()

    conn.commit()
    print(f"\n共补全: {found}/{len(rows)}")

    # 最终统计
    still_missing = cur.execute("""
        SELECT COUNT(*) FROM faculty
        WHERE (college IS NULL OR college = '')
          AND (department IS NULL OR department = '')
    """).fetchone()[0]
    print(f"仍缺失院系: {still_missing} 人")
    conn.close()


if __name__ == "__main__":
    main()

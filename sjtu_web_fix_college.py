#!/usr/bin/env python3
"""
通过网络搜索补全缺失的院系信息
用 Bing 搜索 "上海交通大学 {姓名} {已有线索}" → 从结果链接中提取学院名
"""
import requests
import sqlite3
import re
import time
import os
from pathlib import Path
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("FACULTY_DB", SCRIPT_DIR / "sjtu_faculty_data" / "sjtu_faculty_data.db"))

# 交大院系列表 → 用于从搜索结果URL中识别学院
SJTU_COLLEGES = {
    'soo.sjtu': '上海交通大学海洋学院',
    'gift.sjtu': '上海交通大学溥渊未来技术学院',
    'soe.sjtu': '上海交通大学教育学院',
    'psychology.sjtu': '上海交通大学心理学院',
    'law.sjtu': '上海交通大学凯原法学院',
    'sfl.sjtu': '上海交通大学外国语学院',
    'shss.sjtu': '上海交通大学人文学院',
    'smc.sjtu': '上海交通大学媒体与传播学院',
    'ds.sjtu': '上海交通大学设计学院',
    'speit.sjtu': '上海交通大学巴黎高科卓越工程师学院',
    'ji.sjtu': '上海交通大学上海交大密西根学院',
    'lcc.sjtu': '上海交通大学中英国际低碳学院',
    'ceibs.sjtu': '中欧国际工商学院',
    'saif.sjtu': '上海交通大学上海高级金融学院',
    'acem.sjtu': '上海交通大学安泰经济与管理学院',
    'sipa.sjtu': '上海交通大学国际与公共事务学院',
    'marx.sjtu': '上海交通大学马克思主义学院',
    'agri.sjtu': '上海交通大学农业与生物学院',
    'pharm.sjtu': '上海交通大学药学院',
    'shsmu': '上海交通大学医学院',
    'smc.sjtu': '上海交通大学媒体与传播学院',
    'tdli.sjtu': '上海交通大学李政道研究所',
    'ic2ev.sjtu': '上海交通大学溥渊未来技术学院',
    'sice.sjtu': '上海交通大学集成电路学院',
    'sese.sjtu': '上海交通大学环境科学与工程学院',
    'bme.sjtu': '上海交通大学生物医学工程学院',
    'aero.sjtu': '上海交通大学航空航天学院',
    'energy.sjtu': '上海交通大学智慧能源创新学院',
    'mse.sjtu': '上海交通大学材料科学与工程学院',
    'math.sjtu': '上海交通大学数学科学学院',
    'physics.sjtu': '上海交通大学物理与天文学院',
    'chemistry.sjtu': '上海交通大学化学化工学院',
    'zhiyuan.sjtu': '上海交通大学致远学院',
    'life.sjtu': '上海交通大学生命科学技术学院',
    'me.sjtu': '上海交通大学机械与动力工程学院',
    'naoce.sjtu': '上海交通大学船舶海洋与建筑工程学院',
    'seiee.sjtu': '上海交通大学电子信息与电气工程学院',
}

# 学院名关键词映射
COLLEGE_KEYWORDS = [
    ('电子信息与电气工程学院', ['电子信息与电气工程', '电院', 'SEIEE', 'seiee']),
    ('机械与动力工程学院', ['机械与动力工程', '机动学院', '机械工程']),
    ('船舶海洋与建筑工程学院', ['船舶海洋与建筑工程', '船建学院', 'NAOCE']),
    ('材料科学与工程学院', ['材料科学与工程', '材料学院', '材料工程']),
    ('环境科学与工程学院', ['环境科学与工程', '环境学院']),
    ('生物医学工程学院', ['生物医学工程', '生医学院']),
    ('航空航天学院', ['航空航天', '空天学院']),
    ('数学科学学院', ['数学科学', '数学学院']),
    ('物理与天文学院', ['物理与天文', '物理学院']),
    ('化学化工学院', ['化学化工', '化工学院', '化学系']),
    ('生命科学技术学院', ['生命科学技术', '生命学院']),
    ('农业与生物学院', ['农业与生物', '农生学院']),
    ('医学院', ['医学院', '瑞金医院', '仁济医院', '新华医院']),
    ('药学院', ['药学院']),
    ('安泰经济与管理学院', ['安泰经济与管理', '安泰经管', 'ACEM']),
    ('凯原法学院', ['凯原法学', '法学院']),
    ('外国语学院', ['外国语']),
    ('人文学院', ['人文学院']),
    ('国际与公共事务学院', ['国际与公共事务', '国务学院']),
    ('媒体与传播学院', ['媒体与传播', '媒传学院']),
    ('设计学院', ['设计学院']),
    ('教育学院', ['教育学院']),
    ('体育系', ['体育系']),
    ('心理学院', ['心理学院']),
    ('海洋学院', ['海洋学院']),
    ('集成电路学院', ['集成电路']),
    ('溥渊未来技术学院', ['溥渊未来技术', '溥渊', 'GIFT']),
    ('智慧能源创新学院', ['智慧能源']),
    ('致远学院', ['致远学院']),
    ('李政道研究所', ['李政道研究所', 'TDLI']),
    ('变革性分子前沿科学中心', ['变革性分子', '分子前沿']),
    ('学生创新中心', ['学生创新中心']),
    ('自然科学研究院', ['自然科学研究院']),
    ('系统生物医学研究院', ['系统生物医学']),
    ('Bio-X研究院', ['Bio-X']),
    ('Med-X研究院', ['Med-X']),
]


def search_bing(name, rd_hint=""):
    """用 Bing 搜索，返回前几条结果的摘要文本"""
    query = f"上海交通大学 {name} 学院"
    if rd_hint:
        query += f" {rd_hint[:30]}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(
            f"https://cn.bing.com/search?q={quote(query)}",
            headers=headers, timeout=10
        )
        if resp.status_code != 200:
            return ""
        return resp.text
    except Exception:
        return ""


def extract_college_from_html(html, name):
    """从 Bing 搜索结果 HTML 中提取学院名"""
    # 查找URL中的学院标识
    for domain, college in SJTU_COLLEGES.items():
        if domain in html:
            return college

    # 查找页面文本中的学院关键词
    text = re.sub(r'<[^>]+>', ' ', html)
    for college, keywords in COLLEGE_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return '上海交通大学' + college if not college.startswith('上海') else college

    # "XXX学院" 模式
    found = re.findall(r'上海交通大[学學]([^\s，,。；;<]{2,20}?(?:学院|研究院|研究所|系|中心))', text)
    if found:
        return '上海交通大学' + found[0]

    return ""


def main():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT teacher_id, name, research_direction, profile_url FROM faculty
        WHERE (college IS NULL OR college = '')
          AND (department IS NULL OR department = '')
        ORDER BY name
    """).fetchall()

    # 跳过没主页的（tipmsg）
    to_search = [(tid, name, rd) for tid, name, rd, url in rows
                 if 'tipmsg' not in (url or '')]

    print(f"待搜索: {len(to_search)} 人")
    found = 0

    for i, (tid, name, rd) in enumerate(to_search, 1):
        print(f"  [{i}/{len(to_search)}] {name}...", end=" ", flush=True)

        html = search_bing(name, rd or "")
        college = extract_college_from_html(html, name) if html else ""

        if college:
            cur.execute("""
                UPDATE faculty SET college = ?, department = ?
                WHERE teacher_id = ?
            """, (college, college, tid))
            found += 1
            print(f"→ {college}")
        else:
            print("未找到")

        # 批量提交
        if i % 5 == 0:
            conn.commit()
            time.sleep(1)  # Bing 限流

    conn.commit()
    print(f"\n补全: {found}/{len(to_search)}")

    still = cur.execute("""
        SELECT COUNT(*) FROM faculty
        WHERE (college IS NULL OR college = '')
          AND (department IS NULL OR department = '')
    """).fetchone()[0]
    print(f"仍缺失: {still} 人")
    conn.close()


if __name__ == "__main__":
    main()

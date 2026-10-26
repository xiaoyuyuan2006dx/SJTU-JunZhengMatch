#!/usr/bin/env python3
"""
只爬研究方向 + 个人简介 - 从已有 DB 读 URL，逐个爬教师主页，增量更新
Usage:
  python scrape_research.py           # 只爬还没研究方向的（增量）
  python scrape_research.py --all     # 全部重爬（覆盖已有研究方向）
  python scrape_research.py --force   # 同 --all
"""
import requests
import sqlite3
import sys
import time
import datetime
import os
from pathlib import Path
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# Config
from ..preferences import PreferenceStore
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = PreferenceStore().data_dir()
DB_PATH = Path(os.getenv("FACULTY_DB", DATA_DIR / "sjtu_faculty_data.db"))
MAX_WORKERS = 8
REQUEST_DELAY = 0.15
TIMEOUT = 15


def scrape_profile(profile_url):
    """爬一个教师主页，用 BeautifulSoup 解析 Tab 内容"""
    result = {
        "research_direction": "",
        "profile_text": "",
        "title": "",
        "department": "",
    }

    try:
        resp = requests.get(profile_url, timeout=TIMEOUT,
                          headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception:
        return result

    soup = BeautifulSoup(resp.text, "html.parser")

    # ============================================================
    # Template A: TabbedPanels（旧模板 — 有"研究方向"标签页）
    # ============================================================
    tabs_a = soup.select("li.TabbedPanelsTab")
    contents_a = soup.select("div.TabbedPanelsContent")

    if tabs_a:
        for tab, content in zip(tabs_a, contents_a):
            label = tab.get_text(strip=True)
            text = content.get_text(separator=" ", strip=True)
            if "研究方向" in label:
                result["research_direction"] = text
            elif "个人简介" in label or "简介" in label:
                result["profile_text"] = text

    # ============================================================
    # Template B: 侧边栏模板 — "研究领域" 在 div.tab-con 中
    #   侧边栏链接与 tab-con 顺序对应，研究领域是第一个
    # ============================================================
    tab_cons = soup.select("div.tab-con")
    sidebar_links = []
    for a in soup.select("h3 a, .leftNav a, .sideNav a"):
        txt = a.get_text(strip=True)
        if txt:
            sidebar_links.append(txt)

    # 找研究领域在侧边栏的位置
    rd_index = None
    for i, link in enumerate(sidebar_links):
        if "研究" in link:
            rd_index = i
            break

    if rd_index is not None and rd_index < len(tab_cons):
        rd_text = tab_cons[rd_index].get_text(separator=" ", strip=True)
        if rd_text:
            result["research_direction"] = rd_text

    # Template B 的个人简介 — 找包含"个人简介"的 tab-con 或页面可见文本
    if not result["profile_text"]:
        for tc in tab_cons:
            text = tc.get_text(separator=" ", strip=True)
            if "个人简介" in text:
                # 提取"个人简介"后面的内容
                idx = text.find("个人简介")
                result["profile_text"] = text[idx:].strip()
                break
        # 如果没有显式个人简介段，取第一个 tab-con 旁边的简介区
        if not result["profile_text"]:
            for div in soup.find_all("div"):
                cls = " ".join(div.get("class", []))
                if "profile" in cls.lower() or "intro" in cls.lower():
                    txt = div.get_text(separator=" ", strip=True)
                    if len(txt) > 20:
                        result["profile_text"] = txt
                        break

    # ============================================================
    # 通用：从基本信息区提取职称、院系
    # ============================================================
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if txt.startswith("职称") or txt.startswith("职称："):
            result["title"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif txt.startswith("所在单位") or txt.startswith("所在单位："):
            result["department"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()

    return result


def main():
    force_all = "--all" in sys.argv or "--force" in sys.argv

    print("=" * 60)
    print("研究方向爬虫 - 增量更新")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # 动态获取总数
    db_total = cur.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]

    # 查询待爬教师
    if force_all:
        rows = cur.execute("""
            SELECT teacher_id, profile_url, name FROM faculty
            WHERE profile_url != ''
            ORDER BY teacher_id
        """).fetchall()
    else:
        rows = cur.execute("""
            SELECT teacher_id, profile_url, name FROM faculty
            WHERE profile_url != ''
              AND (research_direction IS NULL OR research_direction = '')
            ORDER BY teacher_id
        """).fetchall()

    total = len(rows)
    already = cur.execute(
        "SELECT COUNT(*) FROM faculty WHERE research_direction != ''"
    ).fetchone()[0]

    print(f"数据库教师总数: {db_total}")
    print(f"已有研究方向: {already}/{db_total} ({100*already//db_total if db_total else 0}%)")
    print(f"待爬: {total}")
    print(f"并发: {MAX_WORKERS}")
    print()

    if total == 0:
        print("全部已有研究方向，无需爬取。")
        conn.close()
        return

    done = 0
    errors = 0
    found_rd = 0
    found_profile = 0
    found_title = 0
    found_dept = 0
    start_time = time.time()

    def process(row):
        tid, url, name = row
        time.sleep(REQUEST_DELAY)
        data = scrape_profile(url)
        return tid, name, data

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process, row): row for row in rows}

        for f in as_completed(futures):
            done += 1
            try:
                tid, name, data = f.result()
            except Exception:
                errors += 1
                continue

            updates = []
            params = []

            if data["research_direction"]:
                updates.append("research_direction = ?")
                params.append(data["research_direction"])
                found_rd += 1

            if data["profile_text"]:
                updates.append("profile_text = ?")
                params.append(data["profile_text"])
                found_profile += 1

            if data["title"] and not force_all:
                updates.append("title = CASE WHEN (title IS NULL OR title = '') THEN ? ELSE title END")
                params.append(data["title"])
                found_title += 1

            if data["department"] and not force_all:
                updates.append("department = CASE WHEN (department IS NULL OR department = '') THEN ? ELSE department END")
                params.append(data["department"])
                found_dept += 1

            if updates:
                params.append(tid)
                cur.execute(f"UPDATE faculty SET {', '.join(updates)} WHERE teacher_id = ?", params)

            # 每 30 条 commit + 报告（带动态 ETA）
            if done % 30 == 0 or done >= total:
                conn.commit()
                elapsed = time.time() - start_time
                speed = done / elapsed if elapsed > 0 else 0
                remaining = total - done
                eta_sec = remaining / speed if speed > 0 else 0
                eta_str = str(datetime.timedelta(seconds=int(eta_sec)))
                pct = 100 * done // total
                bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
                print(f"  [{done:>3}/{total}] [{bar}] {pct:>3}% | "
                      f"速度:{speed:.1f}/s | 预计剩余:{eta_str} | "
                      f"已获:{found_rd} 错误:{errors}  ",
                      end="\r" if done < total else "\n", flush=True)

    conn.commit()

    # 最终统计
    final_rd = cur.execute(
        "SELECT COUNT(*) FROM faculty WHERE research_direction != ''"
    ).fetchone()[0]
    final_profile = cur.execute(
        "SELECT COUNT(*) FROM faculty WHERE profile_text IS NOT NULL AND profile_text != ''"
    ).fetchone()[0]

    total_elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"完成! 总耗时: {datetime.timedelta(seconds=int(total_elapsed))}")
    print(f"  研究方向: {already} → {final_rd} (+{final_rd - already})")
    print(f"  个人简介: {final_profile}")
    print(f"  补充职称: {found_title}")
    print(f"  补充院系: {found_dept}")
    print(f"  错误: {errors}")
    conn.close()


if __name__ == "__main__":
    main()

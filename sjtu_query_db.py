#!/usr/bin/env python3
"""SJTU Faculty DB — python sjtu_query_db.py
j/k:移行  h/l:翻页(每页20人)  Tab:菜单  Enter:执行  Esc:取消  q:退"""
import sys, sqlite3, os
try:
    import termios, tty
except ImportError:
    termios = tty = None
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "sjtu_faculty_data" / "sjtu_faculty_data.db"

PAGE_SIZE = 20  # 每页固定20行

# 列宽(显示宽度)
CW = [8, 12, 19, 28, 49]

TABS = ["院系统计", "全部教师", "关键词搜索", "组合筛选", "编辑当前", "添加教师", "删除当前", "退出"]

# 学院简称映射
COLLEGE_SHORT = {
    "电子信息与电气工程学院": "电院",
    "机械与动力工程学院": "机动学院",
    "船舶海洋与建筑工程学院": "船建学院",
    "材料科学与工程学院": "材料学院",
    "环境科学与工程学院": "环境学院",
    "生物医学工程学院": "生医学院",
    "航空航天学院": "空天学院",
    "智慧能源创新学院": "智慧能源学院",
    "溥渊未来技术学院": "溥渊学院",
    "数学科学学院": "数院",
    "物理与天文学院": "物理天文学院",
    "化学化工学院": "化工学院",
    "致远学院": "致远学院",
    "海洋学院": "海洋学院",
    "生命科学技术学院": "生命学院",
    "农业与生物学院": "农生学院",
    "医学院": "医学院",
    "药学院": "药学院",
    "安泰经济与管理学院": "安泰经管",
    "凯原法学院": "法学院",
    "外国语学院": "外语学院",
    "外语学院": "外语学院",
    "人文学院": "人文学院",
    "马克思主义学院": "马克思学院",
    "国际与公共事务学院": "国务学院",
    "媒体与传播学院": "媒传学院",
    "体育系": "体育系",
    "上海高级金融学院": "高金",
    "设计学院": "设计学院",
    "教育学院": "教育学院",
    "密西根学院": "密西根学院",
    "巴黎高科卓越工程师学院": "巴黎高科学院",
    "巴黎卓越工程师学院": "巴黎高科学院",
    "中英国际低碳学院": "低碳学院",
    "李政道研究所": "李政道所",
    "集成电路学院": "集成电路学院",
    "计算机学院": "计算机学院",
    "计算机科学与工程系": "计算机系",
    "自动化与感知学院": "自动化学院",
    "自动化系": "自动化系",
    "心理学院": "心理学院",
    "变革性分子前沿科学中心": "分子前沿中心",
    "Bio-X研究院": "Bio-X研究院",
    "Bio-X 研究院": "Bio-X研究院",
    "Med-X研究院": "Med-X研究院",
    "Med-X 研究院": "Med-X研究院",
    "系统生物医学研究院": "系统生物医学院",
    "自然科学研究院": "自然科学研究院",
    "学生创新中心": "学生创新中心",
    "图书馆": "图书馆",
    "高等教育研究院": "高教院",
}


def clean_college_full(name):
    """去掉上海交通大学/上海交大前缀，保留完整院系名称（用于数据库存储与文件导出）"""
    s = str(name or "").strip()
    for prefix in ("上海交通大学", "上海交大"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
    return s


def short_college(name):
    """去掉上海交通大学前缀 + 用简称（用于前端预览展示）"""
    name = clean_college_full(name) or "-"
    for full, short in COLLEGE_SHORT.items():
        if full in name:
            name = name.replace(full, short)
            break
    return name


def connect():
    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row; return conn


def stats():
    c = connect()
    t = c.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]
    rd = c.execute("SELECT COUNT(*) FROM faculty WHERE research_direction!=''").fetchone()[0]
    em = c.execute("SELECT COUNT(*) FROM faculty WHERE email!=''").fetchone()[0]
    dp = c.execute("SELECT COUNT(*) FROM faculty WHERE (college!='' AND college IS NOT NULL) OR (department!='' AND department IS NOT NULL)").fetchone()[0]
    c.close(); return t, rd, em, dp


def load(mode="all", kw=None, col=None, rdk=None, nosen=False):
    c = connect(); conds = []; params = []
    if mode == "search" and kw:
        conds.append("(research_direction LIKE ? OR profile_text LIKE ? OR name LIKE ?)")
        params.extend([f"%{kw}%"]*3)
    if mode == "filter":
        if col: conds.append("(college LIKE ? OR department LIKE ?)"); params.extend([f"%{col}%"]*2)
        if rdk: conds.append("(research_direction LIKE ? OR profile_text LIKE ?)"); params.extend([f"%{rdk}%"]*2)
        if nosen: conds.append("(title NOT LIKE '%教授%' OR title LIKE '%副教授%') AND title NOT LIKE '%研究员%' AND title NOT LIKE '%特聘%' AND title NOT LIKE '%讲席%' AND title NOT LIKE '%主任医师%' AND title NOT LIKE '%首席%'")
    w = "WHERE " + " AND ".join(conds) if conds else ""
    rows = c.execute(f"""SELECT teacher_id,name,title,
        COALESCE(NULLIF(department,''),college) AS dept,
        email,phone,research_direction
        FROM faculty {w} ORDER BY dept,name""", params).fetchall()
    total = c.execute(f"SELECT COUNT(*) FROM faculty {w}", params).fetchone()[0]
    c.close(); return rows, total


def upd(tid, f, v):
    conn = sqlite3.connect(str(DB_PATH))
    if f == "department": conn.execute("UPDATE faculty SET department=?,college=? WHERE teacher_id=?",(v,v,tid))
    else: conn.execute(f"UPDATE faculty SET {f}=? WHERE teacher_id=?",(v,tid))
    conn.commit(); conn.close()


def delete(tid):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM faculty WHERE teacher_id=?",(tid,)); conn.commit(); conn.close()


def add(n, ti, dp, em, ph, rd):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("INSERT INTO faculty (name,title,department,college,email,phone,research_direction) VALUES (?,?,?,?,?,?,?)",(n,ti,dp,dp,em,ph,rd))
    conn.commit(); conn.close()


# ── CJK宽度 ──
try:
    import unicodedata
    def _wc(ch): return 2 if unicodedata.east_asian_width(ch) in 'FW' else 1
except ImportError:
    def _wc(ch): return 2 if ord(ch) > 127 else 1


def dw(s):
    return sum(_wc(ch) for ch in str(s))


def clip(s, width):
    s = str(s or '-')
    r, w = "", 0
    for ch in s:
        cw = _wc(ch)
        if w + cw > width: r += "…"; break
        r += ch; w += cw
    return r + " " * (width - w)


def fmt(d):
    # 院系用简称
    dept_str = short_college(d.get('dept', '-'))
    return (clip(d['name'], CW[0]), clip(d['title'], CW[1]),
            clip(dept_str, CW[2]), clip(d['email'], CW[3]),
            clip(d['research_direction'], CW[4]))


# ── 键盘 ──
def parse(b):
    if b == b'\x1b': return 'esc'
    if b == b'\t': return 'tab'
    if b in (b'\r', b'\n'): return 'enter'
    if b == b'\x7f': return 'bs'
    if b.startswith(b'\x1b['):
        s = b[2:].decode()
        return {'A':'up','B':'down','C':'right','D':'left','Z':'stab',
                '5~':'pgup','6~':'pgdn'}.get(s, '')
    try: return b.decode('utf-8')
    except: return ''


def getkey():
    return parse(os.read(0, 6))


# ── 读取输入（使用 draw_frame 重绘） ──
_CTX = {}
SAVED_TERMIOS = None

def read_input(msg, default=""):
    """读取输入 — cbreak 逐键，Esc 立即返回，支持中文多字节累积"""
    result = default
    buf = b""  # UTF-8 字节缓冲
    while True:
        _CTX['msg'] = msg + result
        draw_frame(**_CTX)
        raw = os.read(0, 6)
        if raw == b'\x1b':
            return None  # Esc: 立即取消
        if raw in (b'\r', b'\n'):
            return result if result else (default or None)
        if raw == b'\x7f':
            result = result[:-1]
            continue
        # 跳过方向键等控制序列
        if raw.startswith(b'\x1b['):
            continue
        # 多字节 UTF-8
        try:
            ch = raw.decode('utf-8')
            result += ch
        except UnicodeDecodeError:
            continue


def read_choice(msg):
    """读取单键 — Esc 取消，Enter 确认"""
    while True:
        _CTX['msg'] = msg
        draw_frame(**_CTX)
        raw = os.read(0, 6)
        if raw == b'\x1b':
            return None
        if raw in (b'\r', b'\n'):
            return ''  # 空确认
        if raw.startswith(b'\x1b['):
            continue
        try:
            return raw.decode('utf-8').strip()
        except UnicodeDecodeError:
            continue


def mv(y, x):
    return f"\033[{y};{x}H"


def pad_line(line, width):
    """补空格到指定显示宽度（CJK-aware）"""
    cur = dw(line)
    if cur >= width:
        return line[:width] if width > 0 else ""
    return line + " " * (width - cur)


def flush(buf):
    sys.stdout.write("\033[H\033[2J\033[3J" + "\r\n".join(buf))
    sys.stdout.flush()


def draw_frame(w, h, page_size, start, cur, tab, mode, rows, total, page, msg):
    """绝对定位—左右边框独立绘制，避免ANSI码干扰宽度"""
    out = ["\033[H\033[2J\033[3J"]
    t, rc, em, dp = stats()
    inner_w = w - 2
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    YEL = "\033[33m"  # 藤田琴音黄
    RST = "\033[0m"

    def lb(y): return mv(y, 1) + YEL + "│" + RST
    def rb(y): return mv(y, w) + YEL + "│" + RST

    # ── 顶边 ──
    out.append(mv(1, 1) + YEL + "┌" + "─" * inner_w + "┐" + RST)

    # 顶栏
    bar = (f" SJTU Faculty DB  教师:{t} 院系:{100*dp//max(t,1)}% 方向:{100*rc//max(t,1)}% "
           f"邮箱:{100*em//max(t,1)}% {total}条  {page+1}/{total_pages}页")
    out.append(lb(2))
    out.append(mv(2, 2) + f"\033[30;46m{bar[:inner_w]}\033[0m")
    out.append(rb(2))

    # 菜单
    ml = ""
    for i, nm in enumerate(TABS):
        ml += f"\033[7m {nm} \033[0m" if i == tab else f"  {nm}  "
    out.append(lb(3))
    out.append(mv(3, 2) + ml[:inner_w])
    out.append(rb(3))

    # 表头
    hdr = "".join(clip(h, CW[i]) for i, h in enumerate(["姓名","职称","院系","邮箱","研究方向"]))
    out.append(lb(4))
    out.append(mv(4, 2) + f"\033[1m{hdr[:inner_w]}\033[0m")
    out.append(rb(4))

    # 表头分隔
    out.append(lb(5))
    out.append(mv(5, 2) + "─" * inner_w)
    out.append(rb(5))

    # 数据行
    for i in range(page_size):
        ri = start + i
        y = 6 + i
        out.append(lb(y))
        if ri < len(rows):
            d = dict(rows[ri])
            parts = fmt(d)
            line = "".join(parts)[:inner_w]
            padded = pad_line(line, inner_w)
            if i == cur:
                out.append(mv(y, 2) + f"\033[37;44m{padded}\033[0m")
            elif i % 2:
                out.append(mv(y, 2) + f"\033[2m{padded}\033[0m")
            else:
                out.append(mv(y, 2) + padded)
        else:
            out.append(mv(y, 2) + " " * inner_w)
        out.append(rb(y))

    sep_y = 6 + page_size
    msg_y = sep_y + 1
    foot_y = msg_y + 1
    bot_y = foot_y + 1

    out.append(lb(sep_y))
    out.append(mv(sep_y, 2) + "─" * inner_w)
    out.append(rb(sep_y))

    out.append(lb(msg_y))
    out.append(mv(msg_y, 2) + (msg or " ")[:inner_w].ljust(inner_w)[:inner_w])
    out.append(rb(msg_y))

    footer = f" j/k:移行 h/l:翻页 Tab:菜单 Enter:执行 Esc:取消 e:编辑 d:删 a:加 /:搜 q:退 "
    out.append(lb(foot_y))
    out.append(mv(foot_y, 2) + f"\033[30;47m{footer[:inner_w]}\033[0m")
    out.append(rb(foot_y))

    note = " ♪ Taro & ZhuXueBu © 2026 Gratitude Deepseek-v4-pro Claude"
    out.append(lb(foot_y + 1))
    out.append(mv(foot_y + 1, 2) + f"\033[33m{note:<{inner_w}}\033[0m")
    out.append(rb(foot_y + 1))

    out.append(mv(foot_y + 2, 1) + YEL + "└" + "─" * inner_w + "┘" + RST)

    sys.stdout.write("".join(out))
    sys.stdout.flush()


# ── 主程序 ──
def main():
    global SAVED_TERMIOS
    fd = sys.stdin.fileno()
    SAVED_TERMIOS = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    mode = "all"
    rows, total = load("all")
    page = 0      # 当前页码 (0-based)
    cur = 0       # 页内光标行 (0~PAGE_SIZE-1)
    tab = 1       # 菜单选中索引
    msg = ""

    try:
        while True:
            # 固定宽度 = 列宽总和 + 左边框(1) + 右边框(1)
            w = sum(CW) + 2
            page_size = PAGE_SIZE
            total_pages = max(1, (len(rows) + page_size - 1) // page_size)
            page = max(0, min(page, total_pages - 1))
            start = page * page_size
            page_rows = min(page_size, len(rows) - start)
            cur = max(0, min(cur, page_rows - 1)) if page_rows > 0 else 0

            _CTX.update(w=w, h=60, page_size=page_size, start=start, cur=cur, tab=tab,
                        mode=mode, rows=rows, total=total, page=page, msg=msg)
            draw_frame(**_CTX)
            k = getkey()

            # ── 全局快捷键 ──
            if k == 'q': break
            if k == 'esc':
                msg = ""
                continue

            if k == 'tab':
                tab = (tab + 1) % len(TABS)
            elif k == 'stab':
                tab = (tab - 1) % len(TABS)

            elif k in ('up', 'k'):
                if page_rows > 0: cur = max(cur - 1, 0)
            elif k in ('down', 'j'):
                if page_rows > 0: cur = min(cur + 1, page_rows - 1)
            elif k in ('right', 'l'):
                page = min(page + 1, total_pages - 1); cur = 0
            elif k in ('left', 'h'):
                page = max(page - 1, 0); cur = 0

            # ── Enter: 执行菜单 ──
            elif k == 'enter':
                nm = TABS[tab]

                # ── 院系统计 ──
                if nm == "院系统计":
                    mode = "stats"
                    c = connect()
                    sr = c.execute("SELECT COALESCE(NULLIF(college,''),'(无)') AS c, COUNT(*) AS n FROM faculty GROUP BY c ORDER BY n DESC").fetchall()
                    ta = c.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]; c.close()
                    rows = [{"name":str(r['n']),"title":"","dept":short_college(r['c']),"email":"","research_direction":""} for r in sr]
                    total = len(rows); page = 0; cur = 0
                    msg = f"{total} 个院系 | {ta} 位教师"

                # ── 全部教师 ──
                elif nm == "全部教师":
                    mode = "all"; rows, total = load("all"); page = 0; cur = 0
                    msg = f"全部 {total} 位"

                # ── 关键词搜索 ──
                elif nm == "关键词搜索":
                    kw = read_input("搜索(姓名/研究方向关键词): ")
                    if kw:
                        mode = "search"; rows, total = load("search", kw=kw)
                        page = 0; cur = 0; msg = f"「{kw}」→ {total} 人"
                    else:
                        msg = ""

                # ── 组合筛选 ──
                elif nm == "组合筛选":
                    col = read_input("院系关键词 (回车跳过): ")
                    if col is None: msg = ""; continue
                    rdk = read_input("方向关键词 (回车跳过): ") if col else ""
                    if rdk is None: msg = ""; continue
                    c2 = read_choice("排除正高级? (y/n): ")
                    ns = (c2 == 'y')
                    mode = "filter"
                    rows, total = load("filter", col=(col or None), rdk=(rdk or None), nosen=ns)
                    page = 0; cur = 0; msg = f"筛选 → {total} 人"

                # ── 编辑当前 ──
                elif nm == "编辑当前":
                    if not rows or start + cur >= len(rows):
                        msg = "无可编辑项"; continue
                    r = dict(rows[start + cur])
                    fk = read_choice(f"编辑 {r['name']} — 改哪个字段? (1姓名 2职称 3院系 4邮箱 5电话 6方向): ")
                    if fk is None: msg = ""; continue
                    fm = {'1':'name','2':'title','3':'department','4':'email','5':'phone','6':'research_direction'}
                    if fk not in fm: msg = ""; continue
                    nv = read_input(f"新值({fm[fk]}): ")
                    if nv:
                        upd(r['teacher_id'], fm[fk], nv)
                        rows, total = load(mode)
                        msg = f"✓ {r['name']} → 已更新"
                    else:
                        msg = ""

                # ── 添加教师 ──
                elif nm == "添加教师":
                    nv = read_input("添加 — 姓名,职称,院系,邮箱,电话,方向 (逗号分隔): ")
                    if nv:
                        parts = [p.strip() for p in nv.split(",")]
                        if len(parts) >= 4:
                            add(parts[0], parts[1], parts[2], parts[3],
                                parts[4] if len(parts)>4 else "",
                                parts[5] if len(parts)>5 else "")
                            rows, total = load(mode)
                            msg = f"✓ 已添加: {parts[0]}"
                        else:
                            msg = "格式错误: 至少4个字段(姓名,职称,院系,邮箱)"
                    else:
                        msg = ""

                # ── 删除当前 ──
                elif nm == "删除当前":
                    if not rows or start + cur >= len(rows):
                        msg = "无可删除项"; continue
                    r = rows[start + cur]
                    ck = read_choice(f"确认删除 {r['name']}? (y/n): ")
                    if ck == 'y':
                        delete(r['teacher_id'])
                        rows, total = load(mode)
                        if page * PAGE_SIZE >= len(rows):
                            page = max(0, (len(rows)-1)//PAGE_SIZE)
                        cur = min(cur, max(0, (len(rows)-1) % PAGE_SIZE))
                        msg = f"✓ 已删除"
                    else:
                        msg = ""

                # ── 退出 ──
                elif nm == "退出":
                    break

            # ── 快捷键 ──
            elif k == 'e':
                if rows and start + cur < len(rows):
                    r = dict(rows[start + cur])
                    fk = read_choice(f"编辑 {r['name']} — (1姓名 2职称 3院系 4邮箱 5电话 6方向): ")
                    if fk is None: msg = ""; continue
                    fm = {'1':'name','2':'title','3':'department','4':'email','5':'phone','6':'research_direction'}
                    if fk not in fm: msg = ""; continue
                    nv = read_input(f"新值: ")
                    if nv:
                        upd(r['teacher_id'], fm[fk], nv)
                        rows, total = load(mode)
                        msg = f"✓ {r['name']} → 已更新"
                    else:
                        msg = ""

            elif k == 'd':
                if rows and start + cur < len(rows):
                    r = rows[start + cur]
                    ck = read_choice(f"确认删除 {r['name']}? (y/n): ")
                    if ck == 'y':
                        delete(r['teacher_id'])
                        rows, total = load(mode)
                        if page * PAGE_SIZE >= len(rows):
                            page = max(0, (len(rows)-1)//PAGE_SIZE)
                        cur = min(cur, max(0, (len(rows)-1) % PAGE_SIZE))
                        msg = f"✓ 已删除"

            elif k == 'a':
                nv = read_input("添加 — 姓名,职称,院系,邮箱,电话,方向 (逗号分隔): ")
                if nv:
                    parts = [p.strip() for p in nv.split(",")]
                    if len(parts) >= 4:
                        add(parts[0], parts[1], parts[2], parts[3],
                            parts[4] if len(parts)>4 else "",
                            parts[5] if len(parts)>5 else "")
                        rows, total = load(mode)
                        msg = f"✓ 已添加: {parts[0]}"

            elif k == '/':
                kw = read_input("搜索(姓名/方向): ")
                if kw:
                    mode = "search"; rows, total = load("search", kw=kw)
                    page = 0; cur = 0; msg = f"「{kw}」→ {total} 人"

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, SAVED_TERMIOS)
        sys.stdout.write("\033[H\033[2J\033[3J\033[?25h")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
纯标准库实现的 Excel (.xlsx) / CSV 读写与导出引擎
无需依赖 pandas 或 openpyxl（若已安装也可无缝配合），支持：
1. 读取任意 .xlsx / .csv 文件（自动定位表头行、提取任务说明行、读取学生或教师记录）
2. 导出带合并单元格和原表样式的 .xlsx（保留任务横幅或生成标准表头，每个学生 K 行纵向合并 A-G 列）
3. 导出横式 CSV（每位学生占 1 行，展开 评审1..K 及匹配方向、相近程度，不含人工核验列）
4. 生成空白单行对齐上传模板（.xlsx 和 .csv，单横行对齐表头，供用户下载填写上传）
"""
import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

STUDENT_BASE_COLS = ["序号", "课题类别", "学生姓名", "学生学号", "课题中文", "导师姓名", "导师院系"]
REVIEWER_BASE_COLS = ["拟定评审", "学院", "职称", "电话", "邮箱", "研究方向"]

DEFAULT_TASK_BANNER = (
    "任务名称：xxxx-202x春/秋䇹政结项盲审材料评审匹配\n\n"
    "任务要求：\n"
    "        1.\n"
    "        2.请注意，同学匹配的评审导师不能与自己的指导老师相同。\n"
    "        3.请注意，不要匹配正高级以上职称的评审老师。\n"
    "        4.若遇到无法解决的问题，在䇹政答疑群中询问。\n"
    "        5.本次评审任务时间较紧，请值班部员提高效率尽早评审完成，负责人在此表示衷心的感谢！\n\n"
    "负责人：\n"
    "截止日期：x月x日（xx周周x）晚20:00"
)


def fictional_students():
    topics = [
        ("信息技术类", "面向教学场景的图像理解方法研究", "计算机学院"),
        ("信息技术类", "机器人路径规划与运动控制方法研究", "自动化与感知学院"),
        ("生农医药类", "植物逆境响应与基因调控研究", "农业与生物学院"),
        ("文史哲经管类", "数字平台竞争行为的法律规制研究", "凯原法学院"),
        ("能源化工材料类", "储能材料循环利用与电化学性能研究", "材料科学与工程学院"),
        ("文史哲经管类", "汉语语料与语言认知研究", "人文学院"),
    ]
    return [dict(seq=i+1,category=category,name="示例学生"+"甲乙丙丁戊己"[i],
                 student_id=f"DEMO-{i+1:04d}",topic=topic,advisor="示例导师"+"甲乙丙丁戊己"[i],
                 advisor_dept=dept) for i,(category,topic,dept) in enumerate(topics)]


def generate_example_template_xlsx():
    students=fictional_students()
    return generate_merged_table_xlsx(students,[[] for _ in students],pick_count=3)



def safe_csv_writer(stream):
    raw=csv.writer(stream)
    class Writer:
        def writerow(self,values):
            def literal(value):
                text=str(value if value is not None else '')
                return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else value
            return raw.writerow([literal(value) for value in values])
    return Writer()


def col_letter_to_index(col_str):
    """'A' -> 0, 'B' -> 1, 'Z' -> 25, 'AA' -> 26"""
    idx = 0
    for ch in col_str.upper():
        if 'A' <= ch <= 'Z':
            idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


def col_index_to_letter(idx):
    """0 -> 'A', 1 -> 'B', 25 -> 'Z', 26 -> 'AA'"""
    res = []
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res.append(chr(ord('A') + rem))
    return "".join(reversed(res))


def clean_cell_str(val):
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("nan", "none"):
        return ""
    # 防止学号、序号、电话变成 524030910086.0 或 1.0
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def read_xlsx_rows(file_bytes_or_path):
    """
    使用纯标准库解析 .xlsx 的第一个工作表，返回二维列表 rows: List[List[str]]
    以及第一行 A1 的原始文本（如果是任务横幅）。
    """
    with zipfile.ZipFile(file_bytes_or_path, "r") as z:
        if len(z.infolist()) > 3000 or sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
            raise ValueError("工作簿解压内容过大，请移除无用空白行和图片后重试。")
        ns = {"s": NS_MAIN}
        sst = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sst_root.findall("s:si", ns):
                sst.append("".join(si.itertext()))

        # 找到第一个 sheet 的路径
        sheet_path = "xl/worksheets/sheet1.xml"
        if "xl/workbook.xml" in z.namelist() and "xl/_rels/workbook.xml.rels" in z.namelist():
            wb_root = ET.fromstring(z.read("xl/workbook.xml"))
            rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            rid_map = {}
            for rel in rels_root:
                rid_map[rel.attrib.get("Id")] = rel.attrib.get("Target")
            first_sheet = wb_root.find(".//s:sheet", ns)
            if first_sheet is not None:
                rid = first_sheet.attrib.get(f"{{{NS_REL}}}id")
                target = rid_map.get(rid, "")
                if target:
                    target = target.lstrip("/")
                    if not target.startswith("xl/"):
                        target = "xl/" + target
                    if target in z.namelist():
                        sheet_path = target

        sheet_root = ET.fromstring(z.read(sheet_path))
        rows_data = []
        max_col = 0
        parsed_rows = []

        for r_el in sheet_root.findall(".//s:row", ns):
            row_dict = {}
            for c_el in r_el.findall("s:c", ns):
                ref = c_el.attrib.get("r", "")
                m = re.match(r"([A-Z]+)(\d+)", ref)
                c_idx = col_letter_to_index(m.group(1)) if m else len(row_dict)
                t = c_el.attrib.get("t", "")
                v_el = c_el.find("s:v", ns)
                is_el = c_el.find("s:is", ns)
                val = ""
                if v_el is not None and v_el.text is not None:
                    val = v_el.text
                    if t == "s" and val.isdigit() and int(val) < len(sst):
                        val = sst[int(val)]
                elif is_el is not None:
                    val = "".join(is_el.itertext())
                row_dict[c_idx] = val
                if c_idx + 1 > max_col:
                    max_col = c_idx + 1
            parsed_rows.append(row_dict)

        for row_dict in parsed_rows:
            row_list = [row_dict.get(i, "") for i in range(max_col)]
            rows_data.append(row_list)

        return rows_data


def read_tabular_rows(file_bytes, filename=""):
    """同时支持 .xlsx 与 .csv 文件字节读取，返回 List[List[str]]"""
    fname = (filename or "").lower()
    if fname.endswith(".csv") or (not fname.endswith(".xlsx") and not file_bytes.startswith(b"PK")):
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                text = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = file_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        return [list(r) for r in reader]
    return read_xlsx_rows(io.BytesIO(file_bytes))


def parse_students_from_rows(rows):
    """
    从二维表格行中识别表头行、任务横幅，以及所有学生行记录。
    既支持有任务说明横幅 + 3行合并单元格的原表，也支持单行紧凑对齐的空白模板填写表。
    返回:
      students: List[dict]
      headers: List[str]
      banner_text: str (若原表第1行有任务说明则保留，否则为 "")
    """
    if not rows:
        raise ValueError("上传的文件为空")

    header_row_idx = None
    banner_text = ""

    for i, row in enumerate(rows):
        cleaned = [clean_cell_str(c) for c in row]
        non_empty = [c for c in cleaned if c]
        if not non_empty:
            continue
        joined = " ".join(non_empty)
        if ("序号" in cleaned or "学生姓名" in cleaned or "课题中文" in cleaned or "课题" in cleaned) and len(non_empty) >= 3:
            header_row_idx = i
            break
        if i == 0 and ("任务名称" in joined or "任务要求" in joined or len(joined) > 40):
            banner_text = non_empty[0]

    if header_row_idx is None:
        raise ValueError("缺少必要列：未找到包含【序号、学生姓名、课题中文(或课题)、导师姓名】的表头行")

    headers = [clean_cell_str(c) for c in rows[header_row_idx]]
    col_pos = {h: idx for idx, h in enumerate(headers) if h}

    required = {"序号", "学生姓名", "导师姓名"}
    if not required.issubset(set(col_pos.keys())) or not ({"课题中文", "课题"} & set(col_pos.keys())):
        raise ValueError("缺少必要列：序号、学生姓名、导师姓名，以及课题中文（或课题）")

    students = []
    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        def get_col(name):
            idx = col_pos.get(name)
            if idx is None or idx >= len(row):
                return ""
            return clean_cell_str(row[idx])

        seq_str = get_col("序号")
        name_str = get_col("学生姓名")
        topic_str = get_col("课题中文") or get_col("课题")
        advisor_str = get_col("导师姓名")

        # 跳过合并单元格的空白子行或全空行
        if not seq_str and not name_str and not topic_str:
            continue
        if not seq_str:
            # 如果序号为空但有学生姓名和课题，自动按顺序编号
            if name_str and topic_str:
                seq_val = len(students) + 1
            else:
                continue
        else:
            try:
                seq_val = int(float(seq_str))
            except ValueError:
                continue

        students.append({
            "row_idx": r_idx,
            "seq": seq_val,
            "category": get_col("课题类别") or get_col("门类"),
            "name": name_str,
            "student_id": get_col("学生学号") or get_col("学号"),
            "topic": topic_str,
            "advisor": advisor_str,
            "advisor_dept": get_col("导师院系") or get_col("导师学院") or get_col("学院"),
        })

    return students, headers, banner_text


def format_match_direction(student_topic, teacher, tokenize_fn=None):
    """
    生成清晰易读的【匹配方向】文本（不含“待专业相关性复核/是否人工核验”等字样）。
    例如：课题方向匹配（人工智能、图像视觉 | 共同词: 图像）
    """
    level = teacher.get("_match_level", "方向匹配")
    # 去掉低置信内部调试后缀中的“待复核”之类，仅保留清晰描述
    reason = teacher.get("_match_reason", "")
    parts = [p for p in reason.split("；") if p]

    domain_part = ""
    extra_parts = []
    for p in parts:
        if p.startswith("方向领域:"):
            domain_part = p.replace("方向领域:", "").strip()
        elif p == "导师同院系":
            extra_parts.append("导师同院系")

    shared_words = []
    if tokenize_fn and student_topic:
        q_tokens = set(tokenize_fn(student_topic))
        r_tokens = set(tokenize_fn(teacher.get("research_direction", "")))
        p_tokens = set(tokenize_fn(teacher.get("profile_text", "")))
        shared = sorted(q_tokens & (r_tokens | p_tokens), key=lambda w: (-len(w), w))
        shared_words = shared[:6]

    detail_items = []
    if domain_part:
        detail_items.append(f"领域:{domain_part}")
    if shared_words:
        detail_items.append(f"关键词:{'、'.join(shared_words)}")
    if extra_parts:
        detail_items.extend(extra_parts)

    if detail_items:
        return f"{level} ({'；'.join(detail_items)})"
    return level


def generate_horizontal_csv(students, results, pick_count=3, tokenize_fn=None):
    """
    生成横式 CSV 字节流（UTF-8 with BOM，Excel 双击直接打开不乱码）：
    每位学生占 1 行，列依次为：
    序号, 课题类别, 学生姓名, 学生学号, 课题中文, 导师姓名, 导师院系,
    评审1姓名, 评审1学院, 评审1职称, 评审1电话, 评审1邮箱, 评审1研究方向, 评审1匹配方向, 评审1相近程度,
    评审2姓名, ...
    （不包含是否人工核验部分）
    """
    buf = io.StringIO()
    writer = safe_csv_writer(buf)

    headers = list(STUDENT_BASE_COLS)
    max_k = max([pick_count] + [len(m) for m in results]) if results else pick_count
    for k in range(1, max_k + 1):
        headers.extend([
            f"评审{k}姓名",
            f"评审{k}学院",
            f"评审{k}职称",
            f"评审{k}电话",
            f"评审{k}邮箱",
            f"评审{k}研究方向",
            f"评审{k}匹配方向",
            f"评审{k}相近程度",
        ])
    writer.writerow(headers)

    for s, matches in zip(students, results):
        row = [
            s.get("seq", ""),
            s.get("category", ""),
            s.get("name", ""),
            clean_cell_str(s.get("student_id", "")),
            s.get("topic", ""),
            s.get("advisor", ""),
            s.get("advisor_dept", ""),
        ]
        for j in range(max_k):
            if j < len(matches):
                t, score = matches[j]
                match_dir = format_match_direction(s.get("topic", ""), t, tokenize_fn)
                row.extend([
                    t.get("name", ""),
                    t.get("department", "") or t.get("college", ""),
                    t.get("title", ""),
                    clean_cell_str(t.get("phone", "")),
                    t.get("email", ""),
                    t.get("research_direction", ""),
                    match_dir,
                    f"{float(score):.4f}",
                ])
            else:
                row.extend(["", "", "", "", "", "", "", ""])
        writer.writerow(row)

    return buf.getvalue().encode("utf-8-sig")


def build_xlsx_bytes(sheet_name, rows, merges=None, col_widths=None, row_heights=None, has_banner=False):
    """
    使用纯标准库构建带样式、边框、自动换行与合并单元格的标准 .xlsx 文件字节流。
    styles.xml 内置：
      style 0: 默认
      style 1: 任务说明横幅 (左对齐、垂直居中、自动换行、11pt 宋体/微软雅黑、浅底色、细边框)
      style 2: 表头样式 (居中、加粗、浅蓝灰底色 #D9E1F2、细边框、自动换行)
      style 3: 学生合并列样式 A-G (水平居中、垂直居中、自动换行、细边框)
      style 4: 评审信息列样式 H-L (水平居中、垂直居中、自动换行、细边框)
      style 5: 研究方向/长文本列样式 M+ (左对齐、垂直居中、自动换行、细边框)
    """
    merges = merges or []
    col_widths = col_widths or {}
    row_heights = row_heights or {}

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    wb_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">
  <sheets>
    <sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    wb_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="4">
    <font><sz val="11"/><name val="宋体"/></font>
    <font><b/><sz val="11"/><color rgb="FF1F2937"/><name val="微软雅黑"/></font>
    <font><sz val="10.5"/><color rgb="FF111827"/><name val="微软雅黑"/></font>
    <font><sz val="10.5"/><color rgb="FF1E3A8A"/><name val="微软雅黑"/></font>
  </fonts>
  <fills count="4">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFCBD5E1"/></left>
      <right style="thin"><color rgb="FFCBD5E1"/></right>
      <top style="thin"><color rgb="FFCBD5E1"/></top>
      <bottom style="thin"><color rgb="FFCBD5E1"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="6">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="3" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="left" vertical="center" wrapText="1"/>
    </xf>
    <xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center" wrapText="1"/>
    </xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center" wrapText="1"/>
    </xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center" wrapText="1"/>
    </xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="left" vertical="center" wrapText="1"/>
    </xf>
  </cellXfs>
</styleSheet>"""

    sheet_lines = [
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">',
    ]

    if col_widths:
        sheet_lines.append("  <cols>")
        for c_idx, width in sorted(col_widths.items()):
            col_num = c_idx + 1
            sheet_lines.append(f'    <col min="{col_num}" max="{col_num}" width="{width}" customWidth="1"/>')
        sheet_lines.append("  </cols>")

    sheet_lines.append("  <sheetData>")
    header_row_num = 2 if has_banner else 1

    for r_idx, row in enumerate(rows):
        r_num = r_idx + 1
        ht_attr = f' ht="{row_heights[r_num]}" customHeight="1"' if r_num in row_heights else ""
        sheet_lines.append(f'    <row r="{r_num}"{ht_attr}>')
        for c_idx, val in enumerate(row):
            cell_ref = f"{col_index_to_letter(c_idx)}{r_num}"
            # 決定样式
            if has_banner and r_num == 1:
                s_id = 1
            elif r_num == header_row_num:
                s_id = 2
            elif c_idx < 7:
                s_id = 3
            elif c_idx < 12:
                s_id = 4
            else:
                s_id = 5

            val_str = "" if val is None else str(val)
            if val_str == "":
                sheet_lines.append(f'      <c r="{cell_ref}" s="{s_id}"/>')
            elif c_idx == 0 and r_num > header_row_num and re.fullmatch(r"\d+", val_str):
                # 序号用数值型
                sheet_lines.append(f'      <c r="{cell_ref}" s="{s_id}"><v>{val_str}</v></c>')
            else:
                # 其余全部用 inlineStr，确保学号/电话/长文本原样保留且不依赖 sharedStrings
                escaped_text = escape(val_str)
                sheet_lines.append(
                    f'      <c r="{cell_ref}" s="{s_id}" t="inlineStr"><is><t xml:space="preserve">{escaped_text}</t></is></c>'
                )
        sheet_lines.append("    </row>")
    sheet_lines.append("  </sheetData>")

    if merges:
        sheet_lines.append(f'  <mergeCells count="{len(merges)}">')
        for m_ref in merges:
            sheet_lines.append(f'    <mergeCell ref="{m_ref}"/>')
        sheet_lines.append("  </mergeCells>")

    sheet_lines.append("</worksheet>")
    sheet_xml = "\n".join(sheet_lines)

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", wb_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return out_buf.getvalue()


def generate_merged_table_xlsx(students, results, pick_count=3, banner_text=None, include_match_meta=False, tokenize_fn=None):
    """
    导出原本 table 格式（带合并单元格的 .xlsx）：
    - 第 1 行：任务说明横幅（合并 A1:M1 或 A1:O1），若 banner_text 为 None 则使用默认横幅
    - 第 2 行：表头（序号、课题类别、学生姓名、学生学号、课题中文、导师姓名、导师院系、拟定评审、学院、职称、电话、邮箱、研究方向 [+ 匹配方向、相近程度]）
    - 第 3 行起：每位学生占 K 行（K = max(pick_count, len(matches))），学生的 A~G 列自动跨 K 行纵向合并（A3:A5, B3:B5 ... G3:G5），H~M 列逐行填入匹配的评审老师信息。
    """
    use_banner = True
    banner = DEFAULT_TASK_BANNER  # 输出始终保留可填写任务模板，不继承上传成品中的负责人和日期。

    cols = list(STUDENT_BASE_COLS) + list(REVIEWER_BASE_COLS)
    if include_match_meta:
        cols.extend(["匹配方向", "相近程度"])

    total_cols = len(cols)
    last_col_letter = col_index_to_letter(total_cols - 1)

    rows = []
    merges = []
    row_heights = {}

    if use_banner:
        banner_row = [banner] + [""] * (total_cols - 1)
        rows.append(banner_row)
        merges.append(f"A1:{last_col_letter}1")
        row_heights[1] = 270
        row_heights[2] = 36
        current_excel_row = 3
    else:
        row_heights[1] = 36
        current_excel_row = 2

    rows.append(cols)

    for s, matches in zip(students, results):
        k = max(pick_count, len(matches), 1)
        start_r = current_excel_row
        end_r = current_excel_row + k - 1

        for j in range(k):
            r_num = current_excel_row + j
            row_heights[r_num] = 28
            if j == 0:
                stu_part = [
                    str(s.get("seq", "")),
                    s.get("category", ""),
                    s.get("name", ""),
                    clean_cell_str(s.get("student_id", "")),
                    s.get("topic", ""),
                    s.get("advisor", ""),
                    s.get("advisor_dept", ""),
                ]
            else:
                stu_part = ["", "", "", "", "", "", ""]

            if j < len(matches):
                t, score = matches[j]
                rev_part = [
                    t.get("name", ""),
                    t.get("department", "") or t.get("college", ""),
                    t.get("title", ""),
                    clean_cell_str(t.get("phone", "")),
                    t.get("email", ""),
                    t.get("research_direction", ""),
                ]
                if include_match_meta:
                    rev_part.extend([
                        format_match_direction(s.get("topic", ""), t, tokenize_fn),
                        f"{float(score):.4f}",
                    ])
            else:
                rev_part = [""] * (len(REVIEWER_BASE_COLS) + (2 if include_match_meta else 0))

            rows.append(stu_part + rev_part)

        # 为该学生的 A~G 列（索引 0~6）创建纵向合并单元格
        if k > 1:
            for c_idx in range(7):
                col_let = col_index_to_letter(c_idx)
                merges.append(f"{col_let}{start_r}:{col_let}{end_r}")

        current_excel_row += k

    col_widths = {
        0: 7,    # 序号
        1: 16,   # 课题类别
        2: 12,   # 学生姓名
        3: 16,   # 学生学号
        4: 48,   # 课题中文
        5: 12,   # 导师姓名
        6: 24,   # 导师院系
        7: 14,   # 拟定评审
        8: 24,   # 学院
        9: 18,   # 职称
        10: 16,  # 电话
        11: 28,  # 邮箱
        12: 60,  # 研究方向
        13: 36,  # 匹配方向
        14: 12,  # 相近程度
    }

    return build_xlsx_bytes(
        sheet_name="立项答辩",
        rows=rows,
        merges=merges,
        col_widths=col_widths,
        row_heights=row_heights,
        has_banner=use_banner,
    )


def generate_blank_template_xlsx(template_type="student"):
    """
    生成空白单行对齐上传模板 (.xlsx)：
    单横行表头 + 示例空白对齐格式（不含合并单元格和冗长横幅，与 CSV 格式几乎完全一致）
    template_type:
      - "student": 学生课题上传空白模板（序号, 课题类别, 学生姓名, 学生学号, 课题中文, 导师姓名, 导师院系）
      - "teacher": 教师增量合并空白模板（姓名, 职称, 院系, 邮箱, 电话, 手机, 研究方向, 个人主页）
    """
    if template_type == "teacher":
        headers = ["姓名", "职称", "院系", "邮箱", "电话", "手机", "研究方向", "个人主页"]
        widths = {0: 14, 1: 16, 2: 26, 3: 28, 4: 16, 5: 16, 6: 50, 7: 36}
        sheet_title = "教师增量导入模板"
    else:
        headers = list(STUDENT_BASE_COLS)
        widths = {0: 8, 1: 18, 2: 14, 3: 18, 4: 50, 5: 14, 6: 26}
        sheet_title = "学生课题上传模板"

    rows = [headers]
    return build_xlsx_bytes(
        sheet_name=sheet_title,
        rows=rows,
        merges=[],
        col_widths=widths,
        row_heights={1: 30},
        has_banner=False,
    )


def generate_blank_template_csv(template_type="student"):
    """生成空白单行对齐上传模板 (.csv)"""
    buf = io.StringIO()
    writer = safe_csv_writer(buf)
    if template_type == "teacher":
        writer.writerow(["姓名", "职称", "院系", "邮箱", "电话", "手机", "研究方向", "个人主页"])
    else:
        writer.writerow(STUDENT_BASE_COLS)
    return buf.getvalue().encode("utf-8-sig")

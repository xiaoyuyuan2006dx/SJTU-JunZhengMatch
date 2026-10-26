#!/usr/bin/env python3
"""按学生课题匹配评审：中文2—4字TF-IDF，研究方向优先，先相关性后复用。
python sjtu_match_reviewers.py sample.xlsx --dry-run
python sjtu_match_reviewers.py sample.xlsx --strategy weighted --seed 42 --pick 5
默认自动补齐评审，扩展领域和导师方向参与排序；--strict 恢复仅阈值匹配。
低置信补位在输出中明确标记。
"""
import sys
import sqlite3
from contextlib import closing
import re
import time
import random
from pathlib import Path

import argparse
import math
import unicodedata
from collections import Counter

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False

import sjtu_excel_io as xio

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "sjtu_faculty_data" / "sjtu_faculty_data.db"

# 先移除完整的非正高职称，再检查剩余职称，避免“副教授、研究员”漏排。
JUNIOR_RE = re.compile(
    r"副主任医师|副研究馆员|副教授|副研究员|助理教授|助理研究员|"
    r"讲师|高级工程师|高级实验师|工程师|实验师|实验员|助教|博士后|研究助理|"
    r"(?:associate|assistant)\s+(?:professor|research(?:er|\s+professor))", re.I)
SENIOR_RE = re.compile(r"教授|研究员|主任医师|研究馆员|首席|讲席|professor|research professor", re.I)
STOPWORDS = {"研究", "基于", "通过", "以及", "进行", "相关", "目前", "主要", "从事",
             "方向", "课题", "学生", "导师", "上海", "交通", "大学", "学院", "教授",
             "技术", "方法", "应用", "设计", "发展", "工作", "领域", "具有", "包括",
             "作用", "机制", "构建", "新型", "高效", "调控", "模型", "结构",
             "分析", "功能", "特性", "过程", "开发", "科学", "计算", "智能", "系统"}


def _is_na(value):
    if value is None:
        return True
    if HAS_PANDAS and not isinstance(value, str):
        try:
            if pd.isna(value):
                return True
        except Exception:
            pass
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def clean_text(value):
    if _is_na(value):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def normalize_name(value):
    return re.sub(r"\s+", "", clean_text(value)).casefold()


def is_senior_title(title):
    return bool(SENIOR_RE.search(JUNIOR_RE.sub("", clean_text(title))))


def tokenize(text):
    """中文连续2—4字片段 + 英文词；不依赖可选分词包，避免按单字误匹配。"""
    tokens = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+(?:[-+][a-z0-9]+)*", clean_text(text).lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            for n in (2, 3, 4):
                tokens.extend(part[i:i+n] for i in range(len(part)-n+1)
                              if part[i:i+n] not in STOPWORDS
                              and not all(part[i+j:i+j+2] in STOPWORDS for j in range(0, n, 2)))
        elif len(part) > 1 and not part.isdigit():
            tokens.append(part)
    return tokens


def load_teachers():
    """以只读方式打开数据库，防止路径错误时创建空库。"""
    with closing(sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        rows = conn.execute("""
            SELECT teacher_id, name, title, COALESCE(NULLIF(department,''), college),
                   college, email, phone, mobile, research_direction, profile_text
            FROM faculty ORDER BY teacher_id
        """).fetchall()
    teachers = []
    for tid, name, title, dept, college, email, phone, mobile, rd, profile in rows:
        teachers.append(dict(teacher_id=tid, name=clean_text(name), title=clean_text(title),
                             department=clean_text(dept), college=clean_text(college),
                             email=clean_text(email), phone=clean_text(phone) or clean_text(mobile),
                             research_direction=clean_text(rd), profile_text=clean_text(profile),
                             is_senior=is_senior_title(title)))
    return teachers


def build_engine(teachers):
    """缓存稀疏TF-IDF向量。方向和简介分别归一化，避免长简历稀释专业方向。"""
    documents = [(Counter(tokenize(t['research_direction'])),
                  Counter(tokenize(t.get('profile_text', '')))) for t in teachers]
    frequencies = Counter()
    for research, profile in documents:
        frequencies.update(set(research) | set(profile))
    idf = {word: math.log((1 + len(teachers)) / (1 + count)) + 1
           for word, count in frequencies.items()}

    def vectorize(counts):
        vector = {word: (1 + math.log(count)) * idf[word] * (len(word) / 2 if re.fullmatch(r"[\u4e00-\u9fff]+", word) else 1)
                  for word, count in counts.items() if word in idf}
        norm = math.sqrt(sum(v*v for v in vector.values()))
        return {word: v / norm for word, v in vector.items()} if norm else {}

    return dict(vectorize=vectorize,
                vectors=[(vectorize(r), vectorize(p)) for r, p in documents])


def advisor_names(value):
    return {normalize_name(n) for n in re.split(r"[,，、;；/|\n]+", clean_text(value)) if n.strip()}


def find_matches(query_text, teachers, engine, advisor_name, used_names,
                 pool_size=20, pick_count=3, min_score=0.05, relative_score=0.4,
                 strategy="top", rng=None, allow_unknown_title=False):
    """先确定有相关性的全局候选池，再优先新人；不足时允许复用，不用零分补位。"""
    if pick_count < 1 or pool_size < pick_count:
        raise ValueError("必须满足 pool_size >= pick_count >= 1")
    query = engine['vectorize'](Counter(tokenize(query_text)))
    if not query:
        return [], []
    excluded = advisor_names(advisor_name)
    # 同名记录中如有明确正高，保守回避全部同名记录。
    excluded.update(normalize_name(t['name']) for t in teachers if t['is_senior'])
    used = {normalize_name(n) for n in used_names}
    ranked = []
    for teacher, (research, profile) in zip(teachers, engine['vectors']):
        name = normalize_name(teacher['name'])
        if not name or name in excluded or teacher['is_senior']:
            continue
        if not allow_unknown_title and not JUNIOR_RE.search(teacher['title']):
            continue
        r = sum(v * research.get(w, 0) for w, v in query.items())
        p = sum(v * profile.get(w, 0) for w, v in query.items())
        score = 0.8*r + 0.2*p if research else p
        if score > 0 and score >= min_score:
            ranked.append((teacher, score))
    ranked.sort(key=lambda item: (-item[1], normalize_name(item[0]['name']), str(item[0]['teacher_id'])))
    if not ranked:
        return [], []
    # 同名记录保守合并，避免一个学生选到同一姓名的多个记录。
    pool, seen = [], set()
    cutoff = ranked[0][1] * relative_score
    for teacher, score in ranked:
        name = normalize_name(teacher['name'])
        if score < cutoff:
            break
        if name not in seen:
            seen.add(name)
            pool.append((teacher, score))
        if len(pool) >= pool_size:
            break
    fresh = [pair for pair in pool if normalize_name(pair[0]['name']) not in used]
    reused = [pair for pair in pool if normalize_name(pair[0]['name']) in used]
    selected = []
    for group in (fresh, reused):
        k = min(pick_count - len(selected), len(group))
        if strategy == "weighted":
            indices = weighted_sample_without_replacement(len(group), k, [s for _, s in group], rng)
            selected.extend(group[i] for i in indices)
        else:
            selected.extend(group[:k])
    selected.sort(key=lambda item: -item[1])
    reused_names = [t['name'] for t, _ in selected if normalize_name(t['name']) in used]
    return [(t, round(float(score), 6)) for t, score in selected], reused_names


# 可审查的学科同义词规则；只做词义扩展，不调用在线模型。
CONCEPTS = {
    "图像视觉": r"图像|视觉|成像|图像编辑|image|vision",
    "人工智能": r"人工智能|机器学习|深度学习|神经网络|大模型|强化学习|智能体|图像编辑|扩散模型",
    "情感心理": r"情感|情绪|心理|精神分裂|共情|认知|抑郁",
    "光电光子": r"光学|光子|光放大|激光|光谱|光电|拉曼|光纤|非厄米|超表面",
    "自动控制": r"控制|导航|归航|运动规划|路径规划|协同|伺服|自主系统",
    "机器人": r"机器人|机械臂|四足|具身|人机协作|无人驾驶",
    "航空飞行": r"飞行|翼伞|航空|无人机|航天|飞行器",
    "数据库系统": r"数据库|存内计算|数据管理|数据存储|数据索引|检索|分布式系统|体系结构|存储系统",
    "生物材料": r"生物材料|生物弹性体|组织工程|再生医学|水凝胶|生物医用|医用材料",
    "药物递送": r"载药|给药|药物递送|纳米药物|纳米医学|药物输送",
    "心血管": r"心血管|主动脉|动脉瘤|心肌|心脏|血管|冠心病",
    "感染免疫": r"感染|病原|抗菌|细菌|免疫|铁死亡|铜绿假单胞菌|炎症",
    "有机合成": r"有机合成|全合成|不对称|手性|合成化学|天然产物|合成方法|药物合成|四环素|有机催化",
    "植物科学": r"植物|作物|育种|果树|植物胁迫|植物逆境|植物抗逆",
    "核酸分子": r"核酸|rna|dna|基因|转录|分子生物|蛋白|组学",
    "脑与神经": r"神经|脑|自闭症|癫痫|帕金森|精神分裂|认知障碍",
    "医学影像": r"医学影像|医用影像|磁共振|超声|医学图像|医疗成像|影像诊断",
    "微生物": r"微生物|细菌|真菌|菌群|细菌生物膜|抗生素|达托霉素|黑水虻|铜绿假单胞菌",
    "代谢药理": r"代谢|药理|受体|拮抗剂|糖尿病|高糖|细胞信号|信号转导",
    "骨科力学": r"骨科|种植|骨质|疏松骨|骨组织|生物力学|植介入|牙|口腔|离体动物骨",
    "法律": r"法律|(?<!方)法学|法治|国际法|竞争法|规制|海洋法|海商法|司法|民法|公法",
    "竞争规制": r"竞争|反垄断|规制|知识产权|数字平台|数据法",
    "国际海洋法": r"国际法|海洋法|海商法|深海|采矿|国际公法|国际经济法",
    "语言学": r"自然语言|语言学|语言教育|语言习得|汉语|语法|语料|语义|语用|疑问代词|修辞|词汇",
    "语音听觉": r"语音|听觉|语音识别|语音感知|言语|speech",
    "医疗机器人": r"医疗机器人|手术机器人|医疗微纳机器人|手术导航|智能医疗|微创|超声查扫|植入",
    "电池能源": r"电池|磷酸铁锂|储能|电化学|电解|电极|锂离子",
    "资源环境": r"回收|资源化|废旧|废固|降解|污染|环境修复|固废|废水",
    "高分子流变": r"流变|凝胶|多糖|软物质|高分子|聚合物|关节液",
    "流体流变": r"流体|流变|凝胶|多糖|非牛顿|软物质|高分子|聚合物|关节液",
}


def concept_features(text):
    text = clean_text(text).lower()
    # 避免把人工神经网络、神经形态芯片直接等同于医学神经科学。
    brain_text = re.sub(r"神经(?:网络|模态|形态|计算)|类脑计算", "", text)
    features = {name for name, pattern in CONCEPTS.items() if re.search(pattern, text)}
    if not re.search(CONCEPTS['脑与神经'], brain_text):
        features.discard('脑与神经')
    return features


def normalized_department(text):
    text = clean_text(text).replace("上海交通大学", "").replace(" ", "").lower()
    for old, new in [("外国语", "外语"), ("化学系", "化学化工学院"),
                     ("自动化系", "自动化与感知学院")]:
        text = text.replace(old, new)
    return text


def find_complete_matches(student, teachers, engine, usage_counts=None, pool_size=20,
                          pick_count=3, strategy="top", rng=None, allow_unknown_title=False,
                          min_score=0.05):
    """完整分配：课题文字+领域扩展+导师方向+院系补充，硬约束始终保留。

    按相关性排序，使用次数仅在近分候选间轻微调整；不同学生可复用教师。
    无课题/领域证据时也可补位，但必须明确标为低置信，不能伪装成直接相关。
    """
    if pick_count < 1 or pool_size < pick_count:
        raise ValueError("必须满足 pool_size >= pick_count >= 1")
    usage_counts = usage_counts or {}
    excluded = advisor_names(student.get('advisor', ''))
    excluded.update(normalize_name(t['name']) for t in teachers if t['is_senior'])
    query = engine['vectorize'](Counter(tokenize(student.get('topic', ''))))
    concepts = concept_features(student.get('topic', ''))
    advisor_text = " ".join(t['research_direction'] for t in teachers
                            if normalize_name(t['name']) in advisor_names(student.get('advisor', '')))
    advisor_vector = engine['vectorize'](Counter(tokenize(advisor_text)))
    department = normalized_department(student.get('advisor_dept', ''))
    ranked = []
    for teacher, (research, profile) in zip(teachers, engine['vectors']):
        name = normalize_name(teacher['name'])
        if not name or name in excluded or teacher['is_senior']:
            continue
        if not allow_unknown_title and not JUNIOR_RE.search(teacher['title']):
            continue
        lexical = sum(v * research.get(w, 0) for w, v in query.items())
        profile_score = sum(v * profile.get(w, 0) for w, v in query.items())
        lexical = .85 * lexical + .15 * profile_score if research else profile_score
        research_concepts = concept_features(teacher['research_direction'])
        profile_concepts = concept_features(teacher.get('profile_text', ''))
        shared = concepts & research_concepts
        profile_shared = (concepts & profile_concepts) - shared
        # 方向中的领域词优先，履历中的领域词仅提供很小的补充权重。
        weights = {'资源环境': .5, '人工智能': .6, '图像视觉': .8,
                   '脑与神经': 1.5, '微生物': 1.5, '心血管': 1.5,
                   '有机合成': 1.5, '法律': 1.5, '高分子流变': 1.5}
        total_weight = sum(weights.get(c, 1) for c in concepts)
        coverage = (sum(weights.get(c, 1) for c in shared) +
                    .1 * sum(weights.get(c, 1) for c in profile_shared)) / max(1, total_weight)
        advisor_score = sum(v * research.get(w, 0) for w, v in advisor_vector.items())
        same_dept = bool(department and department in {
            normalized_department(teacher['department']), normalized_department(teacher['college'])})
        score = .65 * lexical + .3 * coverage + .04 * advisor_score + .01 * same_dept
        # 管理/软件使用列表不应凭一个专业词超过专门研究该领域的人。
        practice_only = bool(re.search(r"高教管理|行政管理", teacher['title']) or
                             re.search(r"软件[:：].*(?:photoshop|html|asp\.net)", teacher['research_direction'], re.I))
        if practice_only:
            score *= .25
        reasons = []
        if shared:
            reasons.append("方向领域:" + "、".join(sorted(shared)))
        if lexical > 0:
            reasons.append(f"课题文本:{lexical:.4f}")
        if advisor_score > 0:
            reasons.append(f"导师方向:{advisor_score:.4f}")
        if same_dept:
            reasons.append("导师同院系")
        if shared and coverage >= .66:
            level, tier = "课题方向匹配", 0
        elif shared or (not concepts and lexical >= min_score):
            level, tier = "相近方向匹配", 1
        elif lexical > 0 or profile_shared or advisor_score > 0 or same_dept:
            level, tier = "扩展补位·低置信", 2
        else:
            level, tier = "全库补位·低置信", 3
        if practice_only:
            tier = max(tier, 2)
            level = "扩展补位·低置信"
            reasons.append("管理/软件使用记录，降低优先级")
        enriched = dict(teacher, _match_level=level, _match_reason="；".join(reasons) or "库中相关证据不足，按可用教师补位",
                        _topic_score=round(lexical, 6))
        load = usage_counts.get(name, 0)
        # 不允许“不重复”的偏好把明显更相关的教师排到后面。
        rank_score = score - min(load, 10) * .001
        ranked.append((enriched, score, tier, rank_score))
    ranked.sort(key=lambda item: (item[2], -item[3], normalize_name(item[0]['name']), str(item[0]['teacher_id'])))
    pool, seen = [], set()
    for teacher, score, tier, _ in ranked:
        key = normalize_name(teacher['name'])
        if key not in seen:
            seen.add(key)
            pool.append((teacher, score, tier))
        if len(pool) >= pool_size:
            break
    chosen = []
    for tier in range(4):
        group = [pair for pair in pool if pair[2] == tier]
        k = min(pick_count - len(chosen), len(group))
        if strategy == 'weighted':
            indices = weighted_sample_without_replacement(len(group), k, [max(s, 1e-9) for _, s, _ in group], rng)
            chosen.extend(group[i] for i in indices)
        else:
            chosen.extend(group[:k])
    reused = [t['name'] for t, _, _ in chosen if usage_counts.get(normalize_name(t['name']), 0)]
    return [(t, round(score, 6)) for t, score, _ in chosen], reused


def weighted_sample_without_replacement(n, k, weights, rng=None):
    """指数竞赛：-log(U)/weight 越小越先选；零权重永不入选。"""
    if n != len(weights) or not 0 <= k <= n:
        raise ValueError("无效的采样大小")
    rng = rng or random
    keys = []
    for i, weight in enumerate(weights):
        if not math.isfinite(float(weight)) or weight < 0:
            raise ValueError("权重必须为有限非负数")
        if weight > 0:
            keys.append((-math.log(max(rng.random(), 1e-15)) / weight, i))
    keys.sort()
    return [i for _, i in keys[:k]]


def read_students(filepath):
    """读取学生 Excel/CSV，返回 students list, df, header_row（无 pandas 时自动使用标准库引擎）"""
    if HAS_PANDAS:
        try:
            raw = pd.read_excel(filepath, header=None)
            header_row = 0
            for i, row in raw.iterrows():
                text = " ".join(str(v) for v in row if pd.notna(v))
                if "序号" in text or "学生姓名" in text:
                    header_row = i
                    break

            df = pd.read_excel(filepath, header=header_row)
            df.columns = [str(c).strip() for c in df.columns]

            required = {"序号", "学生姓名", "导师姓名"}
            if not required.issubset(df.columns) or not ({"课题中文", "课题"} & set(df.columns)):
                raise ValueError("缺少必要列：序号、学生姓名、导师姓名，以及课题中文或课题")
            students = []
            for idx, row in df.iterrows():
                seq = row.get("序号")
                if pd.isna(seq) or str(seq).strip() == "":
                    continue
                try:
                    int(float(seq))
                except (ValueError, TypeError):
                    continue
                students.append({
                    "row_idx": idx,
                    "seq": int(float(seq)),
                    "name": clean_text(row.get("学生姓名", "")),
                    "student_id": xio.clean_cell_str(row.get("学生学号", "")),
                    "topic": clean_text(row.get("课题中文", "")) or clean_text(row.get("课题", "")),
                    "advisor": clean_text(row.get("导师姓名", "")),
                    "advisor_dept": clean_text(row.get("导师院系", "")),
                    "category": clean_text(row.get("课题类别", "")),
                })
            return students, df, header_row
        except ImportError:
            pass

    with open(filepath, "rb") as f:
        rows = xio.read_tabular_rows(f.read(), str(filepath))
    students, headers, banner = xio.parse_students_from_rows(rows)
    return students, {"rows": rows, "headers": headers, "banner": banner}, 0


def write_output(filepath, df, students, results, pick_count=3, output=None, csv_output=None):
    """按 --pick 输出学生与评审（支持原表合并单元格格式 .xlsx 与横式 .csv）。"""
    out_path = str(output or (str(Path(filepath).with_suffix("")) + "_matched.xlsx"))
    if Path(out_path).resolve() == Path(filepath).resolve():
        raise ValueError("输出路径不能覆盖输入文件")

    student_cols = ["序号", "课题类别", "学生姓名", "学生学号", "课题中文", "导师姓名", "导师院系"]
    reviewer_cols = ["拟定评审", "学院", "职称", "电话", "邮箱", "研究方向", "综合推荐分", "课题文本分", "匹配层级", "匹配依据", "匹配状态"]

    if HAS_PANDAS and hasattr(df, "columns"):
        rows = []
        used_names = set()
        for student, matches in zip(students, results):
            base = {c: df.at[student["row_idx"], c] if c in df.columns else "" for c in student_cols}
            for j in range(max(pick_count, len(matches))):
                row = {}
                if j == 0:
                    row.update(base)
                if j < len(matches):
                    t, score = matches[j]
                    row["拟定评审"] = t["name"]
                    row["学院"] = t["department"]
                    row["职称"] = t["title"]
                    row["电话"] = t["phone"]
                    row["邮箱"] = t["email"]
                    row["研究方向"] = t["research_direction"]
                    row["综合推荐分"] = score
                    row["课题文本分"] = t.get("_topic_score", score)
                    row["匹配层级"] = t.get("_match_level", "严格匹配")
                    query_tokens = set(tokenize(student['topic']))
                    research_tokens = set(tokenize(t['research_direction']))
                    profile_tokens = set(tokenize(t.get('profile_text', '')))
                    shared = query_tokens & (research_tokens | profile_tokens)
                    evidence = sorted(shared, key=lambda w: (-len(w), w))
                    row["匹配依据"] = t.get("_match_reason", "") + ("；共同片段:" if evidence else "") + "、".join(evidence[:12])
                    key = normalize_name(t["name"])
                    row["匹配状态"] = ("复用" if key in used_names else "新匹配") + "；待专业相关性复核"
                    if not JUNIOR_RE.search(t["title"]):
                        row["匹配状态"] += "；职称待核实"
                    used_names.add(key)
                else:
                    row["匹配状态"] = "相关候选不足，待人工确认"
                rows.append(row)

        out_cols = student_cols + reviewer_cols
        out_df = pd.DataFrame(rows, columns=out_cols)
        for c in ["学生学号", "电话"]:
            if c in out_df.columns:
                out_df[c] = out_df[c].apply(
                    lambda x: (str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else str(x).strip()) if pd.notna(x) else ""
                )
        try:
            out_df.to_excel(out_path, index=False, sheet_name="匹配结果")
            print(f"\n📁 结果: {out_path}")
            return out_path
        except ImportError:
            pass

    banner = df.get("banner", "") if isinstance(df, dict) else ""
    xlsx_bytes = xio.generate_merged_table_xlsx(
        students, results, pick_count=pick_count, banner_text=banner, tokenize_fn=tokenize
    )
    Path(out_path).write_bytes(xlsx_bytes)
    print(f"\n📁 结果 (合并单元格原表格式): {out_path}")
    if csv_output:
        csv_bytes = xio.generate_horizontal_csv(students, results, pick_count=pick_count, tokenize_fn=tokenize)
        Path(csv_output).write_bytes(csv_bytes)
        print(f"📁 结果 (横式 CSV 格式): {csv_output}")
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(description="按研究方向匹配评审教师")
    parser.add_argument("file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--range", dest="student_range")
    group.add_argument("--student", type=int)
    group.add_argument("--name")
    parser.add_argument("--pool", type=int, default=20)
    parser.add_argument("--pick", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=0.05)
    parser.add_argument("--relative-score", type=float, default=0.4)
    parser.add_argument("--strategy", choices=["top", "weighted"], default="top")
    parser.add_argument("--allow-unknown-title", action="store_true", help="允许职称不明的候选，需人工核实")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", help="另存匹配结果，避免覆盖旧结果")
    parser.add_argument("--strict", action="store_true", help="仅返回过阈值候选，不补齐；默认自动补齐")
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args()
    if ns.pick < 1 or ns.pool < ns.pick:
        parser.error("必须满足 --pool >= --pick >= 1")
    if not 0 <= ns.min_score <= 1 or not 0 <= ns.relative_score <= 1:
        parser.error("相关性阈值必须在0到1之间")
    args = dict(file=ns.file, mode="all", start=None, end=None,
                student_seq=ns.student, student_name=ns.name, dry_run=ns.dry_run,
                pool_size=ns.pool, pick_count=ns.pick, min_score=ns.min_score,
                relative_score=ns.relative_score, strategy=ns.strategy,
                seed=ns.seed, output=ns.output, allow_unknown_title=ns.allow_unknown_title, strict=ns.strict)
    if ns.student_range:
        try:
            parts = ns.student_range.split("-")
            if len(parts) > 2:
                raise ValueError()
            args["start"], args["end"] = int(parts[0]), int(parts[-1])
            if not 1 <= args["start"] <= args["end"]:
                raise ValueError()
        except ValueError:
            parser.error("--range 应为正整数范围，例如 1-10")
        args["mode"] = "range"
    elif ns.student is not None:
        args["mode"] = "student"
    elif ns.name is not None:
        args["mode"] = "name"
    return args


def filter_students(students, args):
    """根据参数筛选学生"""
    if args["mode"] == "range":
        return [s for s in students if args["start"] <= s["seq"] <= args["end"]]
    elif args["mode"] == "student":
        return [s for s in students if s["seq"] == args["student_seq"]]
    elif args["mode"] == "name":
        return [s for s in students if args["student_name"] in s["name"]]
    return students


def main():
    args = parse_args()
    if not args["file"]:
        print("Usage: python match_reviewers.py <excel> [--range 1-10] [--student 3]")
        print("       [--name 张三] [--pool 20] [--pick 3] [--dry-run]")
        print("  --pool N  : 候选池大小 (默认20, 从得分最高的N人中选)")
        print("  --pick K  : 从候选池选几人 (默认3)")
        sys.exit(1)

    if not Path(args["file"]).exists():
        print(f"❌ 文件不存在: {args['file']}")
        sys.exit(1)

    pool_size = args["pool_size"]
    pick_count = args["pick_count"]

    # 1. 加载
    print("📚 加载教师库...")
    teachers = load_teachers()
    candidates = [t for t in teachers if not t["is_senior"] and
                  (args["allow_unknown_title"] or JUNIOR_RE.search(t["title"]))]
    print(f"   教师总数: {len(teachers)}, 可用(职称初筛): {len(candidates)}")

    # 2. 引擎
    print("🔧 构建 TF-IDF 引擎...")
    engine = build_engine(teachers)

    # 3. 学生
    print(f"📖 读取: {args['file']}")
    students, df, header_row = read_students(args["file"])
    students = filter_students(students, args)
    total_students = len(students)
    print(f"   待匹配: {total_students} 人")

    # 4. 匹配
    mode_label = {"all": "全部", "range": f"序号 {args['start']}-{args['end']}",
                  "student": f"序号 {args['student_seq']}", "name": f"姓名含'{args['student_name']}'"}
    print(f"🔍 模式: {mode_label.get(args['mode'], args['mode'])}")
    print("   分配模式: " + ("严格阈值" if args["strict"] else "自动补齐，按课题、扩展领域与导师方向排序"))
    print(f"   候选池: Top {pool_size} → {args['strategy']} 选 {pick_count} 人，直接匹配参考阈值 {args['min_score']}\n")

    results = []
    start_time = time.time()
    used_names = set()  # 已被匹配过的教师姓名
    rng = random.Random(args["seed"])
    usage_counts = Counter()

    for i, s in enumerate(students):
        query = s["topic"]  # 类别通常很宽泛，不作为研究方向证据
        if args['strict']:
            matches, reused = find_matches(query, teachers, engine, s["advisor"],
                                           used_names, pool_size=pool_size,
                                           pick_count=pick_count,
                                           min_score=args['min_score'], relative_score=args['relative_score'],
                                           strategy=args['strategy'], rng=rng,
                                           allow_unknown_title=args['allow_unknown_title'])
        else:
            matches, reused = find_complete_matches(s, teachers, engine, usage_counts,
                pool_size=pool_size, pick_count=pick_count, strategy=args['strategy'], rng=rng,
                allow_unknown_title=args['allow_unknown_title'], min_score=args['min_score'])
        results.append(matches)

        # 标记已用
        for t, _ in matches:
            used_names.add(t["name"])
            usage_counts[normalize_name(t["name"])] += 1

        # 动态 ETA
        elapsed = time.time() - start_time
        speed = (i + 1) / elapsed if elapsed > 0 else 0
        remaining = total_students - (i + 1)
        eta_sec = remaining / speed if speed > 0 else 0
        eta_str = f"{int(eta_sec)}s" if eta_sec < 60 else f"{int(eta_sec/60)}m{int(eta_sec%60)}s"

        print(f"  [{s['seq']}] {s['name']} | {s['topic'][:50]}")
        print(f"      指导: {s['advisor']} ({s['advisor_dept']})")
        for j, (t, score) in enumerate(matches):
            rd_short = t["research_direction"][:50] if t["research_direction"] else "(无)"
            tag = (" 复用" if t["name"] in reused else "") + " " + t.get("_match_level", "严格匹配")
            print(f"      评审{j+1}: {t['name']} | {t['title']} | {t['department']} | "
                  f"{score:.4f}{tag} | {rd_short}")
        if reused:
            print(f"      信息: 以下教师在其他学生中也被选用: {', '.join(reused)}")
        if len(matches) < pick_count:
            print(f"      ⚠ 相关候选不足，仅匹配 {len(matches)}/{pick_count}，需人工确认")
        if (i + 1) % 5 == 0 or (i + 1) == total_students:
            print(f"      --- 进度:{i+1}/{total_students} 速度:{speed:.1f}人/s 已用:{len(used_names)}人 预计剩余:{eta_str} ---")
        print()

    total_elapsed = time.time() - start_time
    print(f"⏱ 匹配总耗时: {total_elapsed:.1f}s")

    # 5. 输出
    if not args["dry_run"]:
        write_output(args["file"], df, students, results, pick_count, args["output"])
    else:
        print("🔍 --dry-run 模式，未写入文件")

    matched_any = sum(1 for r in results if r)
    matched_k = sum(1 for r in results if len(r) >= pick_count)
    print(f"📊 {total_students} 人: ≥1匹配 {matched_any}, 满{pick_count} {matched_k}")


if __name__ == "__main__":
    main()

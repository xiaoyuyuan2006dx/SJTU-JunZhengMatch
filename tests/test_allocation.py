import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
from bootstrap import TEMPORARY
from collections import Counter
import io
import unittest
from unittest.mock import patch
from junzheng_match import sjtu_match_reviewers as matcher,sjtu_excel_io as xio,web_server as web


def teachers():
    return [dict(teacher_id=i,name='评审'+name,title='副教授',department='计算机学院',college='计算机学院',email='',phone='',research_direction='图像识别与计算机视觉',profile_text='',is_senior=False) for i,name in enumerate('甲乙丙',1)]


class AllocationLimitTests(unittest.TestCase):
    def run_task(self,strict=False,limit=2,strategy='top'):
        students=[dict(s,topic='图像识别与计算机视觉') for s in xio.fictional_students()[:3]]
        book=xio.generate_merged_table_xlsx(students,[[]]*3)
        with patch.object(matcher,'load_teachers',return_value=teachers()):
            return web.run_match_pipeline(book,'test.xlsx',dict(max_teacher_uses=limit,strict=strict,strategy=strategy,min_score=0,relative_score=0))
    def test_default_cap_two_leaves_last_student_blank(self):
        result=self.run_task();counts=Counter(r['name'] for s in result['items'] for r in s['reviewers'])
        self.assertEqual(set(counts.values()),{2});self.assertEqual(result['matched_full'],2)
        self.assertEqual(result['items'][2]['reviewers'],[]);self.assertIn('次数上限',result['items'][2]['unfilled_reason'])
    def test_strict_mode_respects_same_cap(self):
        result=self.run_task(strict=True);self.assertEqual(result['matched_full'],2)
    def test_weighted_mode_respects_same_cap(self):
        result=self.run_task(strategy='weighted');self.assertEqual(result['matched_full'],2)
    def test_user_can_set_three(self):self.assertEqual(self.run_task(limit=3)['matched_full'],3)
    def test_one_means_no_cross_student_reuse(self):self.assertEqual(self.run_task(limit=1)['matched_full'],1)
    def test_repeated_task_has_independent_counts(self):self.assertEqual(self.run_task()['matched_full'],self.run_task()['matched_full'])
    def test_normalized_names_share_cap(self):
        sample=teachers();sample.append(dict(sample[0],teacher_id=99,name='评审 甲'))
        engine=matcher.build_engine(sample)
        result,_=matcher.find_complete_matches(dict(topic='图像识别',advisor='外部导师',advisor_dept=''),sample,engine,{'评审甲':2},pick_count=3)
        self.assertNotIn('评审甲',{matcher.normalize_name(t['name']) for t,_ in result})
    def test_invalid_limits_rejected(self):
        for value in (0,-1,1.5,True,10001):
            with self.subTest(value=value),self.assertRaises(ValueError):self.run_task(limit=value)
    def test_exports_keep_original_schema_with_shortage(self):
        self.run_task();cache=web.LAST_MATCH_SESSION
        import csv
        records=list(csv.reader(io.StringIO(xio.generate_horizontal_csv(cache['students'],cache['results']).decode('utf-8-sig'))))
        self.assertEqual(len(records),4);self.assertEqual(len(records[0]),31)
        merged=xio.generate_merged_table_xlsx(cache['students'],cache['results'])
        self.assertEqual(xio.read_xlsx_rows(io.BytesIO(merged))[0][0],xio.DEFAULT_TASK_BANNER)

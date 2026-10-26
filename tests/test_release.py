import base64
from contextlib import closing
import csv
import http.cookiejar
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_temporary=tempfile.TemporaryDirectory()
os.environ['JZ_DATA_DIR']=_temporary.name
import sjtu_excel_io as xio
import sjtu_match_reviewers as matcher
import web_server as web


class WorkbookTests(unittest.TestCase):
    def test_example_uses_only_fictional_students(self):
        rows=xio.read_xlsx_rows(io.BytesIO(xio.generate_example_template_xlsx()))
        students,_,banner=xio.parse_students_from_rows(rows)
        self.assertEqual(len(students),6)
        self.assertTrue(all(s['name'] in {'张三','李四','王五','赵六','孙七','周八'} and s['student_id'].startswith('52x') for s in students))
        self.assertEqual({s["category"] for s in students},{"人文社科类","信息技术类","机械控制自动化类","生农医药类","能源化工材料类"})
        self.assertEqual(banner,xio.DEFAULT_TASK_BANNER)

    def test_blank_templates_are_header_only(self):
        rows=xio.read_xlsx_rows(io.BytesIO(xio.generate_blank_template_xlsx()))
        self.assertEqual(rows,[xio.STUDENT_BASE_COLS])
        self.assertEqual(list(csv.reader(io.StringIO(xio.generate_blank_template_csv().decode('utf-8-sig')))),[xio.STUDENT_BASE_COLS])

    def test_merged_export_never_inherits_private_banner(self):
        students=xio.fictional_students()[:1]
        blob=xio.generate_merged_table_xlsx(students,[[]],banner_text='PRIVATE OWNER AND DATE')
        self.assertEqual(xio.read_xlsx_rows(io.BytesIO(blob))[0][0],xio.DEFAULT_TASK_BANNER)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            sheet=z.read('xl/worksheets/sheet1.xml').decode()
            self.assertIn('A1:M1',sheet);self.assertIn('A3:A5',sheet)
            self.assertNotIn('PRIVATE OWNER',sheet)

    def test_banner_has_fillable_fields(self):
        banner=xio.DEFAULT_TASK_BANNER
        self.assertIn('xxxx-202x春/秋',banner)
        self.assertIn('        1.\n',banner)
        self.assertIn('负责人：\n',banner)
        self.assertIn('x月x日（xx周周x）晚20:00',banner)

    def test_horizontal_export_preserves_schema(self):
        data=xio.generate_horizontal_csv(xio.fictional_students()[:1],[[]],pick_count=3)
        rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0][:7],xio.STUDENT_BASE_COLS)
        self.assertIn('评审3匹配方向',rows[0]);self.assertIn('评审3相近程度',rows[0])
        self.assertFalse(any('核验' in c for c in rows[0]))

    def test_csv_formula_like_names_are_literal(self):
        student=dict(xio.fictional_students()[0],name='=1+1')
        data=xio.generate_horizontal_csv([student],[[]]).decode('utf-8-sig')
        self.assertIn("'=1+1",data)

    def test_oversized_expansion_rejected(self):
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,'w') as z:
            for i in range(3001):z.writestr(str(i),'')
        blob.seek(0)
        with self.assertRaises(ValueError):xio.read_xlsx_rows(blob)

    def test_sampler_and_title_constraints(self):
        import random
        rng=random.Random(42)
        high=sum(matcher.weighted_sample_without_replacement(2,1,[.9,.1],rng)==[0] for _ in range(10000))
        self.assertGreater(high,8700);self.assertLess(high,9300)
        self.assertTrue(matcher.is_senior_title('副教授、研究员'))
        self.assertFalse(matcher.is_senior_title('长聘教轨副教授'))


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=web.ThreadingHTTPServer(('127.0.0.1',0),web.FacultyRequestHandler)
        cls.server.daemon_threads=True
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def setUp(self):
        self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self,path,data=None,client=None,headers=None):
        h={'Content-Type':'application/json'};h.update(headers or {})
        request=urllib.request.Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers=h)
        with (client or self.client).open(request,timeout=20) as response:return response.read()

    def test_untrusted_hostname_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/db/stats',headers={'Host':'untrusted.invalid'})
        self.assertEqual(error.exception.code,403);error.exception.close()
    def test_configured_password_is_required(self):
        from unittest.mock import patch
        with patch.dict(os.environ,{'JZ_PASSWORD':'test-only-password'}):
            with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/db/stats')
            self.assertEqual(error.exception.code,401);error.exception.close()
            auth=base64.b64encode(b'user:test-only-password').decode()
            self.assertIn('total',json.loads(self.call('/api/db/stats',headers={'Authorization':'Basic '+auth})))
    def test_database_export_formula_like_names_are_literal(self):
        item=web.create_faculty({'name':'=FAKE_FORMULA()','title':'副教授'})
        try:
            data=self.call('/api/db/export_csv').decode('utf-8-sig')
            self.assertIn("'=FAKE_FORMULA()",data)
        finally:web.delete_faculty(item['id'])
    def test_health(self):self.assertEqual(json.loads(self.call('/health'))['status'],'ok')
    def test_example_and_template_downloads(self):
        for kind in ('student','teacher','example'):
            data=self.call('/api/template?type='+kind+'&format=xlsx')
            self.assertTrue(data.startswith(b'PK'))
    def test_complete_preview_and_exports(self):
        result=json.loads(self.call('/api/match/run',{'use_sample':True,'params':{}}))
        self.assertEqual(result['matched_full'],6)
        self.assertTrue(all(len(s['reviewers'])==3 for s in result['items']))
        for student in result['items']:
            names=[r['name'] for r in student['reviewers']]
            self.assertEqual(len(set(names)),3);self.assertNotIn(student['advisor'],names)
        self.assertTrue(self.call('/api/match/export?format=xlsx').startswith(b'PK'))
        self.assertIn('评审1相近程度',self.call('/api/match/export?format=csv').decode('utf-8-sig'))
    def test_sessions_do_not_share_last_match(self):
        self.call('/api/match/run',{'use_sample':True})
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/match/export?format=csv',client=other)
        self.assertEqual(error.exception.code,400);error.exception.close()
    def test_cross_origin_write_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/match/run',{'use_sample':True},headers={'Origin':'https://untrusted.invalid'})
        self.assertEqual(error.exception.code,403);error.exception.close()
    def test_invalid_parameters_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/match/run',{'use_sample':True,'params':{'pick_count':100000}})
        error.exception.close()
    def test_layout_samples_cover_all_pages(self):
        first=json.loads(self.call('/api/db/list?page=1&page_size=5'))
        second=json.loads(self.call('/api/db/list?page=2&page_size=5'))
        self.assertEqual(first['layout_samples'],second['layout_samples'])
    def test_nonlocal_binding_requires_password(self):
        with self.assertRaises(ValueError):web.run_server('0.0.0.0',0)
    def test_legacy_script_parameters_still_available(self):
        self.assertTrue((web.SCRIPT_DIR/'sjtu_faculty_scraper.py').exists())
        text=(web.SCRIPT_DIR/'frontend/index.html').read_text()
        for key in ('param-pool','param-seed','param-strict','param-allow-unknown'):
            self.assertIn(key,text)


if __name__=='__main__':unittest.main()

class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        import shutil
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name)/'faculty.db'
        shutil.copyfile(Path(web.SCRIPT_DIR)/'data/faculty.db',self.path)
        self.patch=patch.object(web,'DB_PATH',self.path);self.patch.start()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('DELETE FROM faculty')
            conn.executemany('INSERT INTO faculty(id,teacher_id,name,title,department,college) VALUES(?,?,?,?,?,?)',[
                (1,2,'同名教师','副教授','计算机学院','计算机学院'),
                (2,3,'同名教师','副教授','材料科学与工程学院','材料科学与工程学院')])
            conn.commit()
    def tearDown(self):
        self.patch.stop();self.folder.cleanup()
    def test_delete_uses_exact_primary_key(self):
        self.assertEqual(web.delete_faculty(2)['deleted'],1)
        with closing(sqlite3.connect(self.path)) as conn:self.assertEqual(conn.execute('SELECT id FROM faculty').fetchall(),[(1,)])
    def test_update_uses_exact_primary_key(self):
        web.update_faculty(2,{'name':'指定教师'})
        with closing(sqlite3.connect(self.path)) as conn:self.assertEqual(conn.execute('SELECT name FROM faculty ORDER BY id').fetchall(),[('同名教师',),('指定教师',)])
    def test_explicit_teacher_id_lookup(self):
        self.assertEqual(web.delete_faculty(2,by_teacher_id=True)['deleted'],1)
        with closing(sqlite3.connect(self.path)) as conn:self.assertEqual(conn.execute('SELECT id FROM faculty').fetchall(),[(2,)])
    def test_empty_name_update_rejected(self):
        with self.assertRaisesRegex(ValueError,'姓名'):web.update_faculty(1,{'name':''})
    def test_merge_matches_existing_department_among_namesakes(self):
        data='姓名,院系,研究方向\n同名教师,材料科学与工程学院,储能研究\n'.encode('utf-8-sig')
        result=web.merge_teachers_from_bytes(data,'teachers.csv',dry_run=False)
        self.assertEqual(result['merged_same_dept_count'],1)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM faculty').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT research_direction FROM faculty WHERE id=2').fetchone()[0],'储能研究')
    def test_running_maintenance_blocks_mutation(self):
        from unittest.mock import patch
        with patch.object(web,'TASKS',{'probe':{'status':'running'}}):
            with self.assertRaisesRegex(ValueError,'运行中'):web.delete_faculty(1)
    def test_missing_advisor_rejected(self):
        rows=[xio.STUDENT_BASE_COLS,['1','信息技术类','张三','52x0001','图像研究','','计算机学院']]
        with self.assertRaisesRegex(ValueError,'导师姓名'):xio.parse_students_from_rows(rows)
    def test_blank_student_template_has_no_matching_rows(self):
        with self.assertRaisesRegex(ValueError,'没有有效学生'):xio.parse_students_from_rows([xio.STUDENT_BASE_COLS])
    def test_sparse_extreme_column_is_rejected(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{xio.NS_MAIN}"><sheetData><row><c r="ZZZ1" t="inlineStr"><is><t>x</t></is></c></row></sheetData></worksheet>')
        data.seek(0)
        with self.assertRaisesRegex(ValueError,'256列'):xio.read_xlsx_rows(data)

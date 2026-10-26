"""Fail releases containing production workbooks, private records or credentials."""
import re
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SKIP={'.git','.venv','__pycache__','build','dist'}
ALLOWED_BOOKS={'examples/fictional-students.xlsx','examples/blank-students.xlsx','examples/blank-students.csv'}


def check():
    errors=[]
    for path in ROOT.rglob('*'):
        relative=path.relative_to(ROOT)
        if any(part in SKIP for part in relative.parts) or not path.is_file():continue
        name=relative.as_posix()
        if 'sjtu_faculty_data' in relative.parts or 'runtime' in relative.parts or 'backups' in relative.parts:
            errors.append(name+': runtime/production files must not be shipped')
        if path.suffix.lower() in ('.xlsx','.xls','.csv','.db','.sqlite') and name not in ALLOWED_BOOKS|{'data/faculty.db'}:
            errors.append(name+': non-allowlisted data file')
        if path.name in ('.env','session.key') or path.suffix=='.log':errors.append(name+': private configuration/log')
        if path.suffix.lower() in ('.py','.js','.html','.css','.md','.yaml','.yml','.txt'):
            text=path.read_text(errors='replace')
            if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)',text):errors.append(name+': credential pattern')
            if re.search(('/'+'Users'+r'/[^/\s]+/|C:\\Users\\[^\\\s]+'),text):errors.append(name+': hardcoded home directory')
            if re.search(r'(?<!\d)1[3-9]\d{9}(?!\d)',text):errors.append(name+': possible real mobile number')
    with sqlite3.connect(ROOT/'data/faculty.db') as conn:
        rows=conn.execute('SELECT name FROM faculty').fetchall()
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not rows:errors.append('faculty.db: public faculty database is empty')
        if not tables <= {'faculty','sqlite_sequence'}:errors.append('faculty.db: unexpected non-faculty table')
    from junzheng_match import sjtu_excel_io as xio
    for student in xio.fictional_students():
        if student['name'] not in {'张三','李四','王五','赵六','孙七','周八'} or not student['student_id'].startswith('52x') or not student['advisor'].endswith('老师'):
            errors.append('example generator: non-synthetic student')
    if errors:raise RuntimeError('\n'.join(errors))
    return dict(status='ok',public_faculty=len(rows),real_students=0,private_databases=0)


if __name__=='__main__':
    sys.path.insert(0,str(ROOT/"src"))
    print(check())

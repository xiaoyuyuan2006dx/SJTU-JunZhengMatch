"""Portable desktop/EXE entry; resources bundled, mutable data kept outside the EXE."""
import argparse
import json
import os
import runpy
import sys
import tempfile
import threading
import urllib.request
import webbrowser
from pathlib import Path

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))


def self_test(report=None):
    with tempfile.TemporaryDirectory() as folder:
        os.environ['JZ_DATA_DIR']=folder
        import web_server as server
        import sjtu_excel_io as xio
        result=server.run_match_pipeline(xio.generate_example_template_xlsx(),'fictional.xlsx',{})
        assert result['total_matched_students']==6 and result['matched_full']==6
        output=xio.generate_merged_table_xlsx(server.LAST_MATCH_SESSION['students'],server.LAST_MATCH_SESSION['results'])
        assert xio.read_xlsx_rows(__import__('io').BytesIO(output))[0][0]==xio.DEFAULT_TASK_BANNER
        status=dict(status='ok',students=6,reviewers=18,synthetic_data=True)
        if report:Path(report).write_text(json.dumps(status),encoding='utf-8')
        return status


def main():
    if '--internal-script' in sys.argv:
        index=sys.argv.index('--internal-script');name=sys.argv[index+1]
        allowed={'sjtu_faculty_scraper.py','sjtu_scrape_research.py','sjtu_fix_college.py','sjtu_web_fix_college.py'}
        if name not in allowed:raise ValueError('Unsupported internal script')
        sys.argv=[str(ROOT/name)]+sys.argv[index+2:]
        runpy.run_path(str(ROOT/name),run_name='__main__');return
    parser=argparse.ArgumentParser(description='䇹政盲审导师匹配')
    parser.add_argument('--host',default=os.getenv('JZ_HOST','127.0.0.1'));parser.add_argument('--port',type=int,default=int(os.getenv('JZ_PORT','8765')))
    parser.add_argument('--no-open',action='store_true');parser.add_argument('--self-test',action='store_true');parser.add_argument('--report')
    args=parser.parse_args()
    if args.self_test:
        self_test(args.report);return
    from web_server import run_server
    address=f'http://127.0.0.1:{args.port}'
    if not args.no_open:
        try:
            with urllib.request.urlopen(address+'/health',timeout=1) as response:
                if json.load(response).get('service')=='SJTU-JunZhengMatch':
                    webbrowser.open(address);return
        except Exception:pass
        threading.Timer(.8,lambda:webbrowser.open(address)).start()
    run_server(args.host,args.port)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        if '--self-test' in sys.argv:
            if '--report' in sys.argv:
                Path(sys.argv[sys.argv.index('--report')+1]).write_text(json.dumps({'status':'error','error':str(exc)}))
            raise
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(exc),'䇹政评审匹配',0)
        else:raise
        sys.exit(1)

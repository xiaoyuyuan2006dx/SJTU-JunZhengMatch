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


def initialize_streams():
    # Windows windowed EXE has no Python standard streams. Internal workers
    # reconnect to the inherited pipe so crawler progress reaches the web UI.
    if sys.stdout is None:
        if sys.platform=="win32" and "--internal-script" in sys.argv:
            import ctypes, msvcrt
            get_handle=ctypes.windll.kernel32.GetStdHandle
            get_handle.restype=ctypes.c_void_p
            handle=get_handle(-11)
            if handle and handle!=ctypes.c_void_p(-1).value:
                sys.stdout=os.fdopen(msvcrt.open_osfhandle(handle,os.O_WRONLY),"w",encoding="utf-8",buffering=1)
        if sys.stdout is None:sys.stdout=open(os.devnull,"w",encoding="utf-8")
    if sys.stderr is None:sys.stderr=sys.stdout
    if sys.stdin is None:sys.stdin=open(os.devnull,"r",encoding="utf-8")
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):stream.reconfigure(encoding="utf-8",errors="backslashreplace")


def self_test(report=None):
    with tempfile.TemporaryDirectory() as folder:
        os.environ['JZ_DATA_DIR']=folder
        import web_server as server
        import sjtu_excel_io as xio
        import importlib
        for module in ("sjtu_faculty_scraper","sjtu_scrape_research","sjtu_fix_college","sjtu_web_fix_college"):
            importlib.import_module(module)
        result=server.run_match_pipeline(xio.generate_example_template_xlsx(),'fictional.xlsx',{})
        assert result['total_matched_students']==6 and result['matched_full']==6
        output=xio.generate_merged_table_xlsx(server.LAST_MATCH_SESSION['students'],server.LAST_MATCH_SESSION['results'])
        assert xio.read_xlsx_rows(__import__('io').BytesIO(output))[0][0]==xio.DEFAULT_TASK_BANNER
        status=dict(status='ok',students=6,reviewers=18,synthetic_data=True,crawler_modules=4)
        if report:Path(report).write_text(json.dumps(status),encoding='utf-8')
        return status


def main():
    initialize_streams()
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
        import traceback
        try:
            folder=Path(os.getenv("JZ_DATA_DIR",tempfile.gettempdir()));folder.mkdir(parents=True,exist_ok=True)
            (folder/"JunZhengMatch-startup-error.log").write_text(traceback.format_exc(),encoding="utf-8")
        except OSError:pass
        if sys.platform=='win32' and "--no-open" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(exc),'䇹政评审匹配',0)
        else:raise
        sys.exit(1)

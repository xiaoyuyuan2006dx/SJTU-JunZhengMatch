"""Portable browser launcher, shared service and installed desktop entry point."""
import argparse
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import webbrowser
from . import paths, preferences, runtime


def initialize_streams():
    if sys.stdout is None:
        if os.name=='nt' and '--internal-script' in sys.argv:
            import ctypes,msvcrt
            function=ctypes.windll.kernel32.GetStdHandle;function.restype=ctypes.c_void_p
            handle=function(-11)
            if handle and handle!=ctypes.c_void_p(-1).value:sys.stdout=os.fdopen(msvcrt.open_osfhandle(handle,os.O_WRONLY),'w',encoding='utf-8',buffering=1)
        if sys.stdout is None:sys.stdout=open(os.devnull,'w',encoding='utf-8')
    if sys.stderr is None:sys.stderr=sys.stdout
    if sys.stdin is None:sys.stdin=open(os.devnull,'r',encoding='utf-8')
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='backslashreplace')


def self_test(report):
    with tempfile.TemporaryDirectory() as folder:
        os.environ['JZ_DATA_DIR']=os.environ['JZ_CONFIG_DIR']=folder
        from . import web_server as server,sjtu_excel_io as xio
        for module in ('sjtu_faculty_scraper','sjtu_scrape_research','sjtu_fix_college','sjtu_web_fix_college'):
            importlib.import_module('.crawlers.'+module,__package__)
        result=server.run_match_pipeline(xio.generate_example_template_xlsx(),'fictional.xlsx',{})
        assert result['matched_full']==6
        from collections import Counter
        counts=Counter(server.matcher.normalize_name(r['name']) for s in result['items'] for r in s['reviewers'])
        assert max(counts.values())<=2
        output=xio.generate_merged_table_xlsx(server.LAST_MATCH_SESSION['students'],server.LAST_MATCH_SESSION['results'])
        assert xio.read_xlsx_rows(__import__('io').BytesIO(output))[0][0]==xio.DEFAULT_TASK_BANNER
        status=dict(status='ok',students=6,reviewers=18,max_teacher_uses=2,crawler_modules=4)
        if report:Path(report).write_text(json.dumps(status),encoding='utf-8')
        return status


def main():
    initialize_streams()
    if '--internal-script' in sys.argv:
        index=sys.argv.index('--internal-script');name=Path(sys.argv[index+1]).stem
        if name not in ('sjtu_faculty_scraper','sjtu_scrape_research','sjtu_fix_college','sjtu_web_fix_college'):raise ValueError('未知维护脚本。')
        sys.argv=[name]+sys.argv[index+2:];runpy.run_module(__package__+'.crawlers.'+name,run_name='__main__');return
    parser=argparse.ArgumentParser(description='䇹政导师匹配')
    parser.add_argument('--host',default=os.getenv('JZ_HOST','127.0.0.1'));parser.add_argument('--port',type=int,default=int(os.getenv('JZ_PORT','8765')))
    parser.add_argument('--no-open',action='store_true');parser.add_argument('--serve',action='store_true');parser.add_argument('--desktop',action='store_true')
    parser.add_argument('--launch-only',action='store_true');parser.add_argument('--desktop-smoke',action='store_true');parser.add_argument('--self-test',action='store_true');parser.add_argument('--report')
    parser.add_argument('--data-dir');parser.add_argument('--configure-data');parser.add_argument('--ensure-webview2',action='store_true');parser.add_argument('--pick-directory',action='store_true')
    args=parser.parse_args()
    if args.data_dir:os.environ['JZ_DATA_DIR']=str(Path(args.data_dir).expanduser().resolve())
    if args.self_test:return self_test(args.report)
    if args.pick_directory:
        from .native import pick_directory
        selected=pick_directory()
        if args.report:Path(args.report).write_text(json.dumps({'path':selected}),encoding='utf-8')
        return
    store=preferences.PreferenceStore()
    if args.configure_data:
        target=preferences.prepare_folder(args.configure_data)
        if args.ensure_webview2:
            from .native import ensure_webview2
            ensure_webview2()
        store.write(dict(data_dir=str(target),storage_confirmed=True));return
    if args.serve or args.no_open or args.host not in ('127.0.0.1','localhost','::1'):
        from .web_server import run_server
        return run_server(args.host,args.port)
    folder=preferences.prepare_folder(store.data_dir());instance=runtime.ensure_backend(folder,args.port,store.root)
    if args.launch_only:
        if args.report:Path(args.report).write_text(json.dumps(instance),encoding='utf-8')
        return
    if args.desktop or args.desktop_smoke:
        from .native import open_desktop
        return open_desktop(instance,folder,args.report if args.desktop_smoke else None)
    if args.report:Path(args.report).write_text(json.dumps(instance),encoding='utf-8')
    webbrowser.open(instance['url'])


def launch():
    try:main()
    except Exception as error:
        import traceback
        try:
            folder=Path(os.getenv('JZ_DATA_DIR',tempfile.gettempdir()));folder.mkdir(parents=True,exist_ok=True)
            (folder/'JunZhengMatch-startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
            if '--report' in sys.argv:Path(sys.argv[sys.argv.index('--report')+1]).write_text(json.dumps({'status':'error','error':str(error)}),encoding='utf-8')
        except OSError:pass
        if os.name=='nt' and not any(arg in sys.argv for arg in ('--no-open','--serve','--self-test','--desktop-smoke','--launch-only','--configure-data')):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(error),'䇹政导师匹配',0)
        else:raise
        sys.exit(1)

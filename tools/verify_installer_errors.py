"""A frozen installer helper must fail promptly without a bootloader popup."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True);parser.add_argument('--report',required=True);args=parser.parse_args()
exe=Path(args.exe).resolve();invalid=exe.parent/'forbidden-runtime-data'
with tempfile.TemporaryDirectory() as folder:
    result_path=Path(folder)/'result.json'
    env={**os.environ,'JZ_CONFIG_DIR':folder};env.pop('JZ_DATA_DIR',None)
    process=subprocess.Popen([str(exe),'--configure-data',str(invalid),'--report',str(result_path)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:code=process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
        raise RuntimeError('Installer helper opened a blocking dialog or hung')
    assert code!=0,'Invalid storage path was accepted'
    result=json.loads(result_path.read_text(encoding='utf-8'))
    assert result['status']=='error' and result['error']
    assert not invalid.exists(),'Invalid storage folder was created'
report=dict(status='ok',invalid_path_rejected=True,nonzero_exit=True,error_report_written=True,no_blocking_dialog=True)
Path(args.report).write_text(json.dumps(report),encoding='utf-8');print(json.dumps(report))

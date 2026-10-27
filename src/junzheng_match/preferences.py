"""Persist user preferences independently from the selected data folder."""
import json
import os
import secrets
import threading
from pathlib import Path
from . import paths

DEFAULT_MATCH=dict(pick_count=3,pool_size=20,max_teacher_uses=2,strategy='top',seed=42,min_score=.05,relative_score=.4,strict=False,allow_unknown_title=False)


def validate_match(values):
    if not isinstance(values,dict):raise ValueError('默认参数须为对象。')
    result={**DEFAULT_MATCH,**{k:v for k,v in values.items() if k in DEFAULT_MATCH}}
    for key,low,high in [('pick_count',1,15),('pool_size',1,2000),('max_teacher_uses',1,10000)]:
        value=result[key]
        if isinstance(value,bool) or int(value)!=float(value) or not low<=int(value)<=high:raise ValueError(f'{key}须为{low}—{high}的整数。')
        result[key]=int(value)
    if result['pool_size']<result['pick_count']:raise ValueError('候选池不能小于每人的评审数。')
    for key in ('min_score','relative_score'):
        result[key]=float(result[key])
        if not 0<=result[key]<=1:raise ValueError('相近度阈值须为0—1。')
    result['seed']=int(result['seed'])
    if result['strategy'] not in ('top','weighted'):raise ValueError('未知选取策略。')
    for key in ('strict','allow_unknown_title'):
        if not isinstance(result[key],bool):raise ValueError(f'{key}须为布尔值。')
    return result


class PreferenceStore:
    def __init__(self,root=None):
        self.root=Path(root or paths.CONFIG_ROOT);self.file=self.root/'preferences.json';self.lock=threading.RLock()
    def read(self):
        with self.lock:
            result=dict(data_dir=str(paths.DEFAULT_HOME),storage_confirmed=False,retain_uploads=False,match_defaults=dict(DEFAULT_MATCH))
            if self.file.exists():
                saved=json.loads(self.file.read_text(encoding='utf-8'))
                if not isinstance(saved,dict):raise ValueError('偏好设置文件格式错误，请从备份恢复。')
                result.update(saved)
            elif os.getenv('JZ_DATA_DIR'):result['data_dir']=str(Path(os.environ['JZ_DATA_DIR']).resolve())
            result['match_defaults']=validate_match(result.get('match_defaults',{}))
            return result
    def write(self,changes):
        with self.lock:
            current=self.read();current.update(changes)
            current['match_defaults']=validate_match(current['match_defaults'])
            self.root.mkdir(parents=True,exist_ok=True)
            temp=self.file.with_name('.preferences-'+secrets.token_hex(4)+'.tmp')
            temp.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8');temp.chmod(0o600)
            os.replace(temp,self.file)
            self.remember_install_location(current)
            return current
    def remember_install_location(self,current=None):
        if os.name=='nt' and self.root.resolve()==paths.DEFAULT_HOME.resolve():
            import winreg
            current=current or self.read()
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\TaroDeluxe\JunZhenMatch') as key:winreg.SetValueEx(key,'DataDir',0,winreg.REG_SZ,current['data_dir'])
    def data_dir(self):
        return Path(os.getenv('JZ_DATA_DIR') or self.read()['data_dir']).expanduser().resolve()


def prepare_folder(folder):
    folder=Path(folder).expanduser().resolve()
    program=Path(__import__('sys').executable).parent if getattr(__import__('sys'),'frozen',False) else paths.RESOURCE_ROOT
    if folder==paths.RESOURCE_ROOT or paths.RESOURCE_ROOT in folder.parents or folder==program or program in folder.parents:
        raise ValueError('请选择程序目录之外的用户数据位置。')
    folder.mkdir(parents=True,exist_ok=True)
    test=folder/('.write-test-'+secrets.token_hex(4))
    try:test.write_text('ok');test.unlink()
    except OSError as exc:raise ValueError('所选目录不可写。') from exc
    for name in ('backups','exports','uploads','logs'): (folder/name).mkdir(exist_ok=True)
    return folder

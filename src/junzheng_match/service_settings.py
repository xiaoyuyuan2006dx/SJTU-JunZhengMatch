"""Storage migration, client presence and application-wide settings."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
from . import paths, preferences, runtime


def verify_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('数据库完整性检查失败。')
        fields={r[1] for r in conn.execute('PRAGMA table_info(faculty)')}
        required={'id','teacher_id','name','title','department','college','email','phone','mobile','research_direction','profile_text','profile_url'}
        if not required<=fields:raise ValueError('所选文件不是兼容的教师数据库。')


class ServiceSettings:
    def __init__(self,app):self.app=app
    def busy(self):
        a=self.app
        return a.ACTIVE_OPERATIONS>0 or any(t.get('status')=='running' for t in a.TASKS.values())
    def clients(self):
        a=self.app
        with a.ACTIVITY_LOCK:
            now=time.time()
            a.CLIENTS={k:v for k,v in a.CLIENTS.items() if now-v['seen']<50}
            return list(a.CLIENTS.values())
    def status(self,local=True):
        a=self.app
        return dict(clients=len(self.clients()),busy=self.busy(),can_exit=local and not os.getenv('JZ_MANAGED_DATA'),exit_token=a.EXIT_TOKEN if local else '',instance_id=a.INSTANCE_ID)
    def get(self):
        a=self.app;values=a.PREFERENCES.read()
        return {**values,'data_dir':str(a.DATA_DIR),'default_data_dir':str(paths.DEFAULT_HOME),'managed_storage':bool(os.getenv('JZ_MANAGED_DATA')),'backup_count':len(list((a.DATA_DIR/'backups').glob('*.db')))}
    def save(self,body):
        a=self.app
        if not isinstance(body,dict):raise ValueError('偏好设置须为对象。')
        with a.DB_WRITE_LOCK:
            if self.busy():raise ValueError('请等待匹配或维护任务结束后再修改设置。')
            defaults=preferences.validate_match(body.get('match_defaults',a.PREFERENCES.read()['match_defaults']))
            retain=body.get('retain_uploads',a.PREFERENCES.read().get('retain_uploads',False))
            if not isinstance(retain,bool):raise ValueError('保留原表须为布尔值。')
            target=Path(body.get('data_dir') or a.DATA_DIR).expanduser().resolve()
            if target!=a.DATA_DIR:
                if os.getenv('JZ_MANAGED_DATA'):raise ValueError('Docker数据路径由挂载设置指定。')
                mode=body.get('migration','auto')
                if mode=='auto':mode='existing' if (target/'sjtu_faculty_data.db').exists() else 'copy'
                self.migrate(target,mode)
            a.PREFERENCES.write(dict(data_dir=str(a.DATA_DIR),storage_confirmed=True,match_defaults=defaults,retain_uploads=retain))
            return self.get()
    def migrate(self,target,mode):
        a=self.app;old=a.DATA_DIR
        if mode not in ('copy','existing'):raise ValueError('请选择迁移现有数据或使用目标库。')
        if target==old or old in target.parents or target in old.parents:raise ValueError('新旧数据目录不能互相包含。')
        # Validate ownership before populating a target, and keep the original intact.
        target=preferences.prepare_folder(target)
        new_lock=runtime.FolderLock(target).acquire()
        database=target/'sjtu_faculty_data.db'
        try:
            if mode=='copy':
                if database.exists():raise ValueError('目标位置已有教师库。请使用目标库，或选择空目录。')
                if any(any((target/name).iterdir()) for name in ('backups','exports','uploads','logs')):raise ValueError('迁移目标须为空目录，避免覆盖已有文件。')
                a.database_backup()
                with closing(sqlite3.connect(a.DB_PATH)) as source,closing(sqlite3.connect(database)) as dest:source.backup(dest)
                for name in ('backups','exports','uploads','profiles'):
                    if (old/name).exists():shutil.copytree(old/name,target/name,dirs_exist_ok=True)
            elif not database.exists():raise ValueError('目标位置没有教师数据库，请选择迁移现有数据。')
            verify_database(database)
            a.PREFERENCES.write(dict(data_dir=str(target),storage_confirmed=True))
            a.DATA_DIR=target;a.DB_PATH=database;a.matcher.DB_PATH=a.qdb.DB_PATH=database
            os.environ['JZ_DATA_DIR']=str(target)
            if a.SERVER_INSTANCE:
                runtime.write_instance(target,a.SERVER_INSTANCE.server_port,a.INSTANCE_ID)
                old_registry=runtime.registry_path(old)
                if old_registry.exists() and json.loads(old_registry.read_text()).get('instance_id')==a.INSTANCE_ID:old_registry.unlink()
            if a.INSTANCE_LOCK:a.INSTANCE_LOCK.release()
            a.INSTANCE_LOCK=new_lock;new_lock=None
        finally:
            if new_lock:new_lock.release()
    def restore(self,blob):
        a=self.app
        with a.DB_WRITE_LOCK:
            if self.busy():raise ValueError('请等待任务结束后恢复数据库。')
            with tempfile.TemporaryDirectory() as folder:
                source=Path(folder)/'restore.db';source.write_bytes(blob);verify_database(source)
                a.database_backup()
                with closing(sqlite3.connect(source)) as incoming,closing(sqlite3.connect(a.DB_PATH)) as current:incoming.backup(current)
            return dict(status='ok',message='数据库已恢复，恢复前的库已备份。')
    def open_folder(self,kind='data'):
        a=self.app
        if kind not in ('data','exports','backups','uploads'):raise ValueError('未知文件夹。')
        folder=a.DATA_DIR if kind=='data' else a.DATA_DIR/kind
        if os.getenv('JZ_MANAGED_DATA'):raise ValueError('Docker中请在宿主机打开挂载目录。')
        if os.name=='nt':os.startfile(str(folder))
        elif __import__('sys').platform=='darwin':subprocess.Popen(['open',str(folder)])
        else:subprocess.Popen(['xdg-open',str(folder)])
        return dict(status='ok')

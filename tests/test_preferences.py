from bootstrap import TEMPORARY
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from junzheng_match import paths,preferences,runtime
from junzheng_match.service_settings import ServiceSettings


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        folder=preferences.prepare_folder(self.root/'original');db=folder/'sjtu_faculty_data.db';shutil.copy2(paths.SEED_DB,db)
        store=preferences.PreferenceStore(self.root/'config');store.write({'data_dir':str(folder)})
        self.app=SimpleNamespace(DATA_DIR=folder,DB_PATH=db,PREFERENCES=store,DB_WRITE_LOCK=threading.RLock(),ACTIVE_OPERATIONS=0,TASKS={},INSTANCE_LOCK=None,SERVER_INSTANCE=None,matcher=SimpleNamespace(DB_PATH=db),qdb=SimpleNamespace(DB_PATH=db))
        def backup():
            with closing(sqlite3.connect(self.app.DB_PATH)) as src,closing(sqlite3.connect(self.app.DATA_DIR/'backups/before.db')) as dest:src.backup(dest)
        self.app.database_backup=backup;self.manager=ServiceSettings(self.app)
    def tearDown(self):
        if self.app.INSTANCE_LOCK:self.app.INSTANCE_LOCK.release()
        self.temp.cleanup()
    def test_defaults_have_cap_two(self):self.assertEqual(self.manager.get()['match_defaults']['max_teacher_uses'],2)
    def test_saving_confirms_first_use_and_persists(self):
        self.manager.save({'retain_uploads':True,'match_defaults':{'max_teacher_uses':4}})
        settings=preferences.PreferenceStore(self.root/'config').read()
        self.assertTrue(settings['storage_confirmed']);self.assertTrue(settings['retain_uploads']);self.assertEqual(settings['match_defaults']['max_teacher_uses'],4)
    def test_copy_migration_preserves_original(self):
        old=self.app.DATA_DIR;old_db=self.app.DB_PATH.read_bytes()
        result=self.manager.save({'data_dir':str(self.root/'target'),'migration':'copy'})
        self.assertEqual(Path(result['data_dir']),(self.root/'target').resolve());self.assertEqual(old_db,(old/'sjtu_faculty_data.db').read_bytes());self.assertTrue(self.app.DB_PATH.exists())
    def test_existing_target_is_not_silently_overwritten(self):
        target=preferences.prepare_folder(self.root/'target');shutil.copy2(paths.SEED_DB,target/'sjtu_faculty_data.db')
        original=self.app.DATA_DIR
        with self.assertRaisesRegex(ValueError,'已有教师库'):self.manager.save({'data_dir':str(target),'migration':'copy'})
        self.assertEqual(self.app.DATA_DIR,original)
    def test_use_existing_target(self):
        target=preferences.prepare_folder(self.root/'existing');shutil.copy2(paths.SEED_DB,target/'sjtu_faculty_data.db')
        with closing(sqlite3.connect(target/'sjtu_faculty_data.db')) as conn:conn.execute('DELETE FROM faculty');conn.commit()
        self.manager.save({'data_dir':str(target),'migration':'existing'})
        with closing(sqlite3.connect(self.app.DB_PATH)) as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM faculty').fetchone()[0],0)
    def test_nested_data_directory_rejected(self):
        with self.assertRaisesRegex(ValueError,'互相包含'):self.manager.save({'data_dir':str(self.app.DATA_DIR/'nested')})
    def test_invalid_target_database_keeps_current(self):
        target=preferences.prepare_folder(self.root/'bad');(target/'sjtu_faculty_data.db').write_bytes(b'not sqlite')
        original=self.app.DATA_DIR
        with self.assertRaises(sqlite3.DatabaseError):self.manager.save({'data_dir':str(target),'migration':'existing'})
        self.assertEqual(self.app.DATA_DIR,original)
    def test_busy_service_rejects_storage_change(self):
        self.app.ACTIVE_OPERATIONS=1
        with self.assertRaisesRegex(ValueError,'任务结束'):self.manager.save({'data_dir':str(self.root/'new')})
    def test_running_script_rejects_restore(self):
        self.app.TASKS={'test':{'status':'running'}}
        with self.assertRaisesRegex(ValueError,'任务结束'):self.manager.restore(paths.SEED_DB.read_bytes())
    def test_invalid_backup_keeps_existing_database(self):
        original=self.app.DB_PATH.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):self.manager.restore(b'invalid backup')
        self.assertEqual(original,self.app.DB_PATH.read_bytes())
    def test_folder_lock_prevents_duplicate_owner(self):
        first=runtime.FolderLock(self.app.DATA_DIR).acquire()
        try:
            with self.assertRaises(RuntimeError):runtime.FolderLock(self.app.DATA_DIR).acquire()
        finally:first.release()
    def test_corrupt_preferences_are_not_overwritten(self):
        self.app.PREFERENCES.file.write_text('broken json')
        with self.assertRaises(ValueError):self.app.PREFERENCES.write({'retain_uploads':True})
        self.assertEqual(self.app.PREFERENCES.file.read_text(),'broken json')

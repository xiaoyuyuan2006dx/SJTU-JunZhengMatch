import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
TEMPORARY=tempfile.TemporaryDirectory()
os.environ['JZ_DATA_DIR']=os.environ['JZ_CONFIG_DIR']=TEMPORARY.name

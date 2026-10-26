"""Source and PyInstaller launcher."""
import sys
from pathlib import Path
if not getattr(sys,"frozen",False):sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"src"))
from junzheng_match.entrypoint import launch
if __name__=="__main__":launch()

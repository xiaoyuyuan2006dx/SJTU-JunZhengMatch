"""Run the regression suite and write a compact, non-sensitive CI report."""
import argparse,json
from pathlib import Path
import unittest
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',default='tests-report.json');args=parser.parse_args()
    suite=unittest.defaultTestLoader.discover('tests')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    Path(args.report).write_text(json.dumps(dict(status='ok' if result.wasSuccessful() else 'error',tests=result.testsRun,failures=len(result.failures),errors=len(result.errors))),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)

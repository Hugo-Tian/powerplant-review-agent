"""Serve the built Vue app with a disposable database for Playwright."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / '.local-deps').is_dir():
    sys.path.insert(0, str(ROOT / '.local-deps'))

import uvicorn
from demo_api import create_app

if __name__ == '__main__':
    with TemporaryDirectory(prefix='power-plant-e2e-') as tmp:
        uvicorn.run(create_app(Path(tmp) / 'test.sqlite3'), host='127.0.0.1', port=8766,
                    access_log=False)

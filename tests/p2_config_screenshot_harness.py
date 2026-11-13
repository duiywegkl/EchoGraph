"""Render the live config page offscreen without backend traffic or Qt close."""

import os
from pathlib import Path
import shutil
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_FONTDIR'] = 'C:/Windows/Fonts'

from PySide6.QtWidgets import QApplication

import run_ui
from src.ui.managers.window_manager import WindowManager


def main():
    output = Path(tempfile.gettempdir()) / 'echograph-p2-shots'
    output.mkdir(exist_ok=True)
    env_copy = output / '.env-copy'
    shutil.copy2(Path(run_ui.__file__).resolve().parent / '.env.example', env_copy)
    app = QApplication([])
    WindowManager.apply_theme(app, 'sand')
    run_ui.ConfigPage.refresh_connection_status = lambda self: None
    page = run_ui.ConfigPage(env_path=env_copy)
    page.resize(1100, 1050)
    page.show()
    app.processEvents()
    shot = output / 'config-page.png'
    if not page.grab().save(str(shot)):
        raise RuntimeError('screenshot save failed')
    print(shot, flush=True)
    os._exit(0)


if __name__ == '__main__':
    main()

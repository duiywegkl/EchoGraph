"""Offscreen graph-page geometry and screenshots with isolated data and no HTTP."""
import os
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(tempfile.gettempdir()) / 'echograph-p4d-shots'


def child(theme_name, mode, workdir):
    os.chdir(workdir)
    os.environ['ECHOGRAPH_DATA_ROOT'] = str(Path(workdir) / 'data')
    sys.path.insert(0, str(ROOT))
    import requests
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QHBoxLayout
    import run_ui
    from src.ui import theme

    def no_http(*_args, **_kwargs):
        raise AssertionError('HTTP request from graph screenshot harness')

    class NoNetworkManager:
        def get(self, *_args, **_kwargs):
            raise AssertionError('Qt network request from graph screenshot harness')

    requests.get = requests.post = no_http
    run_ui.QNetworkAccessManager = NoNetworkManager
    run_ui.GraphPage.refresh_graph = lambda self: None
    theme.set_theme(theme_name)
    app = QApplication([])
    app.setStyleSheet(theme.build_app_stylesheet())
    page = run_ui.GraphPage(object())
    page.resize(1400, 920)
    page.tavern_mode = mode == 'tavern'
    page.tavern_timeline_status.setText('已连接' if page.tavern_mode else '')
    page.skipped_edits_label.setText('')
    palette = theme.current()
    page.setObjectName('graphPageHarness')
    page.setStyleSheet(f"QWidget#graphPageHarness {{ background: {palette['BG_BASE']}; }}")
    page.graph_view.setHtml(f'''<!doctype html><meta charset="utf-8"><style>
        html,body{{margin:0;height:100%;background:{palette['BG_BASE']};color:{palette['TEXT_PRIMARY']};font:14px sans-serif}}
        .tools{{position:absolute;top:18px;left:18px;background:{palette['BG_SURFACE']};border:1px solid {palette['BORDER']};padding:10px}}
        .node{{position:absolute;top:42%;left:48%;padding:15px;border:2px solid {palette['ACCENT']};border-radius:50%}}
        </style><div class="tools">自动整理　适应窗口　编辑关系</div><div class="node">阿青</div>''')

    def pump():
        for _ in range(100):
            app.processEvents()
            time.sleep(.01)

    panel = page.layout().itemAt(0).widget().widget(0)
    layout = panel.layout()
    header = layout.itemAt(0).layout()
    for widget in (page.tavern_timeline_status, page.tavern_timeline_retry, page.skipped_edits_label):
        header.removeWidget(widget)
    old_status = QHBoxLayout()
    old_status.addWidget(page.tavern_timeline_status)
    old_status.addWidget(page.tavern_timeline_retry)
    old_status.addStretch()
    layout.insertLayout(1, old_status)
    layout.insertWidget(2, page.skipped_edits_label)
    layout.setStretchFactor(page.graph_view, 0)
    page.show()
    pump()
    before = SHOTS / f'{theme_name}-{mode}-before.png'
    assert page.grab().save(str(before))
    before_ratio = page.graph_view.height() / panel.height()

    layout.removeItem(old_status)
    layout.removeWidget(page.skipped_edits_label)
    for widget in (page.tavern_timeline_status, page.tavern_timeline_retry, page.skipped_edits_label):
        header.insertWidget(1, widget)
    layout.setStretchFactor(page.graph_view, 1)
    pump()
    after = SHOTS / f'{theme_name}-{mode}-after.png'
    assert page.grab().save(str(after))
    after_ratio = page.graph_view.height() / panel.height()
    print(f'{theme_name} {mode}: before={before_ratio:.3f}, after={after_ratio:.3f}, web={page.graph_view.height()}px', flush=True)
    assert after_ratio >= .80, (theme_name, mode, after_ratio)
    nodes = [{'id': name, 'name': name, 'type': kind} for name, kind in (
        ('阿青', 'character'), ('古城', 'location'), ('护符', 'item'), ('山谷', 'location'))]
    edges = [{'source': '阿青', 'target': '古城', 'relation': '看见'},
             {'source': '古城', 'target': '山谷', 'relation': '位于'},
             {'source': '阿青', 'target': '护符', 'relation': '持有'}]
    graph_file = Path(workdir) / 'small-graph.html'
    page.html_generator.generate_graph_html(json.dumps(nodes, ensure_ascii=False),
        json.dumps(edges, ensure_ascii=False), graph_file,
        json.dumps({'阿青': {'x': 0, 'y': 0}}))
    page.graph_view.load(QUrl.fromLocalFile(str(graph_file)))

    def js(source):
        result = []
        page.graph_view.page().runJavaScript(source, lambda value: result.append(value))
        until = time.monotonic() + 15
        while not result and time.monotonic() < until:
            app.processEvents()
            time.sleep(.02)
        assert result, 'JavaScript timeout'
        return result[0]

    until = time.monotonic() + 15
    while time.monotonic() < until:
        if js("window.lastLayoutMetrics?.kind === 'auto' && document.querySelectorAll('.node-group').length === 4"):
            break
        pump()
    else:
        raise AssertionError('Fresh small graph was not auto arranged')
    assert js("nodes.every((a,i) => nodes.slice(i+1).every(b => !boxesOverlap(labelBox(a),labelBox(b))))")
    assert js("links.every(d => !d.labelFits || [...document.querySelectorAll('.relation-label')].some(el => el.__data__ === d && nodes.every(n => {const b=labelBox(n), x=+el.getAttribute('x'), y=+el.getAttribute('y'), w=el.getBBox().width, h=el.getBBox().height; return !boxesOverlap(b,{left:x-w/2-3,right:x+w/2+3,top:y-h-3,bottom:y+3})})))")
    print(f'{theme_name} {mode}: sparse 4-node auto layout and edge-label clearance OK', flush=True)
    os._exit(0)  # Never close a live Qt WebEngine window normally.


def main():
    SHOTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='eg-p4d-page-') as root:
        for theme_name in ('sand', 'ink'):
            for mode in ('local', 'tavern'):
                workdir = Path(root) / theme_name / mode
                workdir.mkdir(parents=True)
                env = os.environ.copy()
                env.update(QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR='C:/Windows/Fonts',
                           QTWEBENGINE_DISABLE_SANDBOX='1',
                           QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu')
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child',
                                         theme_name, mode, str(workdir)], cwd=workdir, env=env,
                                        capture_output=True, text=True, timeout=45)
                print(result.stdout, end='')
                if result.returncode:
                    print(result.stderr[-4000:], file=sys.stderr)
                    raise SystemExit(result.returncode)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(*sys.argv[2:])
    else:
        main()

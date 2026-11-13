"""Real Qt WebEngine layout checks. No network service or repository data writes."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "data/tavern_characters/重生我要成为末世之王/sessions/current"
SHOTS = Path(tempfile.gettempdir()) / "echograph-layout-shots-v2"


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def real_graph(copy_dir):
    import networkx as nx
    graph = nx.read_graphml(copy_dir / "knowledge_graph.graphml")
    nodes = [{"id": key, "type": attrs.get("type", "concept"),
              "description": attrs.get("description", ""),
              "is_main_character": bool(attrs.get("is_main_character"))}
             for key, attrs in graph.nodes(data=True)]
    links = [{"source": a, "target": b, "relationship": attrs.get("relationship", "关联")}
             for a, b, attrs in graph.edges(data=True)]
    return payload(nodes, links)


def payload(nodes, links):
    return {"graph_data": {"nodes": nodes, "links": links},
            "graph_stats": {"nodes": len(nodes), "edges": len(links)}}


def hub_graph(count):
    kinds = ["character", "location", "item", "event", "concept"]
    stems = ["林间旅人", "北境旧城", "星纹护符", "秋夜庆典", "远古誓约", "密林传闻",
             "顾明月", "青石镇", "遗失的南方驿站", "风雪中的约定"]
    names = ["沈知远"] + [f"{stems[i % len(stems)]}{i}" for i in range(1, count)]
    nodes = [{"id": name, "type": kinds[i % len(kinds)], "is_main_character": i == 0}
             for i, name in enumerate(names)]
    pairs = set()
    hubs = [1, 2, 3, 4, 5]
    for i in range(1, min(count, 26)):
        pairs.add((0, i))
    for i in range(6, count):
        hub = hubs[(i - 6) % len(hubs)]
        pairs.add((hub, i))
        if i % 9 == 0:
            pairs.add((0, i))
    for a, b in zip(hubs, hubs[1:]):
        pairs.add((a, b))
    links = [{"source": names[a], "target": names[b], "relationship": "相识"}
             for a, b in sorted(pairs) if a != b]
    return payload(nodes, links)


METRICS = r"""(() => {
 const boxes = nodes.map(d => labelBox(d));
 let overlaps = 0;
 for (let i = 0; i < boxes.length; i++) for (let j = i+1; j < boxes.length; j++)
   if (boxesOverlap(boxes[i], boxes[j])) overlaps++;
 const left = Math.min(...boxes.map(b=>b.left)), right = Math.max(...boxes.map(b=>b.right));
 const top = Math.min(...boxes.map(b=>b.top)), bottom = Math.max(...boxes.map(b=>b.bottom));
 const area = boxes.reduce((s,b)=>s+(b.right-b.left)*(b.bottom-b.top),0);
 const viewport = document.querySelector('#graph').getBoundingClientRect();
 const screen = [...document.querySelectorAll('.node-group')].map(el=>el.getBoundingClientRect());
 const visible = screen.filter(b=>b.right>=viewport.left && b.left<=viewport.right &&
   b.bottom>=viewport.top && b.top<=viewport.bottom).length;
 const scale = d3.zoomTransform(svg.node()).k;
 const fontPx = parseFloat(getComputedStyle(document.querySelector('.node-label')).fontSize)*scale;
 return JSON.stringify({count:nodes.length, overlaps, density:((right-left)*(bottom-top)/area),
   scale, fontPx, visible:visible/nodes.length, ms:window.lastLayoutMetrics?.durationMs || 0,
   pinned:nodes.every(d=>d.fx===d.x&&d.fy===d.y),
   coords:Object.fromEntries(nodes.map(d=>[d.id,{x:d.x,y:d.y}]))});
})()"""


def child(theme, workdir):
    import requests
    from PySide6.QtWidgets import QMessageBox
    import run_ui

    workdir = Path(workdir)
    original_memory = run_ui.GRAGMemory
    original_conversations = run_ui.ConversationManager
    original_refresh = run_ui.GraphPage.refresh_graph
    run_ui.GRAGMemory = lambda *a, **kw: original_memory(*a, **{
        **kw, "graph_save_path": str(workdir / "local/knowledge_graph.graphml"),
        "entities_json_path": str(workdir / "local/entities.json")})
    run_ui.ConversationManager = lambda _root: original_conversations(workdir)
    run_ui.GraphPage.refresh_graph = lambda self: None
    run_ui.EchoGraphMainWindow.load_conversation_knowledge_graph = lambda self, _id: False
    run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, "api_server_process", None)
    QMessageBox.warning = lambda *_args: (_ for _ in ()).throw(AssertionError(_args[-1]))
    QMessageBox.critical = QMessageBox.warning
    requests.post = lambda *_args, **_kw: SimpleNamespace(ok=True, status_code=200, json=lambda: {})
    state = {"data": real_graph(workdir / "local")}

    def fake_get(url, **_kw):
        assert "127.0.0.1:9543" not in url, url
        graph = state["data"]
        if url.endswith("/stats"):
            return SimpleNamespace(status_code=200, json=lambda: {
                "graph_nodes": graph["graph_stats"]["nodes"],
                "graph_edges": graph["graph_stats"]["edges"]})
        if url.endswith("/export"):
            return SimpleNamespace(status_code=200, json=lambda: graph)
        return SimpleNamespace(status_code=200, ok=True, json=lambda: {"has_session": False})

    requests.get = fake_get
    env_path = workdir / ".env"
    env_path.write_text(f"UI_THEME={theme}\nAPI_SERVER_PORT=19543\nOPENAI_API_KEY=\n", encoding="utf-8")
    app, window = run_ui.create_app_and_window(env_path=env_path)
    run_ui.GraphPage.refresh_graph = original_refresh
    window.resize(1280, 900)
    window.tabs.setCurrentWidget(window.graph_page)
    page = window.graph_page
    page.graph_file_path = workdir / "graph.html"
    page.layout_storage_root = workdir / "data"
    sessions = page.layout_storage_root / "global"
    sessions.mkdir(parents=True, exist_ok=True)
    sessions.joinpath("active_sessions.json").write_text(json.dumps({
        "session-a": {"local_dir_name": "real"},
        "session-b": {"local_dir_name": "hub80"},
        "session-c": {"local_dir_name": "hub250"}}), encoding="utf-8")

    def pump(seconds=0.02):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(0.01)

    def js(code, timeout=25):
        result = []
        page.graph_view.page().runJavaScript(code, lambda value: result.append(value))
        end = time.monotonic() + timeout
        while not result and time.monotonic() < end:
            pump()
        assert result, f"JavaScript timeout: {code[:80]}"
        return result[0]

    def load(session, data):
        state["data"] = data
        page.enter_tavern_mode(session)
        assert page.refresh_from_api_server(session)
        end = time.monotonic() + 30
        while time.monotonic() < end:
            if js("typeof window.lastLayoutMetrics === 'object' && document.querySelectorAll('.node-group').length") == len(data["graph_data"]["nodes"]):
                break
            pump(0.1)
        else:
            raise AssertionError("Graph failed to initialize")
        pump(0.35)

    def metrics():
        return json.loads(js(METRICS))

    def shot(name):
        pump(0.25)
        path = SHOTS / f"{theme}-{name}.png"
        assert page.graph_view.grab().save(str(path))
        return path

    for key, session, data in (("a", "session-a", real_graph(workdir / "local")),
                               ("b", "session-b", hub_graph(80))):
        load(session, data)
        # Reproduce a previously saved, widely spread force layout as the before state.
        js("""(() => {
          simulation.stop(); nodes.forEach(d => {d.fx=null; d.fy=null});
          const old = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d=>d.id).distance(180))
            .force('charge', d3.forceManyBody().strength(-700))
            .force('center', d3.forceCenter(0,0)).stop();
          for (let i=0;i<100;i++) old.tick(); old.stop();
          separateLabels(); nodes.forEach(d=>{d.fx=d.x;d.fy=d.y});
          window.currentLayoutKind='before'; renderGraph(); fitGraphToView(); return true;
        })()""")
        baseline = metrics()
        assert baseline["fontPx"] >= 10.99
        print(f"{theme} {key} before: zoom={baseline['scale']:.3f} font={baseline['fontPx']:.2f}px "
              f"visible={baseline['visible']:.1%} shot={shot(key+'-before')}", flush=True)
        for kind in ("auto", "radial", "type"):
            js(f"arrangeGraph('{kind}'); true", timeout=30)
            m = metrics()
            assert m["count"] == len(data["graph_data"]["nodes"]) and m["pinned"]
            assert m["overlaps"] == 0 and m["fontPx"] >= 10.99, m
            print(f"{theme} {key} {kind}: overlaps={m['overlaps']} density={m['density']:.2f} "
                  f"zoom={m['scale']:.3f} font={m['fontPx']:.2f}px visible={m['visible']:.1%} "
                  f"ms={m['ms']} shot={shot(key+'-'+kind)}", flush=True)

    # Exercise interactions on the arranged 80-node graph.
    before = metrics()["coords"]
    js("fitGraphToView(); true")
    assert metrics()["coords"] == before
    edits = []
    page.edit_node_with_python_dialog = lambda *args: edits.append(args)
    js("document.querySelector('.node-group').dispatchEvent(new MouseEvent('click',{bubbles:true,detail:1})); true")
    pump(0.35)
    assert len(edits) == 1, edits
    js("(()=>{const n=document.querySelector('.node-group'); n.dispatchEvent(new MouseEvent('click',{bubbles:true,detail:1})); n.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,detail:2})); return true})()")
    pump(0.35)
    assert len(edits) == 2, edits
    js("(()=>{document.querySelector('#editModeBtn').click(); const n=document.querySelectorAll('.node-group'); n[0].dispatchEvent(new MouseEvent('click',{bubbles:true,detail:1})); n[2].dispatchEvent(new MouseEvent('click',{bubbles:true,detail:1})); return true})()")
    assert js("!!document.querySelector('.relation-dialog-overlay')")
    js("document.querySelector('.relation-dialog-overlay').remove(); document.querySelector('#editModeBtn').click(); true")
    print(f"{theme} click/dblclick/relation: OK", flush=True)

    drag = json.loads(js("(()=>{const el=document.querySelector('.node-group'), d=el.__data__; "
                         "const x=d.x+100,y=d.y-100; dragstarted.call(el,{active:0},d); "
                         "dragged.call(el,{x,y},d); dragended.call(el,{active:0,x,y},d); "
                         "return JSON.stringify({id:d.id,x:d.x,y:d.y,pinned:d.fx===d.x&&d.fy===d.y})})()"))
    assert drag["pinned"]
    pump(0.5)
    saved_path = page.layout_storage_root / "tavern_characters/hub80/sessions/current/layout.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved[drag["id"]] == {"x": drag["x"], "y": drag["y"]}
    print(f"{theme} drag pin/save: OK", flush=True)

    previous = metrics()["coords"]
    state["data"] = json.loads(json.dumps(state["data"], ensure_ascii=False))
    new_id = "新加入的远行者"
    state["data"]["graph_data"]["nodes"].append({"id": new_id, "type": "character"})
    neighbour = state["data"]["graph_data"]["nodes"][0]["id"]
    state["data"]["graph_data"]["links"].append({"source": new_id, "target": neighbour, "relationship": "相识"})
    state["data"]["graph_stats"] = {"nodes": 81, "edges": len(state["data"]["graph_data"]["links"])}
    assert page.refresh_from_api_server("session-b")
    end = time.monotonic() + 20
    while time.monotonic() < end and js("document.querySelectorAll('.node-group').length") != 81:
        pump(0.1)
    restored = metrics()
    assert restored["count"] == 81 and restored["overlaps"] == 0
    assert all(restored["coords"][key] == point for key, point in previous.items())
    near = ((restored["coords"][new_id]["x"] - previous[neighbour]["x"]) ** 2 +
            (restored["coords"][new_id]["y"] - previous[neighbour]["y"]) ** 2) ** 0.5
    assert near < 400, near
    print(f"{theme} refresh: positions exact, new neighbour distance={near:.1f}, overlaps=0", flush=True)

    if theme == "sand":
        load("session-c", hub_graph(250))
        for kind in ("auto", "radial", "type"):
            js(f"arrangeGraph('{kind}'); true", timeout=30)
            m = metrics()
            assert m["ms"] <= 1500, m
            print(f"sand c {kind}: ms={m['ms']}", flush=True)
    os._exit(0)


def main():
    SHOTS.mkdir(exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        try:
            child(sys.argv[2], sys.argv[3])
        except BaseException:
            traceback.print_exc()
            os._exit(1)
    before = {name: md5(SOURCE / name) for name in ("entities.json", "knowledge_graph.graphml")}
    with tempfile.TemporaryDirectory(prefix="eg-layout-v2-") as directory:
        for theme in ("sand", "ink"):
            workdir = Path(directory) / theme
            local = workdir / "local"
            local.mkdir(parents=True)
            for name in before:
                shutil.copyfile(SOURCE / name, local / name)
                assert md5(local / name) == before[name]
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QPA_FONTDIR="C:/Windows/Fonts",
                       QTWEBENGINE_DISABLE_SANDBOX="1", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu")
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", theme, str(workdir)],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
            print(result.stdout, end="")
            if result.returncode:
                print(result.stderr[-12000:], file=sys.stderr)
                raise SystemExit(result.returncode)
    after = {name: md5(SOURCE / name) for name in before}
    assert after == before
    print(f"real data MD5 unchanged: {after}", flush=True)


if __name__ == "__main__":
    main()

"""Contrast and palette contract for the desktop sand theme."""
import pytest

from src.ui import theme


@pytest.mark.parametrize("raw, expected", [
    ("UI_THEME='sand'\n", "sand"),
    ('UI_THEME="ink"\n', "ink"),
    ("UI_THEME=INK\n", "ink"),
    ("UI_THEME='  InK  '\n", "ink"),
    ("UI_THEME=unknown\n", "sand"),
    ("OTHER=value\n", "sand"),
])
def test_resolve_ui_theme_from_file(tmp_path, monkeypatch, raw, expected):
    monkeypatch.delenv("UI_THEME", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(raw, encoding="utf-8")
    assert theme.resolve_ui_theme(env_path) == expected


def test_resolve_ui_theme_missing_file_and_process_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("UI_THEME", raising=False)
    env_path = tmp_path / ".env"
    assert theme.resolve_ui_theme(env_path) == "sand"
    env_path.write_text("UI_THEME='sand'\n", encoding="utf-8")
    monkeypatch.setenv("UI_THEME", ' "INK" ')
    assert theme.resolve_ui_theme(env_path) == "ink"
    assert theme.resolve_ui_theme(env_path, process_value=None) == "sand"


def test_save_switch_decision_uses_active_name():
    try:
        theme.set_theme("sand")
        assert not theme.needs_switch("sand")
        assert theme.needs_switch("ink")
        theme.set_theme("ink")
        assert not theme.needs_switch("ink")
        assert theme.needs_switch("sand")
    finally:
        theme.set_theme("sand")


def luminance(color):
    rgb = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def blend(foreground, background, alpha):
    return "#" + "".join(f"{round(int(foreground[i:i+2], 16) * alpha + int(background[i:i+2], 16) * (1-alpha)):02X}" for i in (1, 3, 5))


def test_palette_contract():
    assert theme.PALETTES["sand"].keys() == theme.PALETTES["ink"].keys()
    assert theme.PALETTES["sand"]["NODE_TYPE_COLORS"].keys() == theme.PALETTES["ink"]["NODE_TYPE_COLORS"].keys()
    assert theme.get_theme("invalid") is theme.PALETTES["sand"]
    assert theme.set_theme("invalid") == "sand"
    assert theme.current() is theme.PALETTES["sand"]


def test_sand_contrast():
    p = theme.PALETTES["sand"]
    backgrounds = [p[k] for k in ("BG_BASE", "BG_SURFACE", "BG_RAISED", "BG_INPUT")]
    for key in ("TEXT_PRIMARY", "TEXT_SECONDARY", "DANGER", "SUCCESS", "INFO", "ACCENT_TEXT"):
        assert min(contrast(p[key], bg) for bg in backgrounds) >= 4.5, key
    assert min(contrast(p["TEXT_MUTED"], bg) for bg in backgrounds) >= 3
    for key in ("ACCENT_FILL", "ACCENT_HOVER", "ACCENT_PRESSED"):
        assert contrast(p["ON_ACCENT"], p[key]) >= 4.5, key
    for key, color in p["NODE_TYPE_COLORS"].items():
        assert contrast(color, p["BG_BASE"]) >= 3, key
    assert contrast(blend(p["TEXT_PRIMARY"], p["BG_BASE"], 0.7), p["BG_BASE"]) >= 3


def test_graph_templates_receive_active_variables(tmp_path):
    from src.ui.generators.graph_html_generator import GraphHTMLGenerator
    generator = GraphHTMLGenerator()
    template_path = generator.template_path
    try:
        for name in ("sand", "ink"):
            theme.set_theme(name)
            generator.template_path = template_path
            output = tmp_path / f"{name}.html"
            generator.generate_graph_html("[]", "[]", output)
            html = output.read_text(encoding="utf-8")
            assert f"--bg-base: {theme.current()['BG_BASE']};" in html
            assert "/*THEME_VARS*/" not in html
            generator.template_path = tmp_path / "missing-template.html"
            generator.generate_graph_html("[]", "[]", output)
            assert f"--character: {theme.node_type_colors()['character']};" in output.read_text(encoding="utf-8")
            generator._generate_fallback_html(output)
            assert f"--bg-base: {theme.current()['BG_BASE']};" in output.read_text(encoding="utf-8")
    finally:
        theme.set_theme("sand")


if __name__ == "__main__":
    p = theme.PALETTES["sand"]
    backgrounds = [p[k] for k in ("BG_BASE", "BG_SURFACE", "BG_RAISED", "BG_INPUT")]
    for key in ("TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED", "DANGER", "SUCCESS", "INFO", "ACCENT_TEXT"):
        print(f"{key:16} min backgrounds {min(contrast(p[key], bg) for bg in backgrounds):.2f}:1")
    for key in ("ACCENT_FILL", "ACCENT_HOVER", "ACCENT_PRESSED"):
        print(f"ON_ACCENT/{key:14} {contrast(p['ON_ACCENT'], p[key]):.2f}:1")
    for key, color in p["NODE_TYPE_COLORS"].items():
        print(f"node/{key:11} {contrast(color, p['BG_BASE']):.2f}:1")
    print(f"edge highlighted {contrast(blend(p['TEXT_PRIMARY'], p['BG_BASE'], 0.7), p['BG_BASE']):.2f}:1")

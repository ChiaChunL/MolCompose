from molcompose_mcp.console import CONSOLE_HTML, ConsoleHandler, build_proxy_url


def test_console_page_has_input_and_proxy_wiring():
    assert "MolCompose Console" in CONSOLE_HTML
    assert '"/run?"' in CONSOLE_HTML or "/run?" in CONSOLE_HTML
    assert "remotecontrol rest start" in CONSOLE_HTML


def test_proxy_url_encodes_command():
    url = build_proxy_url("http://127.0.0.1:3000/", "open 1brs")
    assert url == "http://127.0.0.1:3000/run?command=open+1brs"


def test_handler_defaults_to_local_bridge():
    assert ConsoleHandler.chimerax_url == "http://127.0.0.1:3000"

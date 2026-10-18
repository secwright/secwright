from secwright.tools import core_tools, truncate

tools = core_tools()


def call(sb, name, **args):
    return tools.call(sb, name, args)


def test_read_file_numbers_lines(sandbox):
    r = call(sandbox, "read_file", path="pkg/app.py", start_line=2, end_line=2)
    assert not r.is_error
    assert "2  " in r.content and "return 'hi ' + name" in r.content


def test_read_missing_file_is_a_tool_error(sandbox):
    r = call(sandbox, "read_file", path="nope.py")
    assert r.is_error and "cannot read" in r.content


def test_paths_outside_workdir_are_refused(sandbox):
    for p in ("/etc/passwd", "../outside.txt", "pkg/../../x"):
        r = call(sandbox, "read_file", path=p)
        assert r.is_error and "outside the project" in r.content, p


def test_edit_file_replaces_unique_match(sandbox):
    r = call(sandbox, "edit_file", path="pkg/app.py", old="return 'bye'", new="return 'goodbye'")
    assert not r.is_error, r.content
    assert "goodbye" in sandbox.read_file("/work/pkg/app.py").decode()


def test_edit_file_rejects_missing_and_ambiguous(sandbox):
    assert "not found" in call(sandbox, "edit_file", path="pkg/app.py", old="zzz", new="y").content
    r = call(sandbox, "edit_file", path="pkg/app.py", old="return", new="yield")
    assert r.is_error and "appears 2 times" in r.content


def test_create_file_refuses_to_overwrite(sandbox):
    assert not call(sandbox, "create_file", path="pkg/new.py", content="x = 1\n").is_error
    assert call(sandbox, "create_file", path="pkg/app.py", content="").is_error


def test_missing_argument_and_unknown_tool(sandbox):
    assert "missing required" in call(sandbox, "edit_file", path="pkg/app.py").content
    assert "unknown tool" in tools.call(sandbox, "rm_rf", {}).content


def test_submit_ends_episode(sandbox):
    assert call(sandbox, "submit", summary="done").ends_episode


def test_truncate_keeps_head_and_tail():
    t = truncate("a" * 5000 + "MIDDLE" + "z" * 5000, limit=1000)
    assert t.startswith("a") and t.endswith("z") and "omitted" in t and "MIDDLE" not in t

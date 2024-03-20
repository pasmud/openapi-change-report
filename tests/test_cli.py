import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


def cli(*args):
    return subprocess.run([sys.executable, "-m", "openapi_change_report", *args], cwd=PROJECT,
                          capture_output=True, text=True, check=False)


def test_json_report_and_exit_status(tmp_path):
    before = tmp_path / "before.yaml"
    before.write_text("openapi: 3.1.0\npaths: {/notes: {get: {responses: {'200': {description: OK}}}}}\n",
                      encoding="utf-8")
    after = tmp_path / "after.json"
    after.write_text('{"openapi":"3.1.0","paths":{}}', encoding="utf-8")
    args = (str(before), str(after), "--format", "json")
    result = cli(*args)
    assert (result.returncode, result.stderr) == (1, "")
    assert json.loads(result.stdout) == {
        "report_version": 1,
        "summary": {"breaking": 1, "review": 0, "non-breaking": 0},
        "changes": [{"severity": "breaking", "code": "operation.removed", "message": "Removed operation.",
                     "before": "/paths/~1notes/get", "after": None, "operation": "/paths/~1notes/get"}],
    }
    informational = cli(*args, "--fail-on", "never")
    assert (informational.returncode, informational.stdout) == (0, result.stdout)
    assert str(tmp_path) not in result.stdout


def test_review_threshold_and_unsupported_reference(tmp_path):
    doc = tmp_path / "fixture.yaml"
    doc.write_text("openapi: 3.1.0\npaths: {/notes: {$ref: 'missing-file.yaml#/Path'}}\n", encoding="utf-8")
    args = (str(doc), str(doc))
    default, strict = cli(*args), cli(*args, "--fail-on", "review")
    assert (default.returncode, strict.returncode) == (0, 1)
    assert default.stdout == strict.stdout
    assert "## Review" in strict.stdout
    assert "Path Item references are not compared." in strict.stdout


@pytest.mark.parametrize(("filename", "content", "message"), [
    ("missing.yaml", None, "No such file"),
    ("notes.json", '{"openapi":"3.1.0","openapi":"3.1.1"}', "duplicate mapping key"),
    ("notes.txt", "openapi: 3.1.0", "expected a .json, .yaml or .yml file"),
])
def test_input_failures_have_no_report(tmp_path, filename, content, message):
    path = tmp_path / filename
    if content is not None:
        path.write_text(content, encoding="utf-8")
    result = cli(str(path), str(path))
    assert (result.returncode, result.stdout) == (2, "")
    assert "before" in result.stderr and message in result.stderr and "Traceback" not in result.stderr


def test_structural_error_includes_pointer_and_never_is_not_an_error_override(tmp_path):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text('{"openapi":"3.1.0","paths":{}}', encoding="utf-8")
    after.write_text('{"openapi":"3.1.0","paths":{"/notes":{"get":{"responses":[]}}}}', encoding="utf-8")
    result = cli(str(before), str(after), "--fail-on", "never")
    assert (result.returncode, result.stdout) == (2, "")
    assert "/paths/~1notes/get/responses: expected an object" in result.stderr


def test_reports_are_stable_and_do_not_render_input_as_markup(tmp_path):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text('{"openapi":"3.1.0","paths":{}}', encoding="utf-8")
    names = ["/fake`<b>", "/z\n"]
    results = []
    for order in (names, reversed(names)):
        after.write_text(json.dumps({"openapi": "3.1.0", "paths": {name: {"get": {}} for name in order}}),
                         encoding="utf-8")
        result = cli(str(before), str(after))
        assert (result.returncode, result.stderr) == (0, "")
        results.append(result.stdout)
    assert results[0] == results[1]
    assert "`` /paths/~1fake`<b>/get ``" in results[0]
    assert r"/paths/~1z\n/get" in results[0]

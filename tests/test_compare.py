import json

import pytest

from openapi_change_report.compare import compare
from openapi_change_report.document import InputError, parse


def document(paths, **extra):
    return parse(json.dumps({"openapi": "3.1.0", "paths": paths, **extra}), json_input=True)


def test_operations_statuses_and_pointer_escaping():
    ok = {"responses": {"200": {"description": "OK"}}}
    before = document({"/notes/~draft": {"get": ok}, "/notes": {"get": ok, "delete": ok}})
    after = document({"/notes": {"get": {"responses": {"2XX": {}}}, "post": ok},
                      "/teams": {"get": ok}})
    assert [(c.severity, c.code, c.before, c.after) for c in compare(before, after)] == [
        ("breaking", "operation.removed", "/paths/~1notes/delete", None),
        ("breaking", "response.removed", "/paths/~1notes/get/responses/200", None),
        ("breaking", "operation.removed", "/paths/~1notes~1~0draft/get", None),
        ("non-breaking", "response.added", None, "/paths/~1notes/get/responses/2XX"),
        ("non-breaking", "operation.added", None, "/paths/~1notes/post"),
        ("non-breaking", "operation.added", None, "/paths/~1teams/get"),
    ]


def test_path_item_reference_does_not_produce_false_removals():
    before = document({"/notes": {"get": {}}})
    after = document({"/notes": {"$ref": "https://example.invalid/notes.yaml"}})
    assert [(c.severity, c.code) for c in compare(before, after)] == [("review", "path.reference")]


def test_yaml_uses_string_keys_for_words_and_matches_json():
    before = parse("""openapi: 3.1.0
paths:
  /notes:
    get:
      responses:
        '200': {description: on}
""")
    after = document({"/notes": {"get": {"responses": {"200": {"description": "on"}}}}})
    assert before.root == after.root
    assert compare(before, after) == []


@pytest.mark.parametrize(("text", "json_input", "match"), [
    ('{"openapi":"3.1.0","paths":{},"paths":{}}', True, "duplicate"),
    ("openapi: 3.1.0\npaths: {}\npaths: {}", False, "duplicate"),
    ("openapi: 3.1.0\npaths: {200: {}}", False, "must be a string"),
    ("openapi: 3.1.0\npaths: !!map {}", False, "explicit tags"),
    ("openapi: 3.1.0\npaths: &p {x-cycle: *p}", False, "aliases"),
    ("openapi: 3.2.0\npaths: {}", False, "/openapi"),
    ("openapi: 3.0.4", False, "/paths"),
])
def test_rejects_ambiguous_or_out_of_scope_documents(text, json_input, match):
    with pytest.raises(InputError, match=match):
        parse(text, json_input=json_input)


def test_response_validation_even_for_new_operations():
    after = document({"/notes": {"get": {"responses": {"ABC": {}}}}})
    with pytest.raises(InputError, match="/paths/~1notes/get/responses/ABC"):
        compare(document({}), after)

import pytest
from test_compare import document

from openapi_change_report.compare import compare

JSON = "application/json"
OP = "/paths/~1letters/post"


def with_schema(schema, direction):
    item = {"content": {JSON: {"schema": schema}}}
    operation = {"requestBody": item} if direction == "request" else {"responses": {"200": item}}
    return document({"/letters": {"post": operation}})


@pytest.mark.parametrize(("direction", "old", "new", "facet", "severity"), [
    ("request", {"type": "number"}, {"type": "integer"}, "type", "breaking"),
    ("request", {"type": "integer"}, {"type": "number"}, "type", "non-breaking"),
    ("response", {"type": "integer"}, {"type": "number"}, "type", "breaking"),
    ("response", {"type": "number"}, {"type": "integer"}, "type", "non-breaking"),
    ("request", {"enum": ["plain", "fancy"]}, {"enum": ["plain"]}, "enum", "breaking"),
    ("response", {"enum": ["plain"]}, {"enum": ["fancy", "plain"]}, "enum", "breaking"),
    ("request", {"enum": [True, 1]}, {"enum": [1]}, "enum", "breaking"),
    ("response", {"enum": ["plain"]}, {}, "enum", "breaking"),
    ("response", {"type": "string"}, {"type": "array"}, "type", "breaking"),
])
def test_directional_facets(direction, old, new, facet, severity):
    (change,) = compare(with_schema(old, direction), with_schema(new, direction))
    assert (change.code, change.severity, change.operation) == (f"schema.{direction}.{facet}", severity, OP)
    assert change.before.endswith(f"/application~1json/schema/{facet}")


def test_nested_schema_requiredness_and_array_items():
    def schema(required, item_type):
        return {"type": "array", "items": {"type": "object", "required": required,
                "properties": {"tags/~": {"type": "array", "items": {"type": item_type}}}}}

    old = schema([], "number")
    new = schema(["tags/~"], "integer")
    changes = compare(with_schema(old, "request"), with_schema(new, "request"))
    assert [(c.code, c.severity, c.after.split("/schema/")[1]) for c in changes] == [
        ("schema.request.type", "breaking", "items/properties/tags~1~0/items/type"),
        ("schema.request.required", "breaking", "items/required"),
    ]
    changes = compare(with_schema(new, "response"), with_schema(old, "response"))
    assert {c.severity for c in changes} == {"breaking"}
    assert {c.code for c in changes} == {"schema.response.required", "schema.response.type"}


def test_shared_local_schema_is_resolved_and_recursive_field_is_bounded():
    def make(data_type):
        paths = {"/letters": {"post": {"responses": {"200": {"$ref": "#/components/responses/Letter"}}}}}
        ref = {"$ref": "#/components/schemas/Letter"}
        return document(paths, components={
            "responses": {"Letter": {"content": {JSON: {"schema": ref}}}},
            "schemas": {"Letter": {"type": "object", "properties": {"stamp": {"type": data_type}, "next": ref}}},
        })

    breaking, incomplete = compare(make("string"), make("number"))
    assert breaking.after == "/components/schemas/Letter/properties/stamp/type"
    assert (incomplete.severity, incomplete.after) == ("review", "/components/schemas/Letter/properties/next")
    assert "Recursive" in incomplete.message


@pytest.mark.parametrize("unsupported", [
    {"oneOf": [{"type": "string"}]}, {"type": ["string", "null"]}, {"additionalProperties": False},
    {"type": "string", "format": "date-time"}, {"$ref": "https://example.invalid/schema.json"},
    {"$ref": "#/components/schemas/Fake", "type": "string"}, True,
])
def test_unsupported_subtree_emits_review_instead_of_a_false_type_change(unsupported):
    (change,) = compare(with_schema({"type": "integer"}, "request"), with_schema(unsupported, "request"))
    assert (change.code, change.severity) == ("schema.request.unsupported", "review")


def test_status_and_media_removed_without_guessing_wildcard_equivalence():
    before = document({"/letters": {"post": {"requestBody": {"content": {JSON: {}, "text/plain": {}}},
                                             "responses": {"200": {"content": {JSON: {}}}, "201": {}}}}})
    after = document({"/letters": {"post": {"requestBody": {"content": {JSON: {}, "text/*": {}}},
                                            "responses": {"200": {}, "2XX": {}}}}})
    assert {(c.code, c.severity) for c in compare(before, after)} == {
        ("media.request.removed", "breaking"), ("media.response.removed", "breaking"),
        ("media.request.added", "non-breaking"), ("response.removed", "breaking"),
        ("response.added", "non-breaking"),
    }


def test_read_only_property_requiredness_does_not_imply_required_input():
    old = {"type": "object", "properties": {"stamp": {"type": "string", "readOnly": True}}}
    new = {**old, "required": ["stamp"]}
    changes = compare(with_schema(old, "request"), with_schema(new, "request"))
    assert {c.severity for c in changes} == {"review"}
    assert {c.code for c in changes} == {"schema.request.required", "schema.request.unsupported"}


def test_parameter_schemas_use_request_rules_and_enum_order_is_ignored():
    def make(enum):
        params = [{"name": "color", "in": "query", "schema": {"type": "string", "enum": enum}}]
        return document({"/letters": {"get": {"parameters": params}}})

    assert compare(make(["red", "blue"]), make(["blue", "red"])) == []
    (change,) = compare(make(["red", "blue"]), make(["red"]))
    assert (change.severity, change.after) == ("breaking", "/paths/~1letters/get/parameters/0/schema/enum")

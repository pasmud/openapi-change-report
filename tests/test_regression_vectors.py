import json
from pathlib import Path

import pytest

from openapi_change_report.compare import compare
from openapi_change_report.document import parse

VECTORS = Path(__file__).with_name("regression_vectors")
FIELDS = ("severity", "code", "before", "after", "operation")


@pytest.mark.parametrize(
    "path", sorted(VECTORS.glob("*.json")), ids=lambda path: path.stem
)
def test_regression_vector(path):
    vector = json.loads(path.read_text(encoding="utf-8"))
    before = parse(json.dumps(vector["before"]), json_input=True)
    after = parse(json.dumps(vector["after"]), json_input=True)

    actual = [
        {field: getattr(change, field) for field in FIELDS}
        for change in compare(before, after)
    ]
    assert actual == vector["expected"], vector["title"]

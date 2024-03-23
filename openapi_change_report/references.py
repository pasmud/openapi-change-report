"""Resolve only named, same-document OpenAPI component references."""

import re
from dataclasses import dataclass

from .document import Document, mapping, pointer

COMPONENT = re.compile(r"#/components/([A-Za-z]+)/([A-Za-z0-9._-]+)")
ANNOTATIONS = frozenset({"title", "description", "$comment", "default", "example", "examples",
                         "deprecated", "externalDocs"})


class UnresolvedReference(ValueError):
    """A reference or schema falls outside the comparison policy."""

    def __init__(self, message: str, at: str):
        super().__init__(message)
        self.at = at


@dataclass(frozen=True)
class Located:
    value: dict
    at: str


def resolve(doc: Document, obj: Located, kind: str) -> Located:
    seen = set()
    while "$ref" in obj.value:
        if kind == "schemas" and any(key != "$ref" and key not in ANNOTATIONS and not key.startswith("x-")
                                      for key in obj.value):
            raise UnresolvedReference("Schema references with non-annotation siblings are not compared.", obj.at)
        ref_at = pointer(obj.at, "$ref")
        ref = obj.value["$ref"]
        match = COMPONENT.fullmatch(ref) if isinstance(ref, str) else None
        if not match or match[1] != kind:
            raise UnresolvedReference(f"Only same-document #/components/{kind}/NAME refs are supported.", ref_at)
        if ref in seen:
            raise UnresolvedReference("Component reference chain is cyclic.", ref_at)
        seen.add(ref)
        components = mapping(doc.root.get("components", {}), "/components")
        group = mapping(components.get(kind, {}), pointer("/components", kind))
        name = match[2]
        if name not in group:
            raise UnresolvedReference("Local component target does not exist.", ref_at)
        at = pointer("/components", kind, name)
        if kind == "schemas" and isinstance(group[name], bool):
            raise UnresolvedReference("Boolean schemas are not compared.", at)
        obj = Located(mapping(group[name], at), at)
    return obj

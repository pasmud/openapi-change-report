"""Resolve only named, same-document OpenAPI component references."""

import re
from dataclasses import dataclass

from .document import Document, mapping, pointer

COMPONENT = re.compile(r"#/components/([A-Za-z]+)/([A-Za-z0-9._-]+)")


class UnresolvedReference(ValueError):
    """A reference falls outside the offline resolution policy."""


@dataclass(frozen=True)
class Located:
    value: dict
    at: str


def resolve(doc: Document, obj: Located, kind: str) -> Located:
    seen = set()
    while "$ref" in obj.value:
        ref = obj.value["$ref"]
        match = COMPONENT.fullmatch(ref) if isinstance(ref, str) else None
        if not match or match[1] != kind:
            raise UnresolvedReference(f"Only same-document #/components/{kind}/NAME refs are supported.")
        if ref in seen:
            raise UnresolvedReference("Component reference chain is cyclic.")
        seen.add(ref)
        components = mapping(doc.root.get("components", {}), "/components")
        group = mapping(components.get(kind, {}), pointer("/components", kind))
        name = match[2]
        if name not in group:
            raise UnresolvedReference("Local component target does not exist.")
        at = pointer("/components", kind, name)
        obj = Located(mapping(group[name], at), at)
    return obj

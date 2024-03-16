"""Load a local JSON or YAML document without following references."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar

import yaml


class InputError(ValueError):
    """An input cannot be safely interpreted by the reviewer."""


def pointer(base: str, *tokens: str) -> str:
    return base + "".join("/" + token.replace("~", "~0").replace("/", "~1") for token in tokens)


def mapping(value, at: str) -> dict:
    if not isinstance(value, dict):
        raise InputError(f"{at or '<root>'}: expected an object")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise InputError(f"mapping key {key!r} must be a string (quote numeric YAML keys)")
        if key in result:
            raise InputError(f"duplicate mapping key {key!r}")
        result[key] = value
    return result


def finite_decimal(text):
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise InputError(f"invalid number {text!r}") from exc
    if not value.is_finite():
        raise InputError(f"non-finite number {text!r}")
    return value


class OpenAPILoader(yaml.SafeLoader):
    # Do not inherit YAML 1.1 rules such as `on` -> true or dates -> datetime.
    yaml_implicit_resolvers: ClassVar[dict] = {}

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "tag", None) is not None:
            raise InputError("YAML aliases and explicit tags are not supported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        return unique_object(self.construct_pairs(node, deep=deep))


for kind, pattern, initials in (
    ("null", r"^(?:null|~|)$", ["n", "~", ""]),
    ("bool", r"^(?:true|false)$", ["t", "f"]),
    ("int", r"^-?(?:0|[1-9][0-9]*)$", list("-0123456789")),
    ("float", r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)$",
     list("-0123456789")),
):
    OpenAPILoader.add_implicit_resolver(f"tag:yaml.org,2002:{kind}", re.compile(pattern), initials)

OpenAPILoader.add_constructor("tag:yaml.org,2002:float", lambda loader, node: finite_decimal(node.value))


@dataclass(frozen=True)
class Document:
    version: str
    root: dict
    paths: dict


def parse(text: str, *, json_input: bool = False) -> Document:
    """Read one OpenAPI 3.0.x or 3.1.x document; this is not a spec validator."""
    try:
        if json_input:
            data = json.loads(text, object_pairs_hook=unique_object, parse_float=finite_decimal,
                              parse_constant=finite_decimal)
        else:
            data = yaml.load(text, Loader=OpenAPILoader)
        root = mapping(data, "")
        version = root.get("openapi")
        if not isinstance(version, str) or not re.fullmatch(r"3\.[01]\.[0-9]+", version):
            raise InputError("/openapi: expected an OpenAPI 3.0.x or 3.1.x version string")
        paths = root.get("paths", {} if version.startswith("3.1.") else None)
        return Document(version, root, mapping(paths, "/paths"))
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        if isinstance(exc, InputError):
            raise
        if isinstance(exc, RecursionError):
            raise InputError("document nesting is too deep") from exc
        raise InputError(str(exc)) from exc


def load(path: Path) -> Document:
    suffix = path.suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        raise InputError("expected a .json, .yaml or .yml file")
    try:
        return parse(path.read_text(encoding="utf-8-sig"), json_input=suffix == ".json")
    except (OSError, UnicodeError) as exc:
        raise InputError(str(exc)) from exc

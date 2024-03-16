"""Directional rules for a small, explicit Schema Object subset."""

from dataclasses import dataclass, field
from decimal import Decimal

from .changes import Change
from .document import Document, InputError, mapping, pointer
from .references import ANNOTATIONS, Located, UnresolvedReference, resolve

TYPES = frozenset({"null", "boolean", "object", "array", "number", "integer", "string"})
KEYWORDS = frozenset({"type", "enum", "properties", "required", "items"})
OAS_DIALECT = "https://spec.openapis.org/oas/3.1/dialect/base"
MAX_DEPTH = 40


def resolve_schema(doc: Document, raw, at: str) -> Located:
    if doc.version.startswith("3.1.") and doc.root.get("jsonSchemaDialect", OAS_DIALECT) != OAS_DIALECT:
        raise UnresolvedReference("Custom OpenAPI schema dialects are not compared.")
    if isinstance(raw, bool):
        raise UnresolvedReference("Boolean schemas are not compared.")
    obj = resolve(doc, Located(mapping(raw, at), at), "schemas")
    unsupported = [key for key, value in obj.value.items()
                   if key not in KEYWORDS and key not in ANNOTATIONS and not key.startswith("x-")
                   and not (key == "additionalProperties" and value is True)
                   and not (key in {"nullable", "readOnly", "writeOnly"} and value is False)]
    if unsupported:
        raise UnresolvedReference("Unsupported schema keywords: " + ", ".join(map(repr, sorted(unsupported))) + ".")
    schema_type = obj.value.get("type", "")
    if "type" in obj.value and (not isinstance(schema_type, str) or schema_type not in TYPES
                                or (schema_type == "null" and doc.version.startswith("3.0."))):
        raise UnresolvedReference("Only a single supported schema type is compared.")
    if isinstance(obj.value.get("items"), list):
        raise UnresolvedReference("Tuple schemas are not compared.")
    return obj


def enum_values(obj: Located):
    if "enum" not in obj.value:
        return None
    at = pointer(obj.at, "enum")
    values = obj.value["enum"]
    if not isinstance(values, list) or not values:
        raise InputError(f"{at}: expected a non-empty array")
    if any(isinstance(value, (dict, list)) for value in values):
        raise UnresolvedReference("Only scalar enum members are compared.")
    # JSON booleans are distinct from numbers; integer and decimal spellings of a number are not.
    return {("number" if type(value) in (int, Decimal) else type(value).__name__, value) for value in values}


def required_properties(obj: Located) -> set[str]:
    names = obj.value.get("required", [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise InputError(f"{pointer(obj.at, 'required')}: expected an array of strings")
    if len(names) != len(set(names)):
        raise InputError(f"{pointer(obj.at, 'required')}: duplicate property name")
    return set(names)


def type_subset(sub: str | None, sup: str | None) -> bool:
    return sup is None or sub == sup or (sub == "integer" and sup == "number")


def enum_subset(sub: set | None, sup: set | None) -> bool:
    return sup is None or (sub is not None and sub <= sup)


def field_pointer(obj: Located, field_name: str) -> str:
    return pointer(obj.at, field_name) if field_name in obj.value else obj.at


def uncertain_property(value) -> bool:
    # Requiredness and presence may be direction-specific via these annotations.
    return (not isinstance(value, dict) or "$ref" in value or value.get("readOnly") is True
            or value.get("writeOnly") is True)


@dataclass
class SchemaDiff:
    before: Document
    after: Document
    direction: str
    changes: list[Change] = field(default_factory=list)
    active: set[tuple[str, str]] = field(default_factory=set)
    visited: set[tuple[str, str]] = field(default_factory=set)

    def add(self, severity, rule, message, old_at, new_at):
        self.changes.append(Change(severity, f"schema.{self.direction}.{rule}", message, old_at, new_at))

    def visit(self, old_raw, new_raw, old_at, new_at):
        if len(self.active) >= MAX_DEPTH:
            self.add("review", "unsupported", "Schema comparison depth limit reached.", old_at, new_at)
            return
        try:
            old = resolve_schema(self.before, old_raw, old_at)
            new = resolve_schema(self.after, new_raw, new_at)
            old_enum, new_enum = enum_values(old), enum_values(new)
        except UnresolvedReference as exc:
            self.add("review", "unsupported", str(exc), old_at, new_at)
            return

        pair = (old.at, new.at)
        if pair in self.active:
            self.add("review", "unsupported", "Recursive schema references are not expanded.", old_at, new_at)
        elif pair not in self.visited:
            self.active.add(pair)
            self.facets(old, new, old_enum, new_enum)
            self.active.remove(pair)
            self.visited.add(pair)

    def facets(self, old, new, old_enum, new_enum):
        request = self.direction == "request"
        old_type, new_type = old.value.get("type"), new.value.get("type")
        if old_type != new_type:
            compatible = type_subset(old_type, new_type) if request else type_subset(new_type, old_type)
            self.add("non-breaking" if compatible else "breaking", "type",
                     f"Type changed from {old_type or 'any'} to {new_type or 'any'}.",
                     field_pointer(old, "type"), field_pointer(new, "type"))
        if old_enum != new_enum:
            compatible = enum_subset(old_enum, new_enum) if request else enum_subset(new_enum, old_enum)
            if compatible:
                message = "Enum values changed in a compatible direction."
            elif request:
                message = "Enum values changed; previously documented inputs may be rejected."
            else:
                message = "Enum values changed; clients may receive new values."
            self.add("non-breaking" if compatible else "breaking", "enum", message,
                     field_pointer(old, "enum"), field_pointer(new, "enum"))

        self.properties(old, new)
        if "items" in old.value or "items" in new.value:
            self.visit(old.value.get("items", {}), new.value.get("items", {}),
                       field_pointer(old, "items"), field_pointer(new, "items"))

    def properties(self, old, new):
        old_props = mapping(old.value.get("properties", {}), pointer(old.at, "properties"))
        new_props = mapping(new.value.get("properties", {}), pointer(new.at, "properties"))
        old_required, new_required = required_properties(old), required_properties(new)
        request = self.direction == "request"
        required_changes = old_required ^ new_required
        for name in sorted(required_changes):
            values = (old_props.get(name, {}), new_props.get(name, {}))
            old_at, new_at = field_pointer(old, "required"), field_pointer(new, "required")
            added = name in new_required
            # A readOnly/writeOnly declaration can change which direction `required` applies to.
            # Do not classify requiredness if that information may be behind a reference.
            if any(uncertain_property(value) for value in values):
                self.add("review", "required", f"Cannot classify requiredness change for property {name!r}.",
                         old_at, new_at)
            else:
                self.add("breaking" if added == request else "non-breaking", "required",
                         f"Property {name!r} is {'now' if added else 'no longer'} required.", old_at, new_at)

        for name in sorted(old_props.keys() | new_props.keys()):
            old_at = pointer(old.at, "properties", name) if name in old_props else None
            new_at = pointer(new.at, "properties", name) if name in new_props else None
            if not old_at or not new_at:
                if name not in required_changes:
                    if request or uncertain_property(old_props.get(name, new_props.get(name))):
                        severity = "review"
                    else:
                        severity = "non-breaking" if new_at else "breaking"
                    self.add(severity, "property", f"{'Added' if new_at else 'Removed'} property {name!r}.",
                             old_at, new_at)
                continue
            self.visit(old_props[name], new_props[name], old_at, new_at)


def schema_changes(before: Document, after: Document, old: Located, new: Located,
                   direction: str) -> list[Change]:
    if "schema" not in old.value and "schema" not in new.value:
        return []
    old_at, new_at = field_pointer(old, "schema"), field_pointer(new, "schema")
    if ("schema" in old.value) != ("schema" in new.value):
        return [Change("review", f"schema.{direction}.presence", "Explicit schema added or removed.", old_at, new_at)]
    diff = SchemaDiff(before, after, direction)
    diff.visit(old.value["schema"], new.value["schema"], old_at, new_at)
    return diff.changes

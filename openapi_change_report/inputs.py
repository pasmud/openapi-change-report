"""Compute effective parameter and request body requirements."""

from .changes import Change
from .document import Document, InputError, mapping, pointer
from .references import Located, UnresolvedReference, resolve


def required(obj: Located) -> bool:
    value = obj.value.get("required", False)
    if not isinstance(value, bool):
        raise InputError(f"{pointer(obj.at, 'required')}: expected a boolean")
    return value


def effective_parameters(doc: Document, path: Located, operation: Located):
    effective = {}
    issues = {}
    for owner in (path, operation):
        at = pointer(owner.at, "parameters")
        entries = owner.value.get("parameters", [])
        if not isinstance(entries, list):
            raise InputError(f"{at}: expected an array")
        level = {}
        for index, entry in enumerate(entries):
            slot = pointer(at, str(index))
            try:
                obj = resolve(doc, Located(mapping(entry, slot), slot), "parameters")
            except UnresolvedReference as exc:
                issues[slot] = str(exc)
                continue
            name, where = obj.value.get("name"), obj.value.get("in")
            if not isinstance(name, str) or not name:
                raise InputError(f"{pointer(obj.at, 'name')}: expected a non-empty string")
            if where not in ("path", "query", "header", "cookie"):
                raise InputError(f"{pointer(obj.at, 'in')}: expected path, query, header or cookie")
            if where == "header" and name.lower() in {"accept", "content-type", "authorization"}:
                continue  # OpenAPI explicitly ignores these Parameter Objects.
            is_required = required(obj)
            if where == "path" and not is_required:
                raise InputError(f"{pointer(obj.at, 'required')}: path parameters must be required")
            key = (where, name)
            if key in level:
                raise InputError(f"{slot}: duplicate parameter {name!r} in {where}")
            level[key] = obj
        effective.update(level)  # An operation may override, but not remove, a path parameter.
    return effective, issues


def parameter_changes(old: dict, new: dict) -> list[Change]:
    changes = []
    for where, name in sorted(old.keys() | new.keys()):
        previous, current = old.get((where, name)), new.get((where, name))
        label = f"{where} parameter {name!r}"
        if current is None:
            changes.append(Change("review", "parameter.removed", f"Removed {label}.", before=previous.at))
        elif required(current) and (previous is None or not required(previous)):
            before = None
            if previous is not None:
                before = pointer(previous.at, "required") if "required" in previous.value else previous.at
            changes.append(Change("breaking", "parameter.required", f"Now requires {label}.",
                                  before, pointer(current.at, "required")))
        elif previous is None:
            changes.append(Change("non-breaking", "parameter.added", f"Added optional {label}.", after=current.at))
        elif required(previous) and not required(current):
            after = pointer(current.at, "required") if "required" in current.value else current.at
            changes.append(Change("non-breaking", "parameter.optional", f"Made {label} optional.",
                                  pointer(previous.at, "required"), after))
    return changes


def body(doc: Document, operation: Located) -> Located | None:
    if "requestBody" not in operation.value:
        return None
    at = pointer(operation.at, "requestBody")
    obj = resolve(doc, Located(mapping(operation.value["requestBody"], at), at), "requestBodies")
    required(obj)
    return obj


def body_changes(old: Located | None, new: Located | None) -> list[Change]:
    if new is None:
        return [Change("review", "body.removed", "Removed request body.", before=old.at)] if old else []
    if required(new) and (old is None or not required(old)):
        before = (pointer(old.at, "required") if "required" in old.value else old.at) if old else None
        return [Change("breaking", "body.required", "Now requires a request body.",
                       before, pointer(new.at, "required"))]
    if old is None:
        return [Change("non-breaking", "body.added", "Added an optional request body.", after=new.at)]
    if required(old) and not required(new):
        after = pointer(new.at, "required") if "required" in new.value else new.at
        return [Change("non-breaking", "body.optional", "Made the request body optional.",
                       pointer(old.at, "required"), after)]
    return []


def paired_bodies(before: Document, after: Document, old: Located, new: Located):
    sides = []
    issues = []
    for doc, operation in ((before, old), (after, new)):
        try:
            sides.append(body(doc, operation))
        except UnresolvedReference as exc:
            issues.append(str(exc))
            sides.append(None)
    if issues:
        def location(operation):
            return pointer(operation.at, "requestBody") if "requestBody" in operation.value else None

        return None, None, [Change("review", "body.reference", " ".join(sorted(set(issues))),
                                   location(old), location(new))]
    previous, current = sides
    return previous, current, body_changes(previous, current)

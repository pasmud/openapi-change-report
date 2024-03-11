"""Collect changes on the HTTP operation surface."""

import re
from dataclasses import replace

from .changes import Change, sort_changes
from .document import Document, InputError, mapping, pointer
from .inputs import effective_parameters, paired_bodies, parameter_changes
from .references import Located

HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
STATUS = re.compile(r"(?:[1-5](?:[0-9]{2}|XX)|default)")


def path_items(doc: Document) -> dict:
    items = {}
    for name, item in doc.paths.items():
        if name.startswith("x-"):
            continue
        at = pointer("/paths", name)
        if not name.startswith("/"):
            raise InputError(f"{at}: path keys must start with '/'")
        items[name] = mapping(item, at)
    return items


def operations(doc: Document, item: dict, at: str) -> dict:
    result = {}
    for method in sorted(HTTP_METHODS & item.keys()):
        location = pointer(at, method)
        operation = mapping(item[method], location)
        responses_at = pointer(location, "responses")
        responses = mapping(operation.get("responses", {} if doc.version.startswith("3.1.")
                                          else None), responses_at)
        for status, response in responses.items():
            if status.startswith("x-"):
                continue
            status_at = pointer(responses_at, status)
            if not STATUS.fullmatch(status):
                raise InputError(f"{status_at}: invalid response status key")
            mapping(response, status_at)
        result[method] = operation
    return result


def response_changes(old: dict, new: dict, at: str) -> list[Change]:
    old_statuses = {key for key in old.get("responses", {}) if not key.startswith("x-")}
    new_statuses = {key for key in new.get("responses", {}) if not key.startswith("x-")}
    return [
        Change("breaking", "response.removed", f"Removed documented response {status}.",
               before=pointer(at, "responses", status))
        for status in old_statuses - new_statuses
    ] + [
        Change("non-breaking", "response.added", f"Added documented response {status}.",
               after=pointer(at, "responses", status))
        for status in new_statuses - old_statuses
    ]


def input_changes(before: Document, after: Document, old_path: Located, new_path: Located,
                  old: Located, new: Located) -> list[Change]:
    old_params, old_issues = effective_parameters(before, old_path, old)
    new_params, new_issues = effective_parameters(after, new_path, new)
    if old_issues or new_issues:
        changes = []
        for at in sorted(old_issues.keys() | new_issues.keys()):
            messages = {issue[at] for issue in (old_issues, new_issues) if at in issue}
            changes.append(Change("review", "parameter.reference", "Parameter comparison skipped. "
                                  + " ".join(sorted(messages)),
                                  at if at in old_issues else None, at if at in new_issues else None))
    else:
        changes = parameter_changes(old_params, new_params)
    _, _, body_findings = paired_bodies(before, after, old, new)
    return changes + body_findings


def compare(before: Document, after: Document) -> list[Change]:
    """Return changes in severity and location order, independent of input key order."""
    changes = []
    old_paths, new_paths = path_items(before), path_items(after)
    for path in sorted(old_paths.keys() | new_paths.keys()):
        at = pointer("/paths", path)
        old_item, new_item = old_paths.get(path, {}), new_paths.get(path, {})
        if "$ref" in old_item or "$ref" in new_item:
            changes.append(Change("review", "path.reference", "Path Item references are not compared.",
                                  at if path in old_paths else None, at if path in new_paths else None))
            continue
        old_ops = operations(before, old_item, at)
        new_ops = operations(after, new_item, at)
        for method in old_ops.keys() | new_ops.keys():
            location = pointer(at, method)
            if method not in new_ops:
                changes.append(Change("breaking", "operation.removed", "Removed operation.", before=location))
            elif method not in old_ops:
                changes.append(Change("non-breaking", "operation.added", "Added operation.", after=location))
            else:
                changes.extend(response_changes(old_ops[method], new_ops[method], location))
                findings = input_changes(before, after, Located(old_item, at), Located(new_item, at),
                                         Located(old_ops[method], location), Located(new_ops[method], location))
                changes.extend(replace(change, operation=location) for change in findings)
    return sort_changes(changes)

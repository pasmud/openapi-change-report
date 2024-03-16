"""Match request and response representations by literal media type key."""

from .changes import Change
from .document import Document, mapping, pointer
from .references import Located, UnresolvedReference, resolve
from .schemas import schema_changes


def content_changes(before: Document, after: Document, old: Located, new: Located,
                    direction: str) -> list[Change]:
    old_base, new_base = pointer(old.at, "content"), pointer(new.at, "content")
    old_types = mapping(old.value.get("content", {}), old_base)
    new_types = mapping(new.value.get("content", {}), new_base)
    changes = []
    for media in sorted(old_types.keys() | new_types.keys()):
        old_at, new_at = pointer(old_base, media), pointer(new_base, media)
        if media not in new_types:
            changes.append(Change("breaking", f"media.{direction}.removed", f"Removed media type {media!r}.",
                                  before=old_at))
        elif media not in old_types:
            severity = "non-breaking" if direction == "request" else "review"
            changes.append(Change(severity, f"media.{direction}.added", f"Added media type {media!r}.",
                                  after=new_at))
        else:
            changes.extend(schema_changes(before, after, Located(mapping(old_types[media], old_at), old_at),
                                          Located(mapping(new_types[media], new_at), new_at), direction))
    return changes


def response_content_changes(before: Document, after: Document, old: Located, new: Located) -> list[Change]:
    changes = []
    old_statuses, new_statuses = old.value.get("responses", {}), new.value.get("responses", {})
    for status in sorted(old_statuses.keys() & new_statuses.keys()):
        if status.startswith("x-"):
            continue
        old_at, new_at = pointer(old.at, "responses", status), pointer(new.at, "responses", status)
        try:
            old_response = resolve(before, Located(old_statuses[status], old_at), "responses")
            new_response = resolve(after, Located(new_statuses[status], new_at), "responses")
        except UnresolvedReference as exc:
            changes.append(Change("review", "response.reference", str(exc), old_at, new_at))
        else:
            changes.extend(content_changes(before, after, old_response, new_response, "response"))
    return changes

# openapi-change-report

Compare a baseline and a candidate OpenAPI 3 spec before changing a documented HTTP API. The CLI reads two local files and writes a Markdown or JSON report. It never contacts the API, runs requests, or fetches references.

## Quick start

Python 3.11+ is required. From the checkout:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install .
openapi-change-report examples/parcel-labels.before.yaml examples/parcel-labels.after.json
openapi-change-report examples/parcel-labels.before.yaml examples/parcel-labels.after.json --format json --fail-on never
```

Both specs describe a fictional parcel-label API. The comparison reports **6 breaking, 1 review, and 1 non-breaking** finding. The six breaking findings cover the new required header and body, a narrower input enum, a response field that is no longer guaranteed, and a removed status and operation. An unchanged `oneOf` still requires review because the tool does not compare composition. The new formats endpoint is non-breaking. The first command that compares specs exits `1` by default; the second emits the same findings in JSON and exits `0`.

## CLI contract

```text
openapi-change-report BEFORE AFTER [--format markdown|json] [--fail-on breaking|review|any|never]
```

- **Inputs:** One UTF-8 document per file, with an optional BOM. The `.json`, `.yaml`, or `.yml` extension selects the parser; files may use different formats. Supported version strings are `3.0.x` and `3.1.x`. JSON and YAML reject duplicate mapping keys and non-string keys. Quote numeric YAML keys such as `'200'`. YAML uses decimal JSON-style numbers, lowercase `true`/`false`/`null`, and accepts `~` and empty values as null. Explicit tags and aliases (including alias-based merges) are unsupported.
- **Output:** Markdown by default. JSON has `report_version: 1`, a `summary` count for each severity, and a `changes` array. Each record has `severity`, `code`, `message`, `before`, `after`, and `operation`. Reports omit timestamps and source filenames and sort by severity, location (after or before), rule code, and tie-breakers. Object-key order does not affect output; changing a parameter's array index changes its location.
- **Locations:** `before`/`after` are [RFC 6901 JSON Pointers](https://www.rfc-editor.org/rfc/rfc6901) into the respective files (`null` means no corresponding node). A missing keyword whose default is relevant points to its containing object. Pointers to resolved components identify the definition, and `operation` identifies the affected endpoint even when the finding comes from a shared definition. For example, `/paths/~1labels/post/parameters/0/required` addresses the fake header requirement. Use JSON for exact pointer text.
- **Exit codes:** `0` means no findings met the threshold; `1` means at least one did, with the report still on stdout. The default `breaking` threshold fails only on breaking findings. `review` fails on breaking or review. Use `any` during a contract freeze to flag even non-breaking findings, such as a new operation. `never` disables finding-based failures. `2` indicates usage, file, parse, or checked structural errors regardless of threshold; diagnostics go to stderr and no report is emitted.

## Comparison policy

The policy is based on the Operation/Parameter/Response and Schema Objects in [OpenAPI 3.0.4](https://spec.openapis.org/oas/v3.0.4.html) and [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html), with the following explicit compatibility rules. A breaking finding is a contract change that can affect existing consumers under these rules. `review` calls out ambiguity or an unassessed area. `non-breaking` applies to the specific rule and does not certify the whole API.

| Surface | Compared behavior |
| --- | --- |
| Operations | Match exact path text plus HTTP method (`get`, `put`, `post`, `delete`, `options`, `head`, `patch`, `trace`). Removal is breaking; addition is non-breaking. Renaming a path or template variable is an operation removal plus addition. Paths with no operations do not generate findings. |
| Parameters and bodies | Match effective parameters by exact `(in, name)`. Operation entries override path entries; `Accept`, `Content-Type`, and `Authorization` header parameters are ignored. Parameter and body `required` default to `false`; path parameters must declare `true`. Adding a required input or making an existing input required is breaking. Optional additions and required-to-optional changes are non-breaking; removals need review. |
| Response statuses | Match declared keys literally. Removing a status, range such as `2XX`, or `default` is breaking even if another key covers the same numeric status. Additions are non-breaking under this policy. |
| Media types | Compare literal keys inside retained request bodies and retained response statuses. Removal is breaking; a new request media type is non-breaking and a new response media type needs review. For retained parameters, `content` must contain exactly one media type and cannot coexist with `schema`. Switching a parameter's media type or switching between `content` and `schema` needs review. Wildcard coverage and content negotiation are not inferred. |
| Schemas | Compare direct parameter `schema` and schemas under matched media types for parameters, request bodies, and responses. Recognized facets: a single primitive/object/array type (`integer` is a subset of `number`), scalar `enum` sets, object `properties` and `required`, and homogeneous `items`. Narrowing accepted request types or enums is breaking; broadening possible response types or enums is breaking. New required request fields and loss of guaranteed response fields are breaking. Optional response property removal is also breaking under the documented-field policy. Request property presence changes not already classified by requiredness are flagged for review, since they can affect handling of extra fields. |

### Coverage limits

- This is a **review aid, not a full OpenAPI validator or compatibility proof**. It checks structure it needs while traversing operations and compares supported schema facets independently, without proving their joint constraints. It doesn't exhaustively inspect added/removed operations, statuses, media types, or unused components.
- The only resolved references are literal same-document `#/components/{parameters,requestBodies,responses,schemas}/NAME` pointers to named components. Path Item references, relative files, URLs, other fragment forms, and recursive schema expansion are unsupported. Unresolved references encountered in a compared position produce review findings. An unresolved parameter can mask an override, so parameter comparisons for that operation are skipped; body and response checks still run.
- Matched unsupported schema subtrees produce review even when unchanged. For unsupported keywords, schema forms, and unresolved schema references, the finding names the affected side or sides and points to the relevant keyword or schema, including local component definitions. Examples include composition (`oneOf`, `anyOf`, `allOf`), type arrays, boolean schemas, non-scalar enums, closed or schema-valued `additionalProperties`, `nullable: true`, validation constraints such as `pattern`/`format`, and custom 3.1 dialects or resource scopes. The tool does not infer direction-specific requiredness from `readOnly`/`writeOnly` or references on individual fields. Documentation and vendor extensions are ignored. Explicit schema presence changes are marked for review.
- Auth/security requirements, server/base URLs, parameter serialization, response headers, media encodings, links, callbacks, webhooks, and runtime behavior are ignored. An empty report only means the supported comparisons had no findings.

## Development

```sh
python -m pip install '.[test]'
python -m pytest -q
python -m ruff check .
```

PyYAML is the sole runtime dependency. GitHub Actions runs tests, lint, and an installed CLI smoke test on Python 3.11 and 3.14. MIT licensed.

### Regression vectors

`tests/regression_vectors/` contains synthetic before/after OpenAPI documents and
their expected findings. These cases cover operation matching, parameter overrides
and requiredness, literal response and media keys, and the different directions of
request and response schema compatibility. Each case checks the complete ordered
list of severities, codes, and before/after/operation JSON Pointers. An empty
`expected` list asserts that the comparison reports no changes.

Run the corpus offline with `python -m pytest -q tests/test_regression_vectors.py`.
Use `-k <scenario-slug>` to select a case by filename stem.

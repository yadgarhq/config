#!/usr/bin/env python3
"""A knob lives in exactly one file.

There is no merge and no precedence between `shared.yaml` and a service's own
document. A value assembled from two layers is a value nobody wrote and nobody
can attribute to a source, which is the single-writer failure D4 exists to
prevent — and it fails SILENTLY, because both files look authoritative.

D34 already states the rule for prompts in exactly these terms: resolution
replaces, it does not merge. This is the same rule for configuration, enforced
rather than remembered.

WHAT IT CHECKS: no leaf key path appears in more than one document under
`chart/config/`. Leaf, not every node — `tlsRotation` appearing in two files is
only a collision if a knob under it does, and reporting the parent would make the
message point at the wrong line.

THERE ARE TWO SOURCES NOW, NOT ONE, and half a rule enforced is worse than none
because it reads as full coverage. ADR-0705 lets a CONSEQUENTIAL knob come from
the adopter's own values file instead of from `chart/config/`, declared in
`chart/consequential.yaml`. That ruling amends ADR-0569 on the ORIGIN of a value
only and upholds one-knob-one-source, so the partition is checked ACROSS both
sources: a knob declared consequential and also present in `chart/config/` is the
same two-writer fault as a knob in two documents, and `chart/config/` alone cannot
see it.

THE PARTITION THIS MECHANISM CAN ENFORCE IS BY TOP-LEVEL KEY, not by leaf.
`chart/templates/configmap.yaml` APPENDS the values-supplied keys to its verbatim
copy of the document, so a top-level key that document already has would emit a
duplicate mapping key — a ConfigMap that renders cleanly and that `serde_yaml`
then refuses. A leaf-level partition would need a deep merge, and a merge would
re-emit the document and take its comments away, which is the property this
repository exists to keep. So `tlsRotation.pollSeconds` cannot be declared
consequential while `tlsRotation.splayMaxSeconds` stays in `shared.yaml`: both move
or neither does. That is a real limit of the design, stated here rather than
discovered at a sync.

IT ALSO REFUSES THE DECLARATION AND THE SCHEMA DISAGREEING, in either direction.
`chart/values.schema.json` is closed at every level, so a knob declared with no
property is refused before the template runs — the adopter meets a schema error
about a key upstream told them to set. A property with no declaration is the
opposite fault: a value the schema blesses and nothing appends, which is the exact
silent no-op that schema was closed to delete.

BOTH `chart/consequential.yaml` AND `chart/values.schema.json` ABSENT MEANS NOTHING
IS DECLARED, and is not a fault. Neither file can be deleted to turn this check
off quietly, because the agreement check above is symmetric: deleting one while the
other still names a knob is itself a refusal.

IT ALSO REFUSES THREE WAYS A FILE CAN BE PRESENT AND UNREAD, because each of
them passes every other check in this repository while rendering no ConfigMap:
a `chart/config/` holding no `*.yaml` at all (a glob that matches nothing makes
this whole gate a check that cannot fail), a `.yml` extension (the chart's
`.Files.Glob` names `*.yaml`, so a `.yml` file renders nothing and the service
that wanted it refuses to boot), and a stem that is not a DNS-1123 label (the
stem IS the ConfigMap's name; `helm lint` reports an invalid one as a WARNING
and still exits 0, so it reaches Argo and fails at sync).

WHAT IT DOES NOT CHECK, and says so rather than implying coverage it lacks:
whether a knob has a reader, whether its value is sensible, or whether a service
mounts the file its knobs are in. The first two are questions for a human; the
third belongs to the consuming chart.

If a knob genuinely needs a per-service override of a shared value, that is a
design change to bring to the decision record — not something to reach by adding
precedence here.
"""

import json
import pathlib
import re
import sys

import yaml

CONFIG = pathlib.Path("chart/config")

# THE SECOND SOURCE (ADR-0705), and the schema that has to agree with it. Both
# relative, resolved when the script runs, so a test lays out a tree under
# `tmp_path` and runs the gate there.
CONSEQUENTIAL = pathlib.Path("chart/consequential.yaml")
SCHEMA = pathlib.Path("chart/values.schema.json")

# RFC 1123 label. A ConfigMap name may be a DNS SUBDOMAIN, which also allows
# dots, but the name is the directory a service mounts it under, so the stricter
# form is the one this repository means. All seven current names satisfy it.
DNS_1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def leaves(node, prefix=""):
    """Every leaf key path in a parsed document, dotted."""
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            # A mapping recurses; a list or a scalar is where a value lives, and
            # a list's INDICES are not key paths — two files each holding a
            # three-element list under different keys collide at no index.
            if isinstance(value, dict) and value:
                yield from leaves(value, path)
            else:
                yield path


def schema_leaves(node, prefix=""):
    """Every leaf path a JSON-Schema `properties` tree declares, dotted.

    A property with no nested `properties` is a leaf, whatever its `type` says: a
    free-form object an adopter fills in is one value from this gate's point of
    view, and the chart appends it whole.
    """
    for key, subschema in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        nested = (subschema or {}).get("properties")
        if isinstance(nested, dict) and nested:
            yield from schema_leaves(nested, path)
        else:
            yield path


def read_declaration() -> tuple[dict[str, list[str]], str | None]:
    """`chart/consequential.yaml` as stem -> dotted knob paths.

    ABSENT MEANS NOTHING IS DECLARED, which matches the `{}` the file ships with.
    A missing file is not a way to switch this off: the schema-agreement check
    below refuses a schema that still names a knob.
    """
    if not CONSEQUENTIAL.is_file():
        return {}, None
    try:
        document = yaml.safe_load(CONSEQUENTIAL.read_text())
    except yaml.YAMLError as error:
        return {}, f"{CONSEQUENTIAL} is not a YAML document: {error}"
    if document is None:
        return {}, None
    if not isinstance(document, dict):
        return {}, (
            f"{CONSEQUENTIAL} must be a mapping of config-file stem to a list of "
            "dotted knob paths, or `{}` when nothing is declared."
        )
    declared: dict[str, list[str]] = {}
    for stem, knobs in document.items():
        if not isinstance(knobs, list) or not knobs:
            return {}, (
                f"{CONSEQUENTIAL} — `{stem}` must be a non-empty LIST of dotted "
                "knob paths. Delete the key rather than leaving it empty."
            )
        for knob in knobs:
            if not isinstance(knob, str) or not knob or knob.startswith(".") or knob.endswith("."):
                return {}, (
                    f"{CONSEQUENTIAL} — `{stem}` holds `{knob!r}`, which is not a "
                    "dotted knob path such as `archive.bucketName`."
                )
        declared[str(stem)] = [str(knob) for knob in knobs]
    return declared, None


def check_schema_agreement(declared: dict[str, list[str]]) -> list[str]:
    """The declaration and `values.schema.json` name exactly the same knobs.

    Both directions, because they fail differently. A knob declared with no
    property is refused by the closed schema before the template runs, so the
    adopter meets a schema error about a key upstream told them to set. A property
    with no declaration blesses a value nothing appends — the silent no-op that
    schema was closed to delete.
    """
    wanted = {f"{stem}.{knob}" for stem, knobs in declared.items() for knob in knobs}
    if not SCHEMA.is_file():
        if wanted:
            return [
                f"::error::{SCHEMA} does not exist, but {CONSEQUENTIAL} declares "
                + ", ".join(f"`{path}`" for path in sorted(wanted))
                + ". The schema is closed, so a declared knob with no property is "
                "refused before the template runs."
            ]
        return []
    try:
        schema = json.loads(SCHEMA.read_text())
    except json.JSONDecodeError as error:
        return [f"::error::{SCHEMA} is not JSON: {error}"]

    findings = []
    if schema.get("additionalProperties") is not False:
        findings.append(
            f"::error::{SCHEMA} must keep `additionalProperties: false`. It is what "
            "makes a key with no reader a refusal rather than a rubber stamp, and "
            "that behaviour survives the values interface rather than being traded "
            "for it."
        )
    have = set(schema_leaves(schema.get("properties")))
    for path in sorted(wanted - have):
        findings.append(
            f"::error::`{path}` is declared consequential in {CONSEQUENTIAL} but "
            f"{SCHEMA} declares no property for it. The schema is closed, so an "
            "adopter who sets the knob upstream told them to set is refused by name."
        )
    for path in sorted(have - wanted):
        findings.append(
            f"::error::{SCHEMA} declares `{path}` but {CONSEQUENTIAL} does not. "
            "Nothing appends it, so an adopter's value is blessed by the schema and "
            "then dropped — the silent no-op this schema was closed to delete."
        )
    return findings


def main() -> int:
    if not CONFIG.is_dir():
        print(f"::error::{CONFIG} does not exist")
        return 1

    strays = sorted(CONFIG.glob("*.yml"))
    if strays:
        for path in strays:
            print(
                f"::error::{path} ends in `.yml`. The chart globs `config/*.yaml`, "
                "so this file renders no ConfigMap and every service that wanted "
                "it refuses to boot. Rename it."
            )
        return 1

    documents = sorted(CONFIG.glob("*.yaml"))
    if not documents:
        print(
            f"::error::{CONFIG} holds no `*.yaml`. Every knob in this estate comes "
            "from a document here, so an empty directory is not a clean tree — it "
            "is a gate with nothing to check."
        )
        return 1

    declared, complaint = read_declaration()
    if complaint:
        print(f"::error::{complaint}")
        return 1

    owners: dict[str, list[str]] = {}
    top_level: dict[str, set[str]] = {}
    for path in documents:
        if not DNS_1123_LABEL.match(path.stem):
            print(
                f"::error::{path} — `{path.stem}` is not a DNS-1123 label, and the "
                "stem is the ConfigMap's name. `helm lint` reports this as a "
                "warning and exits 0, so it passes CI and fails at sync. Use "
                "lower-case letters, digits and hyphens."
            )
            return 1
        try:
            document = yaml.safe_load(path.read_text())
        except yaml.YAMLError as error:
            print(f"::error::{path} is not a YAML document: {error}")
            return 1
        # A comments-only document parses to None. That is a file waiting for its
        # first knob, not a fault.
        if document is None:
            top_level[path.stem] = set()
            continue
        if not isinstance(document, dict):
            print(f"::error::{path} must be a mapping at the top level")
            return 1
        top_level[path.stem] = {str(key) for key in document}
        for knob in leaves(document):
            owners.setdefault(knob, []).append(str(path))

    # THE SECOND SOURCE JOINS THE SAME KEYSPACE, so a knob declared consequential
    # and also written in `chart/config/` is reported by the collision loop below
    # with the same message and both sources named. Nothing special-cases it,
    # because it is not a special case: it is one knob with two writers.
    stems = {path.stem for path in documents}
    for stem, knobs in sorted(declared.items()):
        if stem not in stems:
            print(
                f"::error::{CONSEQUENTIAL} declares knobs for `{stem}`, but "
                f"{CONFIG}/{stem}.yaml does not exist. An adopter would set the "
                "value, the schema would accept it, and no ConfigMap would carry "
                "it."
            )
            return 1
        for knob in knobs:
            owners.setdefault(knob, []).append(str(CONSEQUENTIAL))

    collisions = {k: v for k, v in owners.items() if len(v) > 1}
    if collisions:
        for knob, files in sorted(collisions.items()):
            print(
                f"::error::`{knob}` is defined in {len(files)} files: "
                + ", ".join(files)
                + ". A knob has one source — there is no merge and no precedence "
                "between these files. Delete it from all but one."
            )
        return 1

    # THE TOP-LEVEL PARTITION, which is stricter than the leaf rule above and has
    # to be. The chart APPENDS a values-supplied top-level mapping to its verbatim
    # copy of the document, so a top-level key the document already holds emits a
    # DUPLICATE mapping key: a ConfigMap that renders cleanly and a reader that
    # refuses to parse it. A leaf-level partition would need a deep merge, and a
    # merge would re-emit the document and take its comments away.
    for stem, knobs in sorted(declared.items()):
        for knob in knobs:
            parent = knob.split(".", 1)[0]
            if parent in top_level.get(stem, set()):
                siblings = sorted(
                    path
                    for path in owners
                    if path == parent or path.startswith(f"{parent}.")
                )
                print(
                    f"::error::`{knob}` is declared consequential in "
                    f"{CONSEQUENTIAL}, so it carries no default — but "
                    f"{CONFIG}/{stem}.yaml already defines `{parent}` at the top "
                    "level. The chart appends the values-supplied keys to its "
                    "verbatim copy of that document, so a top-level key it already "
                    "has would emit a duplicate mapping key. The partition is by "
                    "TOP-LEVEL KEY, not by leaf: move every knob under "
                    f"`{parent}` or none of them. Under `{parent}` today: "
                    + ", ".join(f"`{path}`" for path in siblings)
                    + "."
                )
                return 1

    findings = check_schema_agreement(declared)
    if findings:
        for finding in findings:
            print(finding)
        return 1

    print(f"{len(owners)} knobs, each defined once, across {len(documents)} files.")
    consequential = sum(len(knobs) for knobs in declared.values())
    # A SECOND LINE RATHER THAN A REWORDING of the one above, which the suite pins
    # verbatim. Zero is the state this repository means to be in, so it is printed
    # rather than left to be inferred from silence.
    print(
        f"{consequential} of them carry no default and come from the adopter's "
        f"values file ({CONSEQUENTIAL})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

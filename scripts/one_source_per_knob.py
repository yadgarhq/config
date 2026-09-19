#!/usr/bin/env python3
"""A knob lives in exactly one file, and every knob the chart knows is declared.

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

THERE ARE TWO SOURCES, NOT ONE, and half a rule enforced is worse than none
because it reads as full coverage. ADR-0705 lets a CONSEQUENTIAL knob come from
the adopter's own values file instead of from `chart/config/`, declared in
`chart/consequential.yaml`. That ruling amends ADR-0569 on the ORIGIN of a value
only and upholds one-knob-one-source, so the partition is checked ACROSS both
sources: a knob declared consequential and also present in `chart/config/` is the
same two-writer fault as a knob in two documents, and `chart/config/` alone cannot
see it.

THE PARTITION IS PER LEAF, and under ADR-0721 that is the whole of it. The chart
renders each ConfigMap from a DEEP MERGE of its own document under the adopter's
`.Values.<stem>`, so nothing is appended and no duplicate mapping key can be
emitted. `tlsRotation.pollSeconds` may therefore be declared consequential while
`tlsRotation.splayMaxSeconds` keeps its default — which ADR-0720's append could
not express, and which this gate refused until 0.1.4 on that ground. What may NOT
happen is the same LEAF living in both sources at once.

IT ALSO REFUSES EVERY DISAGREEMENT BETWEEN THE TWO SOURCES AND THE SCHEMA, in
both directions, because `chart/values.schema.json` is the interface an adopter
actually meets. Per leaf, exactly one of two things supplies a knob: the chart's
own document carries a default for it, or `chart/consequential.yaml` declares it
consequential and it carries no default anywhere. The schema declares that union
and nothing else. So three faults, each with its own message:

  - A chart default with NO schema property: the adopter cannot change the knob
    from their own repository at all, so they must fork the chart. That is the
    clone-nothing-change-nothing state ADR-0721 exists to delete, one knob at a
    time.
  - A declared consequential knob with NO schema property: the closed schema
    refuses it before the template runs, so the adopter meets a schema error about
    the key upstream told them to set.
  - A schema property with NEITHER a chart default nor a declaration: unset, the
    knob is absent from the rendered document and the reader refuses to boot, with
    nothing from this chart saying which knob or which file (ADR-0569). Set, it
    works. A knob whose refusal depends on whether anybody happened to state it is
    the failure both rulings are about.

HELM'S `global` IS THE ONE PROPERTY WITH NO SOURCE, and it is exempt by name. Helm
injects it into every subchart's values, so a closed schema that does not declare it
makes this chart unusable as a DEPENDENCY — which ADR-0722's parent chart needs. It
is not a knob, nothing in `chart/config/` can default it, and declaring it
consequential would mean nothing; so it is expected in the schema and excluded from
the partition rather than being made to satisfy it.

`chart/values.schema.json` MUST EXIST and MUST BE CLOSED AT EVERY LEVEL. It is
what turns a key with no reader into a refusal naming the key, and under ADR-0721
it is also the only thing standing between a typo and a value merged into a
document beside the knob it was meant to be — `pollSecond` next to `pollSeconds`,
both looking set, one of them read. `chart/consequential.yaml` may be absent,
which means nothing is declared; the disagreement checks are symmetric, so
deleting one file while the other still names a knob is itself a refusal.

IT ALSO REFUSES THREE WAYS A FILE CAN BE PRESENT AND UNREAD, because each of
them passes every other check in this repository while rendering no ConfigMap:
a `chart/config/` holding no `*.yaml` at all (a glob that matches nothing makes
this whole gate a check that cannot fail), a `.yml` extension (the chart's
`.Files.Glob` names `*.yaml`, so a `.yml` file renders nothing and the service
that wanted it refuses to boot), and a stem that is not a DNS-1123 label (the
stem IS the ConfigMap's name; `helm lint` reports an invalid one as a WARNING
and still exits 0, so it reaches Argo and fails at sync).

WHAT IT DOES NOT CHECK, and says so rather than implying coverage it lacks:
whether a knob has a reader, whether its value is sensible, whether the TYPE the
schema gives a knob matches the value the chart defaults it to, or whether a
service mounts the file its knobs are in. The first two are questions for a human,
the third is a render-time question `helm lint` answers on the chart's own
documents only if they are overridden, and the fourth belongs to the consuming
chart.

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

# THE SECOND SOURCE (ADR-0705), and the schema that has to agree with both. All
# relative, resolved when the script runs, so a test lays out a tree under
# `tmp_path` and runs the gate there.
CONSEQUENTIAL = pathlib.Path("chart/consequential.yaml")
SCHEMA = pathlib.Path("chart/values.schema.json")

# HELM'S OWN RESERVED KEY, which is not a knob and has no source. Helm injects
# `global` into every subchart's values, so a closed schema that does not declare it
# makes this chart impossible to use as a DEPENDENCY: a parent holding it in `charts/`
# fails to render with no values supplied at all. It is therefore expected in the
# schema and exempt from the per-leaf partition below — `chart/config/` cannot carry a
# default for it and declaring it consequential would be meaningless.
RESERVED = {"global"}

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
    view, and the chart merges it whole.
    """
    for key, subschema in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        nested = (subschema or {}).get("properties")
        if isinstance(nested, dict) and nested:
            yield from schema_leaves(nested, path)
        else:
            yield path


def open_levels(node, prefix=""):
    """Every level of a `properties` tree that is not closed.

    `additionalProperties: false` at the ROOT ONLY would leave `shared: {tlsRotation:
    {pollSecond: 30}}` accepted — the typo is not an additional property of the
    root, it is one of `tlsRotation`. Under ADR-0721 that value would then be
    merged into `shared.yaml` beside the knob it was meant to be.
    """
    for key, subschema in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        nested = (subschema or {}).get("properties")
        if isinstance(nested, dict) and nested:
            if (subschema or {}).get("additionalProperties") is not False:
                yield path
            yield from open_levels(nested, path)


def read_declaration() -> tuple[dict[str, list[str]], str | None]:
    """`chart/consequential.yaml` as stem -> dotted knob paths.

    ABSENT MEANS NOTHING IS DECLARED, which matches the `{}` the file ships with.
    A missing file is not a way to switch this off: the disagreement checks below
    refuse a schema that still names a knob nothing supplies.
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


def check_the_schema(defaulted: set[str], declared: set[str]) -> list[str]:
    """The schema declares exactly the union of the two sources, per leaf.

    `defaulted` is every `<stem>.<dotted path>` a document under `chart/config/`
    carries a value for; `declared` is every one `chart/consequential.yaml` names.
    They are disjoint by the collision check in `main`, and their union is the set
    of knobs this chart KNOWS. The schema names that set and nothing else, because
    the three ways the two can disagree fail three different ways — each of them
    written out in this file's docstring.
    """
    if not SCHEMA.is_file():
        return [
            f"::error::{SCHEMA} does not exist. It is the interface an adopter meets: "
            "it is what makes a knob settable from their own repository (ADR-0721) and "
            "what makes a key with no reader a refusal naming the key rather than a "
            "value merged in beside the knob it was meant to be."
        ]
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
    for path in sorted(open_levels(schema.get("properties"))):
        findings.append(
            f"::error::{SCHEMA} — `{path}` does not set `additionalProperties: false`. "
            "The schema is closed AT EVERY LEVEL or it is not closed: a typo one level "
            f"down is an additional property of `{path}`, not of the root, and the "
            "chart would merge it into the document beside the knob it was meant to be."
        )

    have = set(schema_leaves(schema.get("properties"))) - RESERVED
    for path in sorted(declared - have):
        findings.append(
            f"::error::`{path}` is declared consequential in {CONSEQUENTIAL} but "
            f"{SCHEMA} declares no property for it. The schema is closed, so an "
            "adopter who sets the knob upstream told them to set is refused by name."
        )
    for path in sorted(defaulted - have):
        findings.append(
            f"::error::`{path}` carries a default in {CONFIG}/{path.split('.')[0]}.yaml "
            f"and {SCHEMA} declares no property for it, so no adopter can change it "
            "without forking this chart. That is the state ADR-0721 exists to delete, "
            "one knob at a time: declare it here, typed, and the chart merges an "
            "adopter's value over the default."
        )
    for path in sorted(have - (defaulted | declared)):
        findings.append(
            f"::error::{SCHEMA} declares `{path}`, but nothing supplies it: "
            f"{CONFIG}/{path.split('.')[0]}.yaml carries no default for it and "
            f"{CONSEQUENTIAL} does not declare it consequential. An adopter who leaves "
            "it unset gets a document with the knob missing and a reader that refuses "
            "to boot (ADR-0569), with nothing from this chart naming the knob or the "
            "file. Give it a default or declare it consequential."
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
    # THE SAME KNOBS AGAIN, ADDRESSED THE WAY AN ADOPTER ADDRESSES THEM: the file
    # stem outermost, which is what `.Values.<stem>` and the schema both use. The
    # collision check below works in the document's own keyspace, where two files
    # holding one knob collide; the schema check works in the adopter's, where the
    # stem is part of the knob's address.
    defaulted: set[str] = set()
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
            continue
        if not isinstance(document, dict):
            print(f"::error::{path} must be a mapping at the top level")
            return 1
        for knob in leaves(document):
            owners.setdefault(knob, []).append(str(path))
            defaulted.add(f"{path.stem}.{knob}")

    # THE SECOND SOURCE JOINS THE SAME KEYSPACE, so a knob declared consequential
    # and also written in `chart/config/` is reported by the collision loop below
    # with the same message and both sources named. Nothing special-cases it,
    # because it is not a special case: it is one knob with two writers.
    stems = {path.stem for path in documents}
    consequential: set[str] = set()
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
            consequential.add(f"{stem}.{knob}")

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

    findings = check_the_schema(defaulted, consequential)
    if findings:
        for finding in findings:
            print(finding)
        return 1

    print(f"{len(owners)} knobs, each defined once, across {len(documents)} files.")
    # A SECOND LINE RATHER THAN A REWORDING of the one above, which the suite pins
    # verbatim. Zero is the state this repository means to be in, so it is printed
    # rather than left to be inferred from silence.
    print(
        f"{len(consequential)} of them carry no default and come from the adopter's "
        f"values file ({CONSEQUENTIAL})."
    )
    # AND THE NUMBER ADR-0721 IS ABOUT. Every knob the chart knows is settable from
    # an adopter's own repository, so this is the first line that goes DOWN when
    # somebody adds a default and forgets the schema — which is a refusal above, not
    # a number to watch, but the count is what says the interface is whole.
    print(f"{len(defaulted | consequential)} of them are settable from an adopter's values file ({SCHEMA}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

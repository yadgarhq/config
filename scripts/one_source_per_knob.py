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

import pathlib
import re
import sys

import yaml

CONFIG = pathlib.Path("chart/config")

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

    owners: dict[str, list[str]] = {}
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

    print(f"{len(owners)} knobs, each defined once, across {len(documents)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

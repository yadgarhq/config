"""What `chart/values.schema.json` declares and what it refuses.

THIS CHART READS A HELM VALUE FOR EVERY KNOB IT DEFINES (ADR-0721). Each ConfigMap
is rendered from a deep merge of the chart's own `config/<stem>.yaml` under the
adopter's `.Values.<stem>`, so the schema is the interface an adopter meets: it says
which knobs exist, what type each takes, and it REFUSES every other key by name.
`test_values_merge.py` covers what the merge does with a value that is accepted;
this file covers the boundary — what gets in, what does not, and the one reserved
key that is neither.

THE REFUSAL IS NOT TRADED FOR THE INTERFACE. `additionalProperties: false` stays at
EVERY level. Up to chart 0.1.1 a values file was silently DROPPED: byte-identical
output, exit 0, no warning, which is ADR-0569's own failure one layer out — a value
whose effect depends on which layer you inspect. Up to 0.1.4 it was refused in full,
which is the other failure: an adopter could clone nothing and change nothing. Both
are closed by declaring the knobs and refusing everything else.

Run: python3 -m pytest scripts/tests/ -q
"""

import json
import shutil
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "chart"
CONFIG = CHART / "config"
SCHEMA = CHART / "values.schema.json"

# HELM'S OWN RESERVED KEY, declared in the schema and not a knob — see
# `test_the_chart_renders_as_a_subchart` for the measurement that forced it.
RESERVED = {"global"}


def helm(*arguments: str):
    binary = shutil.which("helm")
    # NOT A SKIP — see `test_required_knob.py`. A pass reported without helm is a
    # pass nobody earned.
    assert binary, (
        "helm is not on PATH. This suite renders the chart, and so does the "
        "`helm lint and render` pre-commit hook — install helm rather than "
        "letting either report a pass it did not earn."
    )
    return subprocess.run([binary, *arguments], capture_output=True, text=True)


def schema_leaves(node, prefix=""):
    """Every leaf path the schema declares, dotted — the gate's own rule, restated.

    `scripts/one_source_per_knob.py` owns this at commit time. It is restated here
    because the two answer different questions: the gate refuses a tree that
    disagrees, and this file asserts what the shipped tree actually says.
    """
    for key, subschema in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        nested = (subschema or {}).get("properties")
        if isinstance(nested, dict) and nested:
            yield from schema_leaves(nested, path)
        else:
            yield path


def chart_leaves(node, prefix=""):
    for key, value in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            yield from chart_leaves(value, path)
        else:
            yield path


def every_level(node, prefix=""):
    """Every `(path, subschema)` in the properties tree that has children."""
    for key, subschema in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        nested = (subschema or {}).get("properties")
        if isinstance(nested, dict) and nested:
            yield path, subschema
            yield from every_level(nested, path)


# ------------------------------------------------------------- what gets in


def test_the_chart_renders_with_no_values():
    """THE NORMAL CASE, and the one a closed schema could plausibly break.

    Argo passes nothing today: `yadgarhq/deploy`'s `infra/config-app.yaml` declares
    no `helm:` block at all, so the live sync renders exactly this.
    """
    result = helm("template", "ci-render", str(CHART))
    assert result.returncode == 0, result.stderr


def test_a_knob_stated_under_its_own_stem_is_accepted():
    """THE GREEN HALF of the refusal below, and ADR-0721's whole promise: one line
    in the adopter's own repository, no clone and no fork.
    """
    result = helm(
        "template", "ci-render", str(CHART), "--set", "shared.tlsRotation.pollSeconds=30"
    )
    assert result.returncode == 0, result.stderr


def test_the_same_knob_at_the_top_level_is_refused():
    """THE PLAUSIBLE MISTAKE. `tlsRotation.pollSeconds` is a REAL knob path, spelled
    without the file stem — which is the one place a Helm chart normally takes its
    settings from, and the shape somebody reaching for `shared.yaml`'s knob writes
    first. The stem is part of the knob's address, so this is refused by name
    rather than merged into a document nothing reads it from.

    Asserting on the KEY rather than on helm's wording: helm 3 says `Additional
    property tlsRotation is not allowed` and helm 4 says `additional properties
    'tlsRotation' not allowed`, and only the key is this repository's to own.
    """
    result = helm("template", "ci-render", str(CHART), "--set", "tlsRotation.pollSeconds=30")
    assert result.returncode != 0
    assert "tlsRotation" in result.stderr


def test_the_lint_refuses_a_misnested_knob_too():
    """BOTH GATES, because they are reached by different paths.

    `helm lint --strict` is the `helm lint and render` hook and therefore `ci /
    passed`; `helm template` is what Argo runs. A schema enforced by only one of
    them would be a gate an adopter never meets.

    `audit.retentionDays` is the knob one level short of its address: the real one
    is `audit.audit.retentionDays`, because the stem and the document's top-level
    key are both `audit`. That is the easiest of the four to get wrong.
    """
    result = helm("lint", "--strict", str(CHART), "--set", "audit.retentionDays=7")
    assert result.returncode != 0
    assert "retentionDays" in result.stdout + result.stderr


# ------------------------------------------- helm's reserved key, and subcharts


def test_a_values_file_holding_only_global_renders(tmp_path):
    """HELM INJECTS `global` INTO EVERY SUBCHART'S VALUES, so a closed schema that
    does not declare it makes this chart impossible to use as a DEPENDENCY at all.

    Measured before it was declared: `at '': additional properties 'global' not
    allowed` on helm 4.2.3, `(root): Additional property global is not allowed` on
    helm 3.18.4. ADR-0722 rules that upstream ships a parent chart pinning every
    module chart, so this is a blocker rather than a hypothetical.
    """
    values = tmp_path / "values.yaml"
    values.write_text("global:\n  imageRegistry: ghcr.io\n")
    result = helm("template", "ci-render", str(CHART), "-f", str(values))
    assert result.returncode == 0, result.stderr


def test_an_unknown_key_beside_global_is_still_refused(tmp_path):
    """config#15's BEHAVIOUR SURVIVES THE EXEMPTION. Admitting helm's reserved key
    is not the same as opening the schema, and the difference is what this case
    pins: `additionalProperties: false` stays, so a key with no reader is still
    refused by name.
    """
    values = tmp_path / "values.yaml"
    values.write_text("global:\n  imageRegistry: ghcr.io\nfoo: bar\n")
    result = helm("template", "ci-render", str(CHART), "-f", str(values))
    assert result.returncode != 0
    assert "foo" in result.stderr
    result = helm("lint", "--strict", str(CHART), "-f", str(values))
    assert result.returncode != 0
    assert "foo" in result.stdout + result.stderr


def test_the_chart_renders_as_a_subchart(tmp_path):
    """AS A DEPENDENCY, not only standalone, because that is the shape that failed.

    A parent chart with this chart in its `charts/` directory is what ADR-0722
    describes, and helm injects `global` whether the parent sets anything or not —
    so this case fails with NO values supplied when the reserved key is undeclared.
    No network: the subchart is a copy on disk, which is what a resolved `file://`
    or OCI dependency leaves behind.
    """
    parent = tmp_path / "parent"
    (parent / "charts").mkdir(parents=True)
    shutil.copytree(CHART, parent / "charts" / "config")
    (parent / "Chart.yaml").write_text("apiVersion: v2\nname: parent\nversion: 0.0.1\n")
    (parent / "values.yaml").write_text("{}\n")
    result = helm("template", "parent-render", str(parent))
    assert result.returncode == 0, result.stderr
    names = sorted(
        document["metadata"]["name"]
        for document in yaml.safe_load_all(result.stdout)
        if document
    )
    assert names == sorted(path.stem for path in CONFIG.glob("*.yaml"))


def test_a_parent_chart_can_override_a_knob_through_the_subchart(tmp_path):
    """THE INTERFACE THROUGH THE PARENT, which is how an installation under
    ADR-0722 states a value: `config:` in the parent's values, then the knob's own
    path. A chart that rendered as a subchart but ignored the parent's value would
    pass the case above and still be useless.
    """
    parent = tmp_path / "parent"
    (parent / "charts").mkdir(parents=True)
    shutil.copytree(CHART, parent / "charts" / "config")
    (parent / "Chart.yaml").write_text("apiVersion: v2\nname: parent\nversion: 0.0.1\n")
    (parent / "values.yaml").write_text(
        "config:\n  shared:\n    tlsRotation:\n      pollSeconds: 45\n"
    )
    result = helm("template", "parent-render", str(parent))
    assert result.returncode == 0, result.stderr
    documents = {
        document["metadata"]["name"]: document["data"]
        for document in yaml.safe_load_all(result.stdout)
        if document
    }
    rendered = documents["shared"]["shared.yaml"]
    assert "pollSeconds: 45\n" in rendered
    assert yaml.safe_load(rendered)["tlsRotation"]["splayMaxSeconds"] == 300


def test_nothing_under_global_reaches_a_rendered_document(tmp_path):
    """`global` IS ADMITTED, NOT READ. The template only ever looks at
    `.Values.<config file stem>`, so a parent's shared values change no ConfigMap —
    every document stays the byte-for-byte copy it is with no values at all.
    """
    values = tmp_path / "values.yaml"
    values.write_text("global:\n  imageRegistry: ghcr.io\n  shared: not-a-knob\n")
    result = helm("template", "ci-render", str(CHART), "-f", str(values))
    assert result.returncode == 0, result.stderr
    for document in yaml.safe_load_all(result.stdout):
        if not document:
            continue
        stem = document["metadata"]["name"]
        assert document["data"][f"{stem}.yaml"] == (CONFIG / f"{stem}.yaml").read_text(), stem


# -------------------------------------------------- what the shipped tree says


def test_the_schema_declares_EXACTLY_the_knobs_the_two_sources_supply():
    """THE PARTITION, ASSERTED ON THE SHIPPED TREE. Per leaf, a knob is either
    defaulted in `chart/config/<stem>.yaml` or declared consequential in
    `chart/consequential.yaml` — never both, never neither — and the schema names
    that union and nothing else.

    A typed knob NEITHER source supplies would be a value an adopter may set, no
    upstream default behind it and no `required` refusing its absence: unset, the
    reader refuses to boot with nothing from this chart naming the knob or the
    file. A knob the chart defaults with no property here is the opposite fault and
    the one ADR-0721 exists to delete: the adopter must fork the chart to change
    it.

    `scripts/one_source_per_knob.py` refuses every one of those at commit time.
    This case is the same rule read off the shipped files, so the day a knob is
    added it follows rather than having to be deleted.
    """
    schema = json.loads(SCHEMA.read_text())
    declared = yaml.safe_load((CHART / "consequential.yaml").read_text()) or {}

    supplied = {
        f"{stem}.{knob}" for stem, knobs in declared.items() for knob in knobs
    }
    for path in CONFIG.glob("*.yaml"):
        document = yaml.safe_load(path.read_text()) or {}
        supplied |= {f"{path.stem}.{leaf}" for leaf in chart_leaves(document)}

    assert set(schema_leaves(schema["properties"])) - RESERVED == supplied


def test_the_schema_is_closed_at_EVERY_level():
    """MUTATION TRIPWIRE, and the fault it pins is one level down.

    `additionalProperties: false` at the root alone would accept
    `shared.tlsRotation.pollSecond` — the typo is an additional property of
    `tlsRotation`, not of the root — and under ADR-0721 that value would be MERGED
    into `shared.yaml`, beside the knob it was meant to be, both looking set and
    one of them read.
    """
    schema = json.loads(SCHEMA.read_text())
    assert schema["additionalProperties"] is False
    for path, subschema in every_level(schema["properties"]):
        assert subschema.get("additionalProperties") is False, path


def test_every_declared_knob_carries_a_TYPE():
    """A NAMED KNOB IS NOT A TYPED ONE. A values file reaches helm through
    `sigs.k8s.io/yaml`, so `pollSeconds: "30"` arrives as a string and reaches
    `serde_yaml` as one — which fails the reader at boot rather than the render.
    Every knob the schema declares therefore says what it takes.

    `global` is exempt: it is helm's reserved key rather than a knob, typed as an
    object and deliberately open inside, because its contents belong to the parent
    chart and to the other subcharts.
    """
    schema = json.loads(SCHEMA.read_text())

    def typed(node, prefix=""):
        for key, subschema in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            nested = (subschema or {}).get("properties")
            if isinstance(nested, dict) and nested:
                yield from typed(nested, path)
            elif path not in RESERVED:
                yield path, (subschema or {}).get("type")

    for path, declared_type in typed(schema["properties"]):
        assert declared_type, path

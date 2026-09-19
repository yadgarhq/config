"""What the consequential-knob interface does, proven against a chart COPY.

ADR-0705 rule 2: a knob whose wrong value carries real consequence carries NO
default and is declared with Helm's `required`, so the sync fails naming the knob
and the file. Rule 1 stands unamended — a knob has ONE source — so a consequential
knob lives in the adopter's values file and is ABSENT from `chart/config/`.

THE SHIPPED LIST IS EMPTY AND MUST STAY EMPTY until a knob earns the
classification under the README's Blast radius section. So every case that needs a
declared knob makes a COPY of `chart/` under `tmp_path` and declares one there.
Declaring one in the shipped chart to make a test pass would make upstream's own
`helm lint` unable to render its own chart — see `chart/consequential.yaml`.

WHY A COPY RATHER THAN `--set` ALONE: the declaration and the schema move
together. `chart/values.schema.json` is closed (`additionalProperties: false`) at
every level, so a values key the schema does not declare is refused BEFORE the
template runs. A case that declares a knob therefore has to declare it in the
schema too, which is precisely what a real declaring pull request does — and the
fixture knob is one no document defines, so it is not simply an override of a
chart default.

WHAT THIS FILE IS NOT ABOUT: overriding a knob that HAS a default. That is
ADR-0721's merge, and `test_values_merge.py` covers it against the shipped chart.
Rule 2 is the case where there is no default to fall back on, and the whole of it
is the refusal.

MOST OF THIS FILE DEMANDS A REFUSAL. An interface proven only by its happy path is
an interface that would pass whether the refusal worked or not, and the refusal is
the whole of rule 2.

Run: python3 -m pytest scripts/tests/ -q
"""

import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "chart"

# THE RENDER OF THE SHIPPED CHART, pinned. Recomputed for the pull request that
# deleted the seven per-service documents with at most one reader (ADR-0740).
# TWO THINGS CHANGE THE BYTES, not one: there are fewer ConfigMaps to render at
# all, AND `chart/templates/configmap.yaml`'s own `metadata:` comment — rendered
# into every surviving document too — was corrected for the smaller chart, so
# `shared` and `audit` render with different bytes as well as `gateway` and the
# rest rendering not at all. Taken by running this file's own `render_sha256`
# against the edited chart, not transcribed.
BASELINE_SHA256 = "6954cbbb6e77fd4bd2740c58d99832449ad6176ff29657746d221c45583ade27"


def helm(*arguments: str):
    binary = shutil.which("helm")
    # NOT A SKIP, and ADR-0650 is why: a suite that skips when its subject is
    # absent reports a pass nobody earned. The `helm lint and render` pre-commit
    # hook needs the same binary, so an environment without it cannot check this
    # repository at all and should say so rather than going quietly green.
    assert binary, (
        "helm is not on PATH. This suite renders the chart, and so does the "
        "`helm lint and render` pre-commit hook — install helm rather than "
        "letting either report a pass it did not earn."
    )
    return subprocess.run([binary, *arguments], capture_output=True, text=True)


def render_sha256(*arguments: str) -> str:
    import hashlib

    result = helm("template", "ci-render", *arguments)
    assert result.returncode == 0, result.stderr
    return hashlib.sha256(result.stdout.encode()).hexdigest()


def chart_copy(tmp_path: Path, *, declare: dict, schema_properties: dict) -> Path:
    """A copy of the shipped chart with one knob declared consequential.

    `declare` is the `chart/consequential.yaml` body: file stem -> dotted knob
    paths. `schema_properties` is what `properties` becomes in
    `chart/values.schema.json`. Both are written, because the chart refuses a
    values key that only one of them knows about.
    """
    copy = tmp_path / "chart"
    shutil.copytree(CHART, copy)

    lines = []
    for stem, knobs in declare.items():
        lines.append(f"{stem}:")
        for knob in knobs:
            lines.append(f"  - {knob}")
    (copy / "consequential.yaml").write_text("\n".join(lines) + "\n" if lines else "{}\n")

    schema = json.loads((copy / "values.schema.json").read_text())
    schema["properties"] = schema_properties
    (copy / "values.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    return copy


# `audit.retentionDays` is NOT used as the fixture knob even though it is the one
# with no reader. `audit.yaml` defines it, so declaring it consequential is a
# rule-1 collision the gate refuses — which is a case of its own below. The
# fixture knob is one no document defines, because that is the shape a real
# declaration has.
FIXTURE_DECLARE = {"audit": ["archive.bucketName"]}
FIXTURE_SCHEMA = {
    "audit": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "archive": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"bucketName": {"type": "string", "minLength": 1}},
            }
        },
    }
}


# ------------------------------------------------- the pair that proves rule 2


def test_a_declared_knob_left_unset_refuses_the_render(tmp_path):
    """THE REFUSAL ITSELF, and the half the cut `.Files.Get` mechanism could never have.

    The value is absent from the chart, so the only place it can come from is the
    adopter's values file. Nothing renders until they state it — ADR-0705's "the
    refusal moves from boot to sync".
    """
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    result = helm("template", "ci-render", str(copy))
    assert result.returncode != 0


def test_the_refusal_names_the_knob_and_the_file(tmp_path):
    """A refusal that does not say WHICH knob and WHICH file sends an adopter to grep.

    This is the message ADR-0705 specifies in those words, and it is why the
    declaration list lives in the chart rather than being inferred from the
    schema's own `required`: helm's schema error says `archive is required` on
    helm 3 and `missing property 'archive'` on helm 4, names no file, and is not
    this repository's wording to own.
    """
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    result = helm("template", "ci-render", str(copy))
    assert result.returncode != 0
    assert "archive.bucketName" in result.stderr
    assert "audit.yaml" in result.stderr


def test_the_same_knob_set_in_a_values_file_renders(tmp_path):
    """THE OTHER HALF. A refusal with no way to satisfy it is the mechanism that was cut."""
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text("audit:\n  archive:\n    bucketName: yadgar-audit-archive\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode == 0, result.stderr


def test_the_value_reaches_the_configmap_data(tmp_path):
    """EXIT 0 IS NOT THE CLAIM. A render that succeeds and drops the value is the
    silent no-op `values.schema.json` was closed to delete, one layer further in.

    The assertion is on the ConfigMap's DATA, and on the same document the reader
    opens: a service mounts the ConfigMap as a directory and reads one named file,
    so `audit.yaml` is where the value has to land. A second key or a second
    ConfigMap would be a file that reader never opens.
    """
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text("audit:\n  archive:\n    bucketName: yadgar-audit-archive\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode == 0, result.stderr

    import yaml

    documents = [d for d in yaml.safe_load_all(result.stdout) if d]
    audit = [d for d in documents if d["metadata"]["name"] == "audit"]
    assert len(audit) == 1, [d["metadata"]["name"] for d in documents]
    rendered = audit[0]["data"]["audit.yaml"]
    assert yaml.safe_load(rendered)["archive"]["bucketName"] == "yadgar-audit-archive"


def test_the_overridden_document_is_re_emitted_from_the_MERGED_data(tmp_path):
    """WHAT A DECLARATION COSTS THE DOCUMENT IT BELONGS TO, and it is a cost.

    A consequential knob only arrives from a values file, so the document that
    carries it always has an override — and under ADR-0721 an overridden document is
    re-emitted from the merged data and LOSES its comments. `chart/config/audit.yaml`
    is mostly the reasoning for its number, and `kubectl get cm audit -o yaml` stops
    showing it for an installation that sets a knob in that file. ADR-0721 accepts
    that deliberately: the reasoning still lives in the pinned chart version.

    THE DEEP MERGE IS WHAT KEEPS THE REST OF THE DOCUMENT. `retentionDays` is not
    declared here, so it is still the chart's own 90 — a whole-document replacement
    would have dropped it, which is the alternative ADR-0721 rejected.

    The other half of the split — a document with NO override staying byte-verbatim,
    comments and all — is `test_values_merge.py`'s
    `test_a_document_with_no_override_stays_BYTE_VERBATIM`.
    """
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text("audit:\n  archive:\n    bucketName: yadgar-audit-archive\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode == 0, result.stderr

    import yaml

    documents = [d for d in yaml.safe_load_all(result.stdout) if d]
    rendered = [d for d in documents if d["metadata"]["name"] == "audit"][0]["data"]["audit.yaml"]
    assert [line for line in rendered.splitlines() if line.lstrip().startswith("#")] == []
    parsed = yaml.safe_load(rendered)
    assert parsed["archive"]["bucketName"] == "yadgar-audit-archive"
    assert parsed["audit"]["retentionDays"] == 90


# --------------------------- the per-leaf partition, at RENDER time rather than at commit


SIBLING_DECLARE = {"shared": ["tlsRotation.pollSeconds"]}
SIBLING_SCHEMA = {
    "shared": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tlsRotation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pollSeconds": {"type": "integer", "minimum": 1},
                    "splayMaxSeconds": {"type": "integer", "minimum": 0},
                },
            }
        },
    }
}


def without_pollseconds(copy: Path) -> None:
    """Rule 2 applied to the copy: the declared knob is DELETED from `chart/config/`.

    Its sibling stays. That is what a real declaring pull request does under
    ADR-0721's per-leaf partition, and up to 0.1.4 it was forbidden.
    """
    document = copy / "config" / "shared.yaml"
    lines = [line for line in document.read_text().splitlines(keepends=True)
             if not line.startswith("  pollSeconds:")]
    document.write_text("".join(lines))


def test_a_declared_knob_and_its_sibling_default_RENDER_into_one_mapping(tmp_path):
    """THE CASE ADR-0720 REFUSED, AND IT REFUSED IT AT RENDER TIME.

    Its ground was mechanical: the append wrote a top-level `tlsRotation:` mapping
    into a document that already had one, which emits a DUPLICATE mapping key — a
    ConfigMap that renders cleanly and that `serde_yaml` then refuses, so the reader
    fails to boot on a document helm was happy with. `scripts/one_source_per_knob.py`
    refused it at commit time and the template refused it at render time.

    ADR-0721 replaces the append with a deep merge, and this is the case that proves
    the refusal is gone rather than merely inverted in the gate: `pollSeconds` comes
    from the values file, `splayMaxSeconds` from the chart, and they arrive under ONE
    `tlsRotation` key. The gate-side half of this is
    `test_one_source_per_knob.py::test_a_sibling_under_the_same_top_level_key_MAY_be_classified_differently`,
    which proves nothing about what helm emits.
    """
    copy = chart_copy(tmp_path, declare=SIBLING_DECLARE, schema_properties=SIBLING_SCHEMA)
    without_pollseconds(copy)
    values = tmp_path / "values.yaml"
    values.write_text("shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode == 0, result.stderr

    import yaml

    documents = [d for d in yaml.safe_load_all(result.stdout) if d]
    rendered = [d for d in documents if d["metadata"]["name"] == "shared"][0]["data"]["shared.yaml"]
    # ONE mapping key, not two. A duplicate would still parse here — PyYAML takes the
    # last — so the count is asserted on the TEXT, which is what `serde_yaml` reads.
    assert rendered.count("tlsRotation:") == 1, rendered
    parsed = yaml.safe_load(rendered)
    assert parsed["tlsRotation"]["pollSeconds"] == 30
    assert parsed["tlsRotation"]["splayMaxSeconds"] == 300
    assert "pollSeconds: 30\n" in rendered
    assert "splayMaxSeconds: 300\n" in rendered


def test_the_same_declaration_with_the_line_still_in_the_chart_is_refused(tmp_path):
    """THE RED PAIR, and the rule the merge does NOT relax. Per leaf is still one
    source per leaf: `tlsRotation.pollSeconds` declared consequential while
    `chart/config/shared.yaml` still carries it is two writers for one value, and the
    template refuses it naming the knob and the file.

    This is the nested-path case; `test_a_knob_declared_consequential_and_also_in_chart_config_is_refused`
    above is the same fault one level up.
    """
    copy = chart_copy(tmp_path, declare=SIBLING_DECLARE, schema_properties=SIBLING_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text("shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "tlsRotation.pollSeconds" in result.stderr
    assert "shared.yaml" in result.stderr


# ------------------------------------------------------- the ways it must refuse


# THE SAME KNOB WITH A DELIBERATELY LOOSE SCHEMA. `FIXTURE_SCHEMA` types the leaf
# as a non-empty string, so the schema refuses null and `""` before the template
# is reached — which means a case built on it proves the SCHEMA and says nothing
# about the template. The two cases below are about what the template refuses when
# the schema does not, so they use a schema that permits both. A future declaring
# pull request can write a loose property for a genuinely free-form knob, and the
# `required` guard is what stands behind it then.
PERMISSIVE_SCHEMA = {
    "audit": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "archive": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"bucketName": {}},
            }
        },
    }
}


def test_an_explicit_null_is_refused_rather_than_merged_in(tmp_path):
    """`hasKey` IS NOT ENOUGH. A key present with no value walks the dotted path
    successfully, and merging it would write `bucketName: null` into the
    ConfigMap — a value nobody chose, which is the whole class ADR-0569 exists to
    delete. Helm's `required` is what closes it, and this case is what keeps it
    there when the schema is not tight enough to have caught it first.
    """
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=PERMISSIVE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text("audit:\n  archive:\n    bucketName:\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "archive.bucketName" in result.stderr


def test_an_empty_string_is_refused(tmp_path):
    """Helm's `required` treats an empty string as absent, and so does this."""
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=PERMISSIVE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text('audit:\n  archive:\n    bucketName: ""\n')
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "archive.bucketName" in result.stderr


def test_a_tight_schema_refuses_null_one_layer_earlier(tmp_path):
    """BOTH LAYERS, and they are reached by different paths. The schema is what an
    adopter meets in `helm lint`; `required` is what holds when a property is
    loose. Neither is the other's substitute.
    """
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text("audit:\n  archive:\n    bucketName:\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "specifications of the schema" in result.stderr


def test_a_declared_stem_with_no_document_is_refused(tmp_path):
    """A DECLARATION NOTHING RENDERS is the silent no-op one level up: the adopter
    states the value, the schema accepts it, and no ConfigMap carries it.
    """
    copy = chart_copy(
        tmp_path,
        declare={"nosuchservice": ["a.b"]},
        schema_properties={
            "nosuchservice": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "a": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"b": {"type": "string"}},
                    }
                },
            }
        },
    )
    values = tmp_path / "values.yaml"
    values.write_text("nosuchservice:\n  a:\n    b: x\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "nosuchservice" in result.stderr


def test_a_partly_stated_path_is_refused(tmp_path):
    """The parent set and the leaf absent is a half-finished edit, not a value."""
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text("audit:\n  archive: {}\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "archive.bucketName" in result.stderr


def test_a_knob_declared_consequential_and_also_in_chart_config_is_refused(tmp_path):
    """RULE 1, AT RENDER TIME. ADR-0705 amends ADR-0569 on the ORIGIN of a value
    only, so one-knob-one-source stands: a consequential knob is ABSENT from
    `chart/config/`. Appending a top-level key the copied document already has
    would emit a duplicate mapping key, which is a document `serde_yaml` rejects —
    so the reader would refuse to boot on a ConfigMap that rendered cleanly.

    `scripts/one_source_per_knob.py` refuses this at commit time. This case is the
    render-time backstop, so the fault cannot reach a cluster by way of a gate
    somebody edited.
    """
    copy = chart_copy(
        tmp_path,
        declare={"audit": ["audit.retentionDays"]},
        schema_properties={
            "audit": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "audit": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"retentionDays": {"type": "integer"}},
                    }
                },
            }
        },
    )
    values = tmp_path / "values.yaml"
    values.write_text("audit:\n  audit:\n    retentionDays: 30\n")
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "audit.yaml" in result.stderr


def test_an_undeclared_key_is_still_refused_when_a_knob_is_declared(tmp_path):
    """config#15's BEHAVIOUR MUST SURVIVE THE INTERFACE. Opening the schema for one
    knob must not open it for anything else — a key with no reader is still the
    silent no-op, and `additionalProperties: false` at every level is what keeps
    refusing it.
    """
    copy = chart_copy(tmp_path, declare=FIXTURE_DECLARE, schema_properties=FIXTURE_SCHEMA)
    values = tmp_path / "values.yaml"
    values.write_text(
        "audit:\n  archive:\n    bucketName: yadgar-audit-archive\n"
        "shared:\n  tlsRotation:\n    pollSeconds: 30\n"
    )
    result = helm("template", "ci-render", str(copy), "-f", str(values))
    assert result.returncode != 0
    assert "shared" in result.stderr


# ------------------------------- what declaring nothing must cost: nothing at all


def test_declaring_nothing_renders_the_baseline_byte_for_byte():
    """THE GATE ON THIS WHOLE CHANGE. The shipped list is empty, so the values
    layering must be inert: one rendered byte different means it leaks into the
    defaulted path, and the leak would be discovered at `yadgarhq/deploy`'s sync
    wave -12, ahead of every module.
    """
    assert render_sha256(str(CHART)) == BASELINE_SHA256


def test_the_example_values_file_changes_nothing():
    """`example/values.yaml` SAYS no knob requires a value today, and this is what
    makes that claim checked rather than asserted. An adopter who copies it gets
    exactly the pinned chart's own render.
    """
    assert (
        render_sha256(str(CHART), "-f", str(REPO / "example" / "values.yaml"))
        == BASELINE_SHA256
    )


def test_the_shipped_declaration_list_is_empty():
    """MUTATION TRIPWIRE. `test_declaring_nothing_renders_the_baseline_byte_for_byte`
    above would also pass if the layering were deleted outright, and it would pass
    if a knob were declared whose merge happened to render identically. This case
    pins the input the baseline claim is about.
    """
    import yaml

    declared = yaml.safe_load((CHART / "consequential.yaml").read_text())
    assert declared in (None, {}), declared


def test_the_shipped_chart_still_renders_with_no_values_at_all():
    """UPSTREAM CAN RENDER ITS OWN CHART, which is true only while the list is empty.

    The `helm lint` pre-commit hook and `ci / passed` both render with no values.
    The day a knob is declared they must be given `example/values.yaml` instead,
    and this case is where that transition announces itself.
    """
    result = helm("template", "ci-render", str(CHART))
    assert result.returncode == 0, result.stderr
    result = helm("lint", "--strict", str(CHART))
    assert result.returncode == 0, result.stdout + result.stderr

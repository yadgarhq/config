"""What `one_source_per_knob.py` asserts, pinned so it cannot quietly stop asserting it.

THIS GATE HAD NO TEST AT ALL (ledger 625), which is the shape that matters
rather than an oversight to log. It is the only thing standing between this
repository and a knob defined twice, and a knob defined twice is a value
assembled from two layers that nobody wrote and nobody can attribute — the
single-writer failure D4 exists to prevent, failing SILENTLY because both files
look authoritative. A gate guarding that, guarded by nothing, is one refactor
away from being a green tick that checks nothing.

MOST OF THIS FILE DEMANDS A REFUSAL, and that is the rule this estate applies to
its own gates: a gate is proven by a demanded finding, not by a passing run. A
suite that only fed conforming input would pass whether the script worked or
not — it would certify the fixture instead of the gate, which is the antipattern
measured six times in this estate now. So every refusal the script's docstring
claims has a case here that requires it, and the suite goes red the day the
script stops refusing.

`CONFIG` IS A RELATIVE PATH resolved when the script runs, so each case lays out
a `chart/config/` under `tmp_path` and runs the gate there. Nothing is
monkeypatched and the script needs no argument it does not already have.

Run: python3 -m pytest scripts/tests/ -q
"""

import json
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "one_source_per_knob.py"
REPO = Path(__file__).resolve().parents[2]


def declare(root: Path, declaration, schema_properties=None, *, closed=True):
    """Write ADR-0705's second source: the declaration list and the schema.

    `declaration` is written verbatim when it is a string, so a case can plant a
    malformed one. Otherwise it is dumped as JSON, which every YAML parser reads.

    `schema_properties` defaults to a schema DERIVED from the declaration, so a
    case about one rule does not trip the agreement rule by accident. The cases
    about the agreement pass their own.
    """
    chart = root / "chart"
    chart.mkdir(parents=True, exist_ok=True)
    if isinstance(declaration, str):
        (chart / "consequential.yaml").write_text(declaration)
        parsed = {}
    else:
        (chart / "consequential.yaml").write_text(json.dumps(declaration or {}) + "\n")
        parsed = declaration or {}

    if schema_properties is None:
        schema_properties = {}
        for stem, knobs in parsed.items():
            node = schema_properties.setdefault(
                stem, {"type": "object", "additionalProperties": False, "properties": {}}
            )
            for knob in knobs if isinstance(knobs, list) else []:
                cursor = node
                segments = str(knob).split(".")
                for segment in segments[:-1]:
                    cursor = cursor["properties"].setdefault(
                        segment,
                        {"type": "object", "additionalProperties": False, "properties": {}},
                    )
                cursor["properties"][segments[-1]] = {}
    (chart / "values.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": not closed,
                "properties": schema_properties,
            },
            indent=2,
        )
        + "\n"
    )
    return root


def layout(tmp_path: Path, **files):
    """Write `chart/config/<name>.yaml` files and return the root to run in.

    A key of `a__yml` becomes `a.yml`, so a case can plant a stray extension.
    """
    directory = tmp_path / "chart" / "config"
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        stem = name.replace("__", ".")
        if "." not in stem:
            stem += ".yaml"
        (directory / stem).write_text(text)
    return tmp_path


def run(cwd: Path):
    return subprocess.run(
        [sys.executable, str(GATE)], capture_output=True, text=True, cwd=str(cwd)
    )


# ------------------------------------------ the collision this gate exists for


def test_the_same_knob_in_two_documents_is_refused(tmp_path):
    """THE DEFECT ITSELF. If this stops failing, the gate is gone."""
    root = layout(tmp_path, shared="logLevel: info\n", gateway="logLevel: debug\n")
    result = run(root)
    assert result.returncode == 1
    assert "`logLevel` is defined in 2 files" in result.stdout


def test_the_collision_message_names_both_files(tmp_path):
    """A refusal that does not say WHERE sends the reader back to grep."""
    root = layout(tmp_path, shared="logLevel: info\n", gateway="logLevel: debug\n")
    result = run(root)
    assert result.returncode == 1
    assert "chart/config/shared.yaml" in result.stdout
    assert "chart/config/gateway.yaml" in result.stdout


def test_a_collision_deep_in_a_tree_is_found(tmp_path):
    root = layout(
        tmp_path,
        shared="tls:\n  rotation:\n    every: 24h\n",
        iam="tls:\n  rotation:\n    every: 12h\n",
    )
    result = run(root)
    assert result.returncode == 1
    assert "`tls.rotation.every` is defined in 2 files" in result.stdout


def test_a_collision_across_three_files_names_all_three(tmp_path):
    root = layout(tmp_path, shared="a: 1\n", iam="a: 2\n", task="a: 3\n")
    result = run(root)
    assert result.returncode == 1
    assert "defined in 3 files" in result.stdout


# --------------------------------- the three ways a file is present and unread


def test_a_directory_holding_no_yaml_is_refused(tmp_path):
    """A GLOB THAT MATCHES NOTHING makes the whole gate a check that cannot fail."""
    (tmp_path / "chart" / "config").mkdir(parents=True)
    result = run(tmp_path)
    assert result.returncode == 1
    assert "holds no `*.yaml`" in result.stdout


def test_a_yml_extension_is_refused(tmp_path):
    """The chart globs `config/*.yaml`, so a `.yml` renders no ConfigMap."""
    root = layout(tmp_path, shared="logLevel: info\n", gateway__yml="timeout: 5s\n")
    result = run(root)
    assert result.returncode == 1
    assert "ends in `.yml`" in result.stdout


def test_a_stem_that_is_not_a_dns_1123_label_is_refused(tmp_path):
    """`helm lint` reports an invalid ConfigMap name as a WARNING and exits 0."""
    root = layout(tmp_path, shared="logLevel: info\n", Gateway_DB="timeout: 5s\n")
    result = run(root)
    assert result.returncode == 1
    assert "is not a DNS-1123 label" in result.stdout


def test_a_missing_config_directory_is_refused(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 1
    assert "does not exist" in result.stdout


def test_an_unparseable_document_is_refused(tmp_path):
    root = layout(tmp_path, shared="logLevel: info\n", gateway="a: [unclosed\n")
    result = run(root)
    assert result.returncode == 1
    assert "is not a YAML document" in result.stdout


def test_a_document_that_is_not_a_mapping_is_refused(tmp_path):
    root = layout(tmp_path, shared="logLevel: info\n", gateway="- a\n- b\n")
    result = run(root)
    assert result.returncode == 1
    assert "must be a mapping at the top level" in result.stdout


# ------------------------------------------ what is NOT a collision, and why

def test_a_shared_parent_is_not_a_collision(tmp_path):
    """LEAF, NOT EVERY NODE.

    `tls` appearing in two files is only a fault if a knob UNDER it does.
    Reporting the parent would point the reader at the wrong line.
    """
    root = layout(
        tmp_path,
        shared="tls:\n  rotation: 24h\n",
        iam="tls:\n  verify: true\n",
    )
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_two_lists_under_different_keys_do_not_collide(tmp_path):
    """A list's INDICES are not key paths."""
    root = layout(tmp_path, shared="hosts:\n  - a\n  - b\n", iam="peers:\n  - a\n  - b\n")
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_a_comments_only_document_is_a_file_waiting_for_its_first_knob(tmp_path):
    root = layout(tmp_path, shared="logLevel: info\n", gateway="# nothing yet\n")
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_a_conforming_tree_passes_and_the_finding_says_what_was_checked(tmp_path):
    root = layout(tmp_path, shared="logLevel: info\n", gateway="timeout: 5s\n")
    result = run(root)
    assert result.returncode == 0, result.stdout
    # A FINDING, never a bare pass: both counts are in it.
    assert "2 knobs, each defined once, across 2 files." in result.stdout


def test_this_repository_has_one_source_per_knob_today(tmp_path):
    """The real tree, not a fixture, so the suite is also the gate's own run."""
    result = run(REPO)
    assert result.returncode == 0, result.stdout


# ------------------------------- ADR-0705's SECOND source, and the rule across both
#
# A consequential knob comes from the ADOPTER's values file rather than from
# `chart/config/`, declared in `chart/consequential.yaml`. ADR-0705 amends ADR-0569
# on the ORIGIN of a value only and upholds one-knob-one-source, so the partition
# has to hold across BOTH sources — and `chart/config/` alone cannot see half of it.
# A gate that checked only the directory would read as full coverage while missing
# the newer half, which is worse than not checking at all.


def test_both_new_files_absent_means_nothing_is_declared(tmp_path):
    """ABSENCE IS NOT A FAULT, and every case above depends on it: they lay out
    `chart/config/` alone. Deleting the declaration is still not a way to switch
    this off quietly — the agreement check below refuses a schema that names a knob
    the declaration does not.
    """
    root = layout(tmp_path, shared="logLevel: info\n")
    result = run(root)
    assert result.returncode == 0, result.stdout
    assert "0 of them carry no default" in result.stdout


def test_the_same_knob_declared_and_also_in_chart_config_is_refused(tmp_path):
    """THE CROSS-SOURCE COLLISION, which is the whole reason this gate had to learn
    the second source. Two writers for one value, and `chart/config/` alone cannot
    see it.
    """
    root = layout(tmp_path, audit="retention:\n  days: 90\n")
    declare(root, {"audit": ["retention.days"]})
    result = run(root)
    assert result.returncode == 1
    assert "`retention.days` is defined in 2 files" in result.stdout
    assert "chart/consequential.yaml" in result.stdout
    assert "chart/config/audit.yaml" in result.stdout


def test_a_sibling_under_the_same_top_level_key_is_refused(tmp_path):
    """THE PARTITION IS BY TOP-LEVEL KEY, NOT BY LEAF, and this is the case that
    says so. There is no leaf collision here — `pollSeconds` is in one source and
    `splayMaxSeconds` in the other — but the chart APPENDS a top-level
    `tlsRotation:` mapping to a document that already has one, which emits a
    duplicate mapping key that `serde_yaml` refuses. So the first realistic
    consequential knob in this repository cannot be declared alone; both knobs
    under `tlsRotation` move or neither does.
    """
    root = layout(tmp_path, shared="tlsRotation:\n  splayMaxSeconds: 300\n")
    declare(root, {"shared": ["tlsRotation.pollSeconds"]})
    result = run(root)
    assert result.returncode == 1
    assert "`tlsRotation.pollSeconds` is declared consequential" in result.stdout
    assert "TOP-LEVEL KEY, not by leaf" in result.stdout
    # The message names the siblings, so the reader does not have to go and find
    # what else has to move.
    assert "tlsRotation.splayMaxSeconds" in result.stdout


def test_a_declared_stem_with_no_document_is_refused(tmp_path):
    """A DECLARATION NOTHING RENDERS. The adopter states the value, the schema
    accepts it, and no ConfigMap carries it.
    """
    root = layout(tmp_path, shared="logLevel: info\n")
    declare(root, {"nosuchservice": ["a.b"]})
    result = run(root)
    assert result.returncode == 1
    assert "does not exist" in result.stdout
    assert "nosuchservice" in result.stdout


def test_a_declared_knob_with_no_schema_property_is_refused(tmp_path):
    """THE SCHEMA IS CLOSED, so a knob declared and not typed is refused by helm
    before the template runs — the adopter meets a schema error about the key
    upstream told them to set.
    """
    root = layout(tmp_path, audit="# nothing yet\n")
    declare(root, {"audit": ["archive.bucketName"]}, schema_properties={})
    result = run(root)
    assert result.returncode == 1
    assert "declares no property for it" in result.stdout
    assert "audit.archive.bucketName" in result.stdout


def test_a_schema_property_with_no_declaration_is_refused(tmp_path):
    """THE OPPOSITE FAULT, and the worse one: the schema blesses a value and
    nothing appends it. That is the silent no-op the schema was closed to delete,
    reintroduced by the file that closed it.
    """
    root = layout(tmp_path, audit="# nothing yet\n")
    declare(
        root,
        {},
        schema_properties={
            "audit": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"retentionDays": {"type": "integer"}},
            }
        },
    )
    result = run(root)
    assert result.returncode == 1
    assert "audit.retentionDays" in result.stdout
    assert "silent no-op" in result.stdout


def test_a_schema_that_stops_being_closed_is_refused(tmp_path):
    """config#15's BEHAVIOUR IS NOT TRADED FOR THE INTERFACE. Opening the schema
    for one knob must not open it for everything, and `additionalProperties: false`
    is the whole of that rule.
    """
    root = layout(tmp_path, shared="logLevel: info\n")
    declare(root, {}, closed=False)
    result = run(root)
    assert result.returncode == 1
    assert "additionalProperties: false" in result.stdout


def test_a_declaration_that_is_not_a_mapping_is_refused(tmp_path):
    root = layout(tmp_path, shared="logLevel: info\n")
    declare(root, "- audit\n- shared\n")
    result = run(root)
    assert result.returncode == 1
    assert "must be a mapping of config-file stem" in result.stdout


def test_a_declared_stem_with_an_empty_list_is_refused(tmp_path):
    """AN EMPTY KEY IS NOT A DECLARATION. It reads as one and declares nothing, so
    the honest form is to delete the key.
    """
    root = layout(tmp_path, audit="# nothing yet\n")
    declare(root, "audit: []\n")
    result = run(root)
    assert result.returncode == 1
    assert "non-empty LIST" in result.stdout


def test_a_knob_that_is_not_a_dotted_path_is_refused(tmp_path):
    root = layout(tmp_path, audit="# nothing yet\n")
    declare(root, "audit:\n  - 90\n")
    result = run(root)
    assert result.returncode == 1
    assert "not a dotted knob path" in result.stdout


def test_a_conforming_declaration_passes_and_is_counted(tmp_path):
    """THE GREEN CASE FOR THE SECOND SOURCE, paired with every refusal above. The
    knob is absent from `chart/config/` and typed in the schema, which is exactly
    what a real declaring pull request does.
    """
    root = layout(tmp_path, audit="# no knob lives here\n", shared="logLevel: info\n")
    declare(root, {"audit": ["archive.bucketName"]})
    result = run(root)
    assert result.returncode == 0, result.stdout
    assert "2 knobs, each defined once, across 2 files." in result.stdout
    assert "1 of them carry no default" in result.stdout


def test_this_repository_declares_nothing_consequential_today(tmp_path):
    """THE SHIPPED POSTURE, pinned. The declaration list is empty because all four
    knobs keep their default — the classification is in the README under "Blast
    radius", and this is where a line added without reading it shows up.
    """
    result = run(REPO)
    assert result.returncode == 0, result.stdout
    assert "0 of them carry no default" in result.stdout

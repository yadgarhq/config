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

import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "one_source_per_knob.py"
REPO = Path(__file__).resolve().parents[2]


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

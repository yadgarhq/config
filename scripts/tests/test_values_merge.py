"""What an adopter's values file does to a rendered document, and what it must not do.

ADR-0721: each ConfigMap is rendered from a DEEP MERGE of this chart's own
`config/<stem>.yaml` under the adopter's `.Values.<stem>`, so any knob is settable
from the adopter's own repository in one line. The merge is PER DOCUMENT and it is
the ruling rather than an optimisation:

  - A document with NO override is still copied VERBATIM, and its comments still
    reach the cluster.
  - A document WITH an override is re-emitted from the merged data and LOSES its
    comments.

Both halves are asserted here, on the same render, because either one alone is
satisfied by a mechanism that is wrong. Verbatim-always is the state ADR-0721
rejected — an adopter could change nothing. Merge-always would take the comments
off every document to override one, which is the loss ADR-0721 accepts only
where it must.

WHY A VALUES FILE RATHER THAN `--set` in most cases here: an adopter commits a
file and Argo passes a file, and the two paths are not the same code. `--set`
parses through helm's `strvals` and yields an int64; a values file goes through
`sigs.k8s.io/yaml`, which converts to JSON first, so every number arrives as a
float64. A ConfigMap carrying `pollSeconds: 30.0` renders cleanly and `serde_yaml`
then refuses it for a `u64`, so the reader fails to boot on a document a
parse-only assertion called green. The assertions below are on the rendered BYTES
as well as on the parsed value for exactly that reason.

Run: python3 -m pytest scripts/tests/ -q
"""

import shutil
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "chart"
CONFIG = CHART / "config"

STEMS = sorted(path.stem for path in CONFIG.glob("*.yaml"))


def helm(*arguments: str):
    binary = shutil.which("helm")
    # NOT A SKIP, and ADR-0650 is why — see `test_required_knob.py`. A suite that
    # skips when its subject is absent reports a pass nobody earned.
    assert binary, (
        "helm is not on PATH. This suite renders the chart, and so does the "
        "`helm lint and render` pre-commit hook — install helm rather than "
        "letting either report a pass it did not earn."
    )
    return subprocess.run([binary, *arguments], capture_output=True, text=True)


def render(tmp_path: Path, values: str | None = None, *arguments: str) -> dict[str, str]:
    """The rendered documents as stem -> the text of `data.<stem>.yaml`."""
    command = ["template", "ci-render", str(CHART), *arguments]
    if values is not None:
        path = tmp_path / "values.yaml"
        path.write_text(values)
        command += ["-f", str(path)]
    result = helm(*command)
    assert result.returncode == 0, result.stderr
    rendered = {}
    for document in yaml.safe_load_all(result.stdout):
        if not document:
            continue
        name = document["metadata"]["name"]
        rendered[name] = document["data"][f"{name}.yaml"]
    return rendered


def comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


# ------------------------------------------------- the override actually lands


def test_an_override_reaches_the_data_as_an_INTEGER(tmp_path):
    """ADR-0721's whole point: one line in the adopter's own repository.

    THREE ASSERTIONS AND NONE IS REDUNDANT. The parsed value is what the reader
    means; the literal bytes are what the reader gets, and `30.0` parses equal to
    `30` in Python while `serde_yaml` refuses it for a `u64`; the type check
    catches the same fault from the other side.
    """
    rendered = render(tmp_path, "shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    document = yaml.safe_load(rendered["shared"])
    assert document["tlsRotation"]["pollSeconds"] == 30
    assert isinstance(document["tlsRotation"]["pollSeconds"], int)
    assert "pollSeconds: 30\n" in rendered["shared"]


def test_the_unstated_sibling_keeps_the_charts_default(tmp_path):
    """A DEEP merge, not a replacement. The adopter states one leaf and inherits
    the rest of the document — which is what makes this not the whole-document
    replacement ADR-0721 rejected, where they restate every knob and stop
    receiving upstream's improvements to it.
    """
    rendered = render(tmp_path, "shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    document = yaml.safe_load(rendered["shared"])
    assert document["tlsRotation"]["splayMaxSeconds"] == 300
    assert isinstance(document["tlsRotation"]["splayMaxSeconds"], int)
    assert "splayMaxSeconds: 300\n" in rendered["shared"]


def test_an_explicit_zero_wins_over_the_default(tmp_path):
    """ZERO IS A VALUE, and this is the case that pins it.

    `splayMaxSeconds: 0` means exit at once and `chart/config/shared.yaml` says so
    in those words. A merge that treated a zero as "unset" would hand the adopter
    300 while they read 0 in their own file — the effective-value-depends-on-the-
    layer failure ADR-0569 exists to delete. Sprig's `mergeOverwrite` delegates
    this to mergo's notion of an empty value, which is why the chart carries its
    own recursive merge rather than borrowing that one.
    """
    rendered = render(tmp_path, "shared:\n  tlsRotation:\n    splayMaxSeconds: 0\n")
    document = yaml.safe_load(rendered["shared"])
    assert document["tlsRotation"]["splayMaxSeconds"] == 0
    assert "splayMaxSeconds: 0\n" in rendered["shared"]
    assert document["tlsRotation"]["pollSeconds"] == 60


def test_a_knob_nested_under_its_own_stem_name_lands(tmp_path):
    """`audit.audit.retentionDays` — the stem and the top-level key are both
    `audit`, which is the shape most likely to be got wrong by one level.
    """
    rendered = render(tmp_path, "audit:\n  audit:\n    retentionDays: 30\n")
    document = yaml.safe_load(rendered["audit"])
    assert document["audit"]["retentionDays"] == 30
    assert "retentionDays: 30\n" in rendered["audit"]


def test_the_same_override_through_set_lands_identically(tmp_path):
    """BOTH INPUT PATHS. `--set` parses through `strvals` and a values file through
    `sigs.k8s.io/yaml`; an Argo `helm.parameters` block is the former and a
    `valueFiles` entry the latter, so an installation can meet either.
    """
    by_file = render(tmp_path, "shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    by_set = render(tmp_path, None, "--set", "shared.tlsRotation.pollSeconds=30")
    assert by_set["shared"] == by_file["shared"]


# --------------------------------- the per-document split, both halves at once


def test_a_document_with_no_override_stays_BYTE_VERBATIM(tmp_path):
    """ADR-0721's per-document split, the half that keeps what still pays.

    `audit.yaml` is mostly the reasoning for its number, and `kubectl get cm audit
    -o yaml` is where somebody debugging at 3am reads it. Overriding a knob in
    `shared.yaml` must not cost that.
    """
    rendered = render(tmp_path, "shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    assert rendered["audit"] == (CONFIG / "audit.yaml").read_text()


def test_every_document_but_the_overridden_one_is_byte_verbatim(tmp_path):
    """The split is per document, so every OTHER one is untouched — asserted
    across all of them rather than on one sample, because a merge that ran
    unconditionally would still pass a single-document check on a document whose
    merge happened to be a no-op.
    """
    rendered = render(tmp_path, "shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    for stem in STEMS:
        if stem == "shared":
            continue
        assert rendered[stem] == (CONFIG / f"{stem}.yaml").read_text(), stem


def test_the_overridden_document_LOSES_its_comments(tmp_path):
    """THE COST, ASSERTED RATHER THAN REGRETTED. ADR-0721 accepts it deliberately:
    an overridden document is re-emitted from the merged data, so its reasoning no
    longer reaches the cluster and lives in the pinned chart the adopter can read.

    This case is also the red pair for the one above. A mechanism that copied every
    document verbatim would pass that one and fail this one — and that mechanism is
    the state ADR-0721 exists to delete, where an adopter can change nothing.
    """
    rendered = render(tmp_path, "shared:\n  tlsRotation:\n    pollSeconds: 30\n")
    assert comment_lines(CONFIG / "shared.yaml" and (CONFIG / "shared.yaml").read_text())
    assert comment_lines(rendered["shared"]) == []


def test_with_no_values_every_document_is_byte_verbatim(tmp_path):
    """GATE 1 IN PER-DOCUMENT FORM. With nothing supplied there is nothing to
    merge, so every document is the copy it always was.

    `test_required_knob.py::test_declaring_nothing_renders_the_baseline_byte_for_byte`
    pins the whole render against a sha256 taken before the merge existed. This
    case says WHICH bytes, so a future failure of that one names a document instead
    of a hash.
    """
    rendered = render(tmp_path)
    for stem in STEMS:
        assert rendered[stem] == (CONFIG / f"{stem}.yaml").read_text(), stem


def test_chart_values_yaml_carries_no_default(tmp_path):
    """MUTATION TRIPWIRE for the two cases above, and it is not a style rule.

    A knob written into `chart/values.yaml` is supplied for every installation, so
    `.Values.<stem>` is non-empty with nothing overridden — every document would be
    re-emitted, every comment lost, and the byte-identity gate would fail on a
    change nobody made. The chart's defaults live in `chart/config/`, which is also
    ADR-0569's one-source rule.
    """
    assert yaml.safe_load((CHART / "values.yaml").read_text()) in (None, {})


# ------------------------------------- a typo is still refused, not absorbed


def test_an_unknown_top_level_key_is_refused_by_the_template(tmp_path):
    """The merge opens the four knobs the chart knows and nothing else. A key the
    schema does not declare is REFUSED rather than merged into a document as a
    setting no reader opens.
    """
    result = helm("template", "ci-render", str(CHART), "--set", "foo=bar")
    assert result.returncode != 0
    assert "foo" in result.stderr


def test_an_unknown_top_level_key_is_refused_by_the_lint(tmp_path):
    """BOTH GATES. `helm lint --strict` is the `helm lint and render` pre-commit
    hook and therefore `ci / passed`; `helm template` is what Argo runs.
    """
    result = helm("lint", "--strict", str(CHART), "--set", "foo=bar")
    assert result.returncode != 0
    assert "foo" in result.stdout + result.stderr


def test_a_typo_in_a_declared_knob_is_refused(tmp_path):
    """THE PLAUSIBLE MISTAKE, not the implausible one. Nobody sets `foo`; somebody
    sets `pollSecond`. `additionalProperties: false` at EVERY level is what makes
    that a refusal naming the key rather than a value merged in beside the real
    one, where both look set and only one is read.
    """
    result = helm(
        "template", "ci-render", str(CHART), "--set", "shared.tlsRotation.pollSecond=30"
    )
    assert result.returncode != 0
    assert "pollSecond" in result.stderr


def test_a_knob_under_the_wrong_stem_is_refused(tmp_path):
    """`audit.tlsRotation.pollSeconds` is a real knob under the wrong document.
    The stem is part of the knob's address, and a merge that ignored it would write
    a `tlsRotation` block into `audit.yaml` that nothing reads.
    """
    result = helm(
        "template", "ci-render", str(CHART), "--set", "audit.tlsRotation.pollSeconds=30"
    )
    assert result.returncode != 0
    assert "tlsRotation" in result.stderr


def test_a_string_where_the_schema_wants_an_integer_is_refused(tmp_path):
    """TYPED, not merely named. `pollSeconds: "30"` would reach `serde_yaml` as a
    string and fail the reader at boot; the schema refuses it at render.
    """
    result = helm(
        "template", "ci-render", str(CHART), "--set-string", "shared.tlsRotation.pollSeconds=30"
    )
    assert result.returncode != 0
    assert "pollSeconds" in result.stderr

"""What `chart/values.schema.json` refuses, and why a closed schema stays the honest one.

THIS CHART NOW READS A HELM VALUE, FOR EXACTLY THE KNOBS `chart/consequential.yaml`
DECLARES — AND THAT LIST IS EMPTY. So every key an adopter sets in a values file, in
an Argo Application's `helm.parameters`, or with `--set` is still read by nobody
today, and is still REFUSED rather than dropped. `test_required_knob.py` covers the
interface itself, against a chart copy that declares a knob; this file covers the
closed schema that keeps everything else out.

THE SILENCE IS THE DEFECT THIS SCHEMA DELETES, and it is ADR-0569's own failure one
layer out — a value whose effect depends on which layer you inspect, with nothing
anywhere saying the number was dropped. Up to chart 0.1.1 `helm template -f
override.yaml` rendered byte-identically to no override, exit 0, no warning. An
empty `properties` with `additionalProperties: false` turns that into a refusal
naming the key.

THE INTERFACE DID NOT BUY ITS WAY PAST THAT. `additionalProperties: false` stays, at
every level, and a typed property is added only for a knob the declaration list
names — otherwise the schema would PASS an adopter's value and the chart would then
ignore it, which is validation blessing inert input. The two files opening together,
knob by knob, is what `scripts/one_source_per_knob.py` enforces, and the last case
here is this file's half of it.

Run: python3 -m pytest scripts/tests/ -q
"""

import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "chart"
SCHEMA = CHART / "values.schema.json"


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


def test_the_chart_renders_with_no_values():
    """THE NORMAL CASE, and the one a closed schema could plausibly break.

    Argo passes nothing: `yadgarhq/deploy`'s `infra/config-app.yaml` declares no
    `helm:` block at all, so the live sync renders exactly this.
    """
    result = helm("template", "ci-render", str(CHART))
    assert result.returncode == 0, result.stderr


def test_a_value_the_chart_cannot_read_is_refused_rather_than_ignored():
    """THE REFUSAL ITSELF. If this stops failing, an adopter's value is silent again.

    `tlsRotation.pollSeconds` is a REAL knob name, deliberately: the plausible
    mistake is not a typo, it is setting the knob in the one place a Helm chart
    normally takes settings from. Asserting on the key rather than on helm's
    wording, because helm 3 and helm 4 word it differently and only the key is
    this repository's to own.
    """
    result = helm("template", "ci-render", str(CHART), "--set", "tlsRotation.pollSeconds=30")
    assert result.returncode != 0
    assert "tlsRotation" in result.stderr


def test_the_lint_refuses_it_too():
    """BOTH GATES, because they are reached by different paths.

    `helm lint --strict` is the `helm lint and render` hook and therefore `ci /
    passed`; `helm template` is what Argo runs. A schema enforced by only one of
    them would be a gate an adopter never meets.
    """
    result = helm("lint", "--strict", str(CHART), "--set", "audit.retentionDays=7")
    assert result.returncode != 0
    assert "audit" in result.stdout + result.stderr


def test_the_schema_declares_exactly_the_knobs_the_chart_reads():
    """A TYPED KNOB THE CHART DOES NOT READ WOULD BLESS A VALUE IT IGNORES, and a
    knob the chart reads with no property here is refused before the template runs.

    So the assertion is the AGREEMENT rather than emptiness: `properties` names
    exactly what `chart/consequential.yaml` declares. Today both are empty and the
    refusals above hold for every key; the day a knob is declared this case follows
    it rather than having to be deleted, which is what stops the tempting edit —
    "documenting" the knobs here — from quietly converting a refusal into a rubber
    stamp. `scripts/one_source_per_knob.py` enforces the same agreement at commit
    time, in both directions and per dotted path.
    """
    import yaml

    schema = json.loads(SCHEMA.read_text())
    assert schema["additionalProperties"] is False

    declared = yaml.safe_load((CHART / "consequential.yaml").read_text()) or {}
    assert set(schema["properties"]) == set(declared)


def test_the_closed_schema_is_what_refuses_a_key_with_no_reader():
    """MUTATION TRIPWIRE for the case above, which passes when both sides are empty
    and would therefore also pass if `additionalProperties` were dropped and the
    agreement held vacuously. This pins the state the refusals above depend on.
    """
    schema = json.loads(SCHEMA.read_text())
    assert schema["properties"] == {}, (
        "A knob is declared as a value. That is allowed by ADR-0705 — but it makes "
        "this chart unable to render itself bare, so `helm lint` and `ci / passed` "
        "must be given `example/values.yaml`, and `test_required_knob.py`'s "
        "`test_the_shipped_chart_still_renders_with_no_values_at_all` is the case "
        "to read first."
    )

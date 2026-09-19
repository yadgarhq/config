"""What `chart/values.schema.json` refuses, and why a closed schema is the honest one.

THE CHART READS NO HELM VALUES AT ALL. `chart/templates/configmap.yaml` copies
`config/*.yaml` out of the chart's own files with `.Files.Get`, and nothing in
`chart/` references `.Values` — measured, not assumed: `grep -rn '\\.Values'
chart/` finds nothing. So a key an adopter sets in a values file, in an Argo
Application's `helm.parameters`, or with `--set` was READ BY NOBODY and reported
as a success: `helm template -f override.yaml` rendered byte-identically to no
override, exit 0, no warning.

THAT SILENCE IS THE DEFECT THIS SCHEMA DELETES, and it is ADR-0569's own failure
one layer out — a value whose effect depends on which layer you inspect, with
nothing anywhere saying the number was dropped. An empty `properties` with
`additionalProperties: false` turns it into a refusal naming the key.

A SCHEMA THAT DECLARED THE KNOBS WOULD BE WORSE THAN NONE. `tlsRotation.
pollSeconds` as a typed property would PASS an adopter's value and the chart
would then ignore it — validation blessing inert input, which reads as
confirmation that the value took effect. The knobs are not values, so they are
not in this schema, and the pull request that teaches the chart to read values is
the one that puts them there.

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


def test_the_schema_declares_no_knob_as_a_value():
    """A TYPED KNOB HERE WOULD BLESS A VALUE THE CHART IGNORES.

    The refusal above holds only while `properties` stays empty and the schema
    stays closed, and the tempting edit is to "document" the knobs by adding
    them. Demanded explicitly so that edit fails a test rather than quietly
    converting a refusal into a rubber stamp.
    """
    schema = json.loads(SCHEMA.read_text())
    assert schema["additionalProperties"] is False
    assert schema["properties"] == {}

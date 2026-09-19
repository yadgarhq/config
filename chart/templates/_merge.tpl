{{- /*
A DEEP MERGE THIS CHART OWNS, rather than sprig's `mergeOverwrite`.

`config.deepMerge` takes `base` and `over` as dicts and returns the merged
document as YAML text. A key present in both and holding a map in both recurses;
anything else the `over` side states REPLACES what `base` says. So an adopter
states one leaf and inherits the rest of the document, which is ADR-0721's whole
point — a whole-document replacement would make them restate every knob and stop
receiving upstream's improvements to it.

WHY NOT `mergeOverwrite`, WHICH IS ONE LINE. Its behaviour for a zero, a `false`
and an empty string is mergo's notion of an "empty" value rather than helm's
documented contract, and the adopter's own helm — or Argo's bundled one — is what
decides which mergo this chart gets. `splayMaxSeconds: 0` MEANS exit at once and
`chart/config/shared.yaml` says so in those words, so a merge that read 0 as
"unset" would hand an installation 300 while the operator reads 0 in their own
file: the effective-value-depends-on-the-layer failure ADR-0569 exists to delete.
Measured identical on helm 3.18.4, 3.20.2 and 4.2.3 today — the recursion is what
keeps it identical on the version this chart has not met yet.
`test_values_merge.py::test_an_explicit_zero_wins_over_the_default` is the case.

THE ROUND TRIP IS PER NESTING LEVEL, and it is what `include` costs: a named
template returns a string, so the recursive call is re-parsed by `fromYaml`. An
integer survives it — asserted on the rendered BYTES rather than on a parsed
value, because a values file reaches helm through `sigs.k8s.io/yaml` as a float64
and `pollSeconds: 30.0` is a ConfigMap `serde_yaml` refuses for a `u64` while
Python reads it as equal to 30.

THIS FILE RENDERS NOTHING. A template whose name starts with `_` emits no
manifest, so adding it did not change one rendered byte — checked against the
pinned sha256 on its own commit, before the merge was wired up.
*/ -}}
{{- define "config.deepMerge" -}}
{{- $out := dict -}}
{{- range $key, $value := .base }}
{{-   $out = set $out $key $value }}
{{- end }}
{{- range $key, $value := .over }}
{{-   if and (hasKey $out $key) (kindIs "map" (index $out $key)) (kindIs "map" $value) }}
{{-     $out = set $out $key (fromYaml (include "config.deepMerge" (dict "base" (index $out $key) "over" $value))) }}
{{-   else }}
{{-     $out = set $out $key $value }}
{{-   end }}
{{- end }}
{{- toYaml $out -}}
{{- end -}}

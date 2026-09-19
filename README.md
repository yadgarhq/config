# yadgar/config

The configuration a yadgar installation reads at boot.

**An installation clones nothing and forks nothing** (ADR-0705, ADR-0721). Upstream publishes this chart as a versioned OCI artifact, an organisation's own GitOps repository pins a version, and an upgrade is a version bump — see "Adopting this in your own installation" below. The DEFAULTS live here, in `chart/config/`: every setting is a line you can see, in a file you can diff, with the reasoning for its starting value written next to it. An installation changes any one of them from its OWN repository, in one line, because each ConfigMap is rendered from a deep merge of the chart's document under that installation's values.

It is a **Helm chart that renders ConfigMaps** and nothing else — no controller, no loader, no API. ADR-0570: where a capability can be expressed as a Helm chart, it is expressed as one, so configuration reuses the sync, the review gate, the rollback and the audit trail the estate already runs.

## The rule this exists to hold

**A configuration knob is read from this repository and from nowhere else** — no compiled-in default, no system-level fallback, no last-resort constant (ADR-0569). A knob this repository does not define makes the owning process refuse to start, naming the knob and the file it was looked for in.

That rule is only workable because of its other half: **this repository ships with working values in it.** Ninety days for audit retention, sixty seconds for the rotation poll. An operator inherits a stated choice and edits it, rather than deriving a number from nothing.

The failure it deletes is specific and this estate has met it: a default compiled into a binary is invisible at the point of use, survives an upgrade unnoticed, and makes the effective setting depend on which layer you happen to inspect. Until 2026-09-05 `yadgar-lifecycle` fell back to `DEFAULT_POLL = 60s` and `DEFAULT_SPLAY_MAX = 300s` when nothing set them, and an installation could run both for a year with nothing anywhere saying so.

## What this is NOT

**It is not D35's seed repository.** That one loads prompts, help pages and starter memories into a module's DATABASE at install time, through a loader that does not exist yet. This repository writes no rows, runs no job, and touches no database. The two get confused because both are described as "a repository an installation clones", so: if it ends up in a table, it is D35's and it is unbuilt; if it ends up in a ConfigMap a process reads at boot, it is this one.

**It is not a configuration service, and none is planned** (ADR-0570). Two mechanisms cover configuration between them and a third is not added:

| what                            | where it lives                           | read when   |
| ------------------------------- | ---------------------------------------- | ----------- |
| deployment configuration        | this repository, as a mounted ConfigMap  | at boot     |
| per-organisation runtime policy | ADR-0522's inherited setting in `iam-db` | per request |

A third mechanism would put one concept in two places, which is the single-writer failure D4 exists to prevent.

**It never holds a secret.** This repository is PUBLIC and it is the thing operators clone, so anything secret in it is published. Credentials keep their existing homes: `yadgarhq/deploy`'s `infra/bootstrap` generates what it can (ADR-0517), and a data-bearing key is supplied by hand and deliberately never generated (ADR-0518). A knob whose value would be sensitive is a signal that it does not belong here at all — raise it rather than inventing a split.

## Layout

```
chart/Chart.yaml                the chart
chart/values.yaml               deliberately empty, and it must stay empty — see the file for why
chart/values.schema.json        every knob an installation may set, typed, and a refusal for every other key
chart/consequential.yaml        which knobs carry NO default at all — empty today
chart/templates/configmap.yaml  one ConfigMap per file below, named after the file
chart/templates/_merge.tpl      the deep merge that puts an installation's values over those files
chart/config/shared.yaml        knobs every service reads, with the same value in each
chart/config/gateway.yaml       knobs only `gateway` reads
chart/config/iam.yaml           ... and so on, one file per service
chart/config/iam-db.yaml
chart/config/project.yaml
chart/config/task.yaml
chart/config/task-db.yaml
chart/config/project-db.yaml     the project registry's — empty, and its first knob is D53's depth cap
chart/config/audit.yaml         the audit module's — designed, not built, nothing reads it
scripts/one_source_per_knob.py  the gate below
```

**One file per service, and a shared one.** A single document holding every service's settings is unnavigable — that judgement comes from having run one. The file name is the ConfigMap name, so `kubectl -n yadgar get cm iam-db -o yaml` answers "what is iam-db configured with" with no naming scheme to learn.

**Nothing enumerates the services.** `chart/templates/configmap.yaml` globs `config/*.yaml`, so adding a service is adding a file — the same property D54 buys for the module ApplicationSet one repository over.

**A document nobody overrides reaches the cluster byte for byte**, comments and all: `.Files.Get` copies the bytes and the template adds the indent a YAML block scalar requires and nothing else, so `kubectl -n yadgar get cm shared -o yaml` shows the reasoning beside the number. **A document an installation DOES override is re-emitted from the merged data and loses its comments** — the split is per document and it is ADR-0721's ruling rather than an optimisation. That is a real loss, accepted deliberately: comment preservation was a consequence of the operator editing these files, and under ADR-0705 they edit their own values file instead. The reasoning for an overridden knob still lives in the pinned chart version, which `helm template` prints.

### A knob lives in exactly one file

Either it is shared or it is per-service, never both. **There is no merge and no precedence** between `shared.yaml` and a service's own document.

D34 already states this for prompts — resolution replaces, it does not merge — and gives the reason: merging layers produces a value nobody wrote and nobody can attribute to a source. A knob present in two files is two writers for one value, and it fails silently, because both files look authoritative.

`scripts/one_source_per_knob.py` enforces it, as a pre-commit hook and therefore as part of `ci / passed`. If a knob genuinely needs a per-service override of a shared value, that is a design change to bring to the decision record, not something to reach by adding precedence.

**An installation's own values file is not a second source**, and the distinction is the whole of ADR-0705's amendment. It states a value for a knob this chart DEFINES; it cannot introduce one, because `chart/values.schema.json` refuses a key the chart does not declare. So there is still one place a knob is defined and one place its default is written. The gate checks the partition across both sources that can DEFINE a knob — `chart/config/` and `chart/consequential.yaml` — per leaf.

### Blast radius

Editing `gateway.yaml` restarts `gateway`. **Editing `shared.yaml` restarts everything that mounts it**, which is all six services — `gateway`, `iam`, `task`, `iam-db`, `task-db` and `project-db`. That is correct by construction and worth knowing before you edit: a change to a shared knob is a deliberate estate-wide roll, not a surprise.

**Configuration changes roll pods by design.** A value read at boot changes by the process being restarted onto it, and nobody should read that restart as a fault. The mechanism is ADR-0523's rotation watcher and it needed no new code: it already watches every file the process read at boot, so a mounted ConfigMap is in the watch set by that rule alone. An operator edits a file here, Argo syncs the ConfigMap, kubelet swaps the mounted file, the digest changes, the pod drains and exits, and the supervisor restarts it onto the new value.

#### Blast radius also decides which knobs carry a default

ADR-0705 splits defaults on exactly this criterion. A knob **may** carry a default in the pinned chart. A knob whose wrong value carries real consequence carries **no** default and is declared with Helm's `required`, so the sync fails naming the knob and the file.

**Both halves are built, and they answer different questions.** `chart/values.schema.json` says which knobs an installation MAY set — all four of them — and `chart/consequential.yaml` says which carry no default to fall back on. A knob listed in the second carries no default anywhere: it is absent from `chart/config/`, the adopter states it in their own values file, and nothing renders until they do — ADR-0705's "the refusal moves from boot to sync". Either way `chart/templates/configmap.yaml` merges the installation's values into that document, so the value lands in the one file the reader opens.

**An earlier attempt read the chart's own packaged documents instead, and it was cut before it merged.** Helm's `required` does work over `.Files.Get` then `fromYaml`, measured — but it inverts the guarantee ADR-0705 wants. A knob with no default is absent from `chart/config/`, so a refusal reading `chart/config/` fires for **everyone**: this repository's own `helm lint`, the reference cluster, every installation, permanently, with no way for an adopter to satisfy it. The only way to make it pass was to put the value back, at which point the knob has a default and is no longer the case the rule is about. The input source is the whole of the difference.

**The partition is per leaf, since ADR-0721.** `tlsRotation.pollSeconds` may be declared consequential while `tlsRotation.splayMaxSeconds` keeps its default in `shared.yaml`; only the same leaf may not live in both sources. Up to chart 0.1.4 both had to move together, because the mechanism APPENDED the values-supplied keys to the copied document and a top-level key the document already held would have emitted a duplicate mapping key that `serde_yaml` refuses. The deep merge has no such restriction, and what it costs instead is the comments of a document an installation overrides.

**One limit remains, and it is deliberate.** The moment the list is non-empty **this chart cannot render itself bare** — which is the point, and it lands on upstream too: `helm lint` and `ci / passed` must then be given `example/values.yaml` with the knob stated in it.

**`chart/consequential.yaml` is empty. That is a classification, not an omission.** All four knobs this repository defines keep their shipped default:

| knob                          | reader                                       | why it keeps its default                                                                                                                                                                                                         |
| ----------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tlsRotation.pollSeconds`     | `yadgar-lifecycle`, read by all six services | It sets how promptly a rotated certificate is picked up, and how hard the API server is polled. The deadline it protects is 30 days wide, so a wrong value degrades timing rather than correctness.                              |
| `tlsRotation.splayMaxSeconds` | `yadgar-lifecycle`, read by all six services | It bounds how long a replica waits before exiting onto a change. A large value delays the roll; `0` exits at once and is a supported choice. Either way the cost is timing, and the worst case is two replicas leaving together. |
| `toolsPoll.intervalSeconds`   | `gateway`                                    | It sets how often an MCP client re-polls `tools/list`. A wrong value makes a changed tool catalogue reach clients later, or polls more often than anything needs. Timing and load, not correctness.                              |
| `audit.retentionDays`         | **none — awaiting its consumer**             | Nothing consumes it, so no value of it can be wrong yet. The paragraph below is the one to read before changing this row.                                                                                                        |

**No knob here warrants `required` today, and ADR-0705 makes that the default posture rather than a preference.** It rejects forbidding chart defaults entirely, because "adding one upstream knob would then fail every installation's sync until each adopted the line, making every knob addition a breaking upgrade". A refusal has to buy something to be worth a breaking upgrade.

**The three knobs with readers are already covered one layer down.** Delete one of their lines and the fault does not pass silently: the process refuses to start, naming the knob and the file it looked in — `shared.yaml` and `gateway.yaml` each say so about their own knobs, and ADR-0705 amends ADR-0569 on the ORIGIN of a value only, so that refusal still stands. A chart-side `required` on them would add a second refusal for one fault, and its message would tell an adopter to edit `chart/config/shared.yaml` — a file that, under ADR-0705's own delivery model, an adopter never has.

**`audit.retentionDays` looks like the archetype and is not, because it has no reader at all.** The audit store is designed and not built, and ADR-0574 records that reader-less state as deliberate rather than an oversight. Declaring it `required` would force every installation to state a number nothing consumes: a refusal that protects nothing and fails syncs to do it. **Do not read the missing reader as a defect to fix by making the knob refuse.** When the audit module ships and reads this file, classify it again — D25 says an audit log with silent holes is worse than none, because it will be trusted, and a retention window only becomes consequential once something honours it.

**The file a refusal names follows the delivery path.** The refusal that exists today is the boot-time one, raised by each knob's own reader, and a knob lives in `chart/config/<file>.yaml`, so that is the file its message names. ADR-0705's own delivery — the chart pinned as an OCI artifact, the values held in an organisation's own repository — **is now expressible**, and a consequential knob's refusal is raised by the chart at sync rather than by the reader at boot. Its message names the knob, the path to set it under in the adopter's values file, and the `chart/config/` document it belongs to, because that document is what the value is merged into and what the reader opens. **No knob takes that path today**, so every refusal that actually fires in this estate is still the boot-time one.

**This chart reads a Helm value for every knob it defines, and refuses every other key.** Two failures were shipped before this one worked. Up to chart 0.1.1 a key set in a values file, in an Argo Application's `helm.parameters`, or with `--set` reached nothing and reported success — the silent no-op ADR-0569 exists to delete, one layer out. Up to 0.1.4 it was refused in full, which sounds stricter and is worse: an adopter could clone nothing and also change nothing, which is ADR-0705's own rejected alternative built by accident. Now `chart/values.schema.json` declares the four knobs, typed, and `additionalProperties: false` at EVERY level refuses everything else by name in both `helm lint` and `helm template`.

**Closed at every level, not only at the root, and the reason is the merge.** The plausible mistake is not `foo`, it is `pollSecond` — and a typo one level down is an additional property of `tlsRotation` rather than of the root. Accepted, it would be MERGED into `shared.yaml` beside the knob it was meant to be: two keys, both looking set, one of them read.

**`global` is declared and is not a knob.** Helm injects it into every subchart's values, so a closed schema that does not declare it makes this chart impossible to use as a DEPENDENCY — measured before it was declared: a parent chart holding it in `charts/` fails to render with no values supplied at all. ADR-0722's parent chart pinning every module chart needs it. It is typed as an object and left open inside, because its contents belong to the parent and to the other subcharts, and this chart reads nothing from it.

**Per leaf, exactly one of two things supplies a knob, and the schema declares their union.** Either `chart/config/<stem>.yaml` carries a default for it, or `chart/consequential.yaml` declares it consequential and it carries no default anywhere. `scripts/one_source_per_knob.py` refuses all three ways that can break: a chart default with no property here (nobody can change it without forking the chart, which is the state ADR-0721 deletes), a declared knob with no property (the closed schema refuses the key upstream told them to set), and a property neither source supplies (unset, the document renders without the knob and the reader refuses to boot with nothing from this chart naming it).

## How a service reads this

Two rules, and each closes a hole the other leaves open. **A knob missing its ConfigMap must fail loud and fail the pod** — a service that silently used a hardcoded default is the thing this whole design deletes.

**1. The volume — `optional: false`, which is the default.** A ConfigMap volume that is not marked optional makes kubelet refuse to start the pod at all when the ConfigMap is absent: it sits in `ContainerCreating` with an event naming the missing ConfigMap. Relying on the default is deliberate, and a consuming chart should say so in a comment rather than leaving it implicit — the single word `optional: true` is the difference between a pod that will not start and a pod that starts with an empty directory.

**2. The process.** The volume guard does not cover a ConfigMap that exists but lacks a key, a key whose value is empty, or a file that mounts and parses to nothing. In every one of those the process refuses to start, naming the knob path and the file. `yadgar-lifecycle`'s `ScheduleError` is the worked example: six variants, one per fault, and `Missing` and `Empty` are deliberately separate because an unset knob and a half-finished edit are different mistakes.

The mount, which every consuming chart copies:

```yaml
volumes:
  # A DIRECTORY, NEVER `subPath`. A subPath mount is copied once at container
  # start and kubelet never updates it, so the file would be frozen for the life
  # of the pod while the ConfigMap moved underneath it — the rotation watcher
  # would see nothing and configuration would silently never take effect.
  #
  # NO `optional: true`. The default is `false`, and it is what makes an absent
  # ConfigMap a pod that will not start rather than one that starts misconfigured.
  - name: config-shared
    configMap:
      name: shared
  - name: config-gateway
    configMap:
      name: gateway
volumeMounts:
  - name: config-shared
    mountPath: /etc/yadgar/config/shared
    readOnly: true
  - name: config-gateway
    mountPath: /etc/yadgar/config/gateway
    readOnly: true
```

`/etc/yadgar/config` is `yadgar_lifecycle::rotate::CONFIG_DIR`, and a test asserts its exact spelling. The mount path and that constant must agree; they disagree LOUDLY — a mismatch produces a refusal naming the path the process looked in.

Never `envFrom`. Environment variables are fixed at container start and kubelet never updates them, so an `envFrom` delivery would silently ignore every configuration change until something unrelated restarted the pod. It also collapses an absent knob and an empty one into a single case, which is exactly the distinction ADR-0569 needs.

## Adopting this in your own installation

`example/application.yaml` is the Argo `Application` an organisation commits to
**its own** GitOps repository. Copy it, pin the chart version you want, and you
have this installation's configuration. You clone nothing, and you never fork the
chart (ADR-0705).

That file is a reference and nothing syncs it from here. `yadgarhq/deploy`'s
`infra/config-app.yaml` is what deploys config into the reference cluster, and the
two differ on purpose: that one follows `main` by a git path under D55, so a merge
here reaches the reference cluster at once. That is right for the repository that
owns the chart and wrong for an installation consuming it, which pins a version.

`example/values.yaml` is the values file that goes beside it, and copying it as it
stands changes nothing. **No knob requires a value today**, which is measured rather
than claimed: that file is `{}`, and a render with it is byte-for-byte a render
without it.

**What you may set in it is every knob this chart defines**, spelled with the config
file's stem outermost:

```yaml
shared:
  tlsRotation:
    pollSeconds: 30
```

That one line changes that one number. You inherit the rest of `shared.yaml` from the
chart version you pinned, including improvements to it, because the ConfigMap is
rendered from a DEEP MERGE rather than from your file alone (ADR-0721). You clone
nothing and you fork nothing.

**Every other key is REFUSED by name** — `helm template` and `helm lint --strict`
both exit 1, and so does your sync. That includes a typo in a real knob, because the
schema is closed at every level: `pollSecond` is refused rather than merged in beside
`pollSeconds`. Two earlier versions got this wrong in opposite directions: up to chart
0.1.1 your file was silently DROPPED, and up to 0.1.4 it was refused in full, which
left you unable to change anything at all.

**What a knob you override costs you: the comments in that document.** A document you
do not override reaches your cluster byte for byte, with the reasoning for each number
beside it. A document you DO override is re-emitted from the merged data, so
`kubectl get cm shared -o yaml` shows the values without the argument for them. The
argument is in the chart version you pinned — `helm template` prints it.

**How you learn a knob has become consequential: you bump `targetRevision` and the
sync fails, naming the knob and the file.** A consequential knob carries no default
anywhere, so nothing renders until you state it.

To see exactly what a pinned version puts in your cluster:

```
helm template config oci://ghcr.io/yadgarhq/charts/config --version 0.1.5
```

Not `helm show values` — that prints this chart's `values.yaml`, which is `{}` by
design, so it answers "what do I inherit" with nothing. The defaults are in the files
under `chart/config/`, and only a render shows them.

**This chart also works as a SUBCHART**, which ADR-0722's parent chart needs. Helm
injects a `global` key into every subchart's values, so `chart/values.schema.json`
declares it: without that, a parent holding this chart in `charts/` fails to render
with no values supplied at all. A parent states this installation's knobs under
`config:`, then the knob's own path.

## Deployment

Argo syncs this chart through `yadgarhq/deploy`'s `infra/config-app.yaml`, at a **sync wave earlier than the modules**. The ordering is load-bearing: every ConfigMap must exist before any pod that mounts it, or a first sync on a fresh cluster leaves pods in `ContainerCreating` waiting for a file.

**Do not add the `yadgar-deployable` topic to this repository.** The ApplicationSet in `yadgarhq/argocd` selects repositories by that topic AND a `chart/` directory, and this repository has the directory. Adding the topic would mint a second Application for the same chart at sync wave 10 — after the modules that read it — and two Applications owning one set of ConfigMaps is a fight neither wins.

**These ConfigMap names are reserved**: `shared`, `gateway`, `iam`, `task`, `iam-db`, `task-db`, `project-db`, `audit`, `project`, in namespace `yadgar`. No module chart renders a ConfigMap today, which is what makes the unprefixed names safe; a module chart that later renders one named after itself would collide with this repository.

## Status

| knob                          | reader                                                                      |
| ----------------------------- | --------------------------------------------------------------------------- |
| `tlsRotation.pollSeconds`     | `yadgar-lifecycle`, read by all six services                                |
| `tlsRotation.splayMaxSeconds` | `yadgar-lifecycle`, read by all six services                                |
| `toolsPoll.intervalSeconds`   | `gateway`, which is the only service that builds the `tools/list` response  |
| `audit.retentionDays`         | **none — awaiting its consumer.** The audit store is designed and not built |

Every one of them carries its shipped default and none is declared with Helm's `required`; the classification and the reasoning for each are under "Blast radius" above. **All four are settable from an installation's own values file** — `chart/values.schema.json` declares each with a type, and the ConfigMap is rendered from a deep merge of the chart's document under those values (ADR-0721).

`project-db.yaml` is rendered and carries no knob at all: its first one is D53's project-path depth cap, and `project-db` ships with no compiled-in default standing in for it.

The rotation knobs have a reader in the library and **all six services read them from here.** `gateway`, `iam`, `task`, `iam-db`, `task-db` and `project-db` all pin `yadgar-lifecycle` `v0.2.3`, the version that reads this repository, and none of them carries a `tlsRotation` block in its own chart values any longer — that source was deleted once the cut-over landed.

**That was TWO pull requests per service, in order, and the reason was mechanical rather than stylistic.** Argo takes a module's chart from the module repository at HEAD, so a chart change is live on merge; the image is pinned by digest in `yadgarhq/argocd`, written by a separate release pipeline minutes later. Deleting the environment variables in the same pull request that added the file would have rolled the pod onto the OLD binary with neither source present, and the compiled-in default this repository exists to delete would have answered instead — `Schedule::from_env` was that fallback, and it no longer exists: `yadgar-lifecycle` deleted it, along with `from_lookup` and `DEFAULT_POLL`, at `v0.2.0`. So the first pull request added the file and kept the environment variables, and a second deleted them once the release had landed in `yadgarhq/argocd`. `yadgarhq/deploy`'s `MIGRATION_NOTES.md` carries both, as steps 2a and 2b, for the five services that had a fallback to delete; `project-db` shipped after the cut-over with the tag pinned from the start and nothing to remove.

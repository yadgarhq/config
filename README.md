# yadgar/config

The configuration a yadgar installation reads at boot.

This repository is a **template**. Clone it, edit the values in `chart/config/`, and point Argo at it: that is the whole of configuring an installation. Every setting is a line you can see, in a file you can diff, with the reasoning for its starting value written next to it.

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
chart/values.yaml               deliberately empty of settings — see the file for why
chart/templates/configmap.yaml  one ConfigMap per file below, named after the file
chart/config/shared.yaml        knobs every service reads, with the same value in each
chart/config/gateway.yaml       knobs only `gateway` reads
chart/config/iam.yaml           ... and so on, one file per service
chart/config/iam-db.yaml
chart/config/task.yaml
chart/config/task-db.yaml
chart/config/audit.yaml         the audit module's — designed, not built, nothing reads it
scripts/one_source_per_knob.py  the gate below
```

**One file per service, and a shared one.** A single document holding every service's settings is unnavigable — that judgement comes from having run one. The file name is the ConfigMap name, so `kubectl -n yadgar get cm iam-db -o yaml` answers "what is iam-db configured with" with no naming scheme to learn.

**Nothing enumerates the services.** `chart/templates/configmap.yaml` globs `config/*.yaml`, so adding a service is adding a file — the same property D54 buys for the module ApplicationSet one repository over.

**The file an operator edits is the file a process reads**, byte for byte. `.Files.Get` copies the bytes and the template adds the indent a YAML block scalar requires and nothing else, so comments reach the cluster: `kubectl -n yadgar get cm shared -o yaml` shows the reasoning beside the number.

### A knob lives in exactly one file

Either it is shared or it is per-service, never both. **There is no merge and no precedence** between `shared.yaml` and a service's own document.

D34 already states this for prompts — resolution replaces, it does not merge — and gives the reason: merging layers produces a value nobody wrote and nobody can attribute to a source. A knob present in two files is two writers for one value, and it fails silently, because both files look authoritative.

`scripts/one_source_per_knob.py` enforces it, as a pre-commit hook and therefore as part of `ci / passed`. If a knob genuinely needs a per-service override of a shared value, that is a design change to bring to the decision record, not something to reach by adding precedence.

### Blast radius

Editing `gateway.yaml` restarts `gateway`. **Editing `shared.yaml` restarts everything that mounts it**, which is all five services. That is correct by construction and worth knowing before you edit: a change to a shared knob is a deliberate estate-wide roll, not a surprise.

**Configuration changes roll pods by design.** A value read at boot changes by the process being restarted onto it, and nobody should read that restart as a fault. The mechanism is ADR-0523's rotation watcher and it needed no new code: it already watches every file the process read at boot, so a mounted ConfigMap is in the watch set by that rule alone. An operator edits a file here, Argo syncs the ConfigMap, kubelet swaps the mounted file, the digest changes, the pod drains and exits, and the supervisor restarts it onto the new value.

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

## Deployment

Argo syncs this chart through `yadgarhq/deploy`'s `infra/config-app.yaml`, at a **sync wave earlier than the modules**. The ordering is load-bearing: every ConfigMap must exist before any pod that mounts it, or a first sync on a fresh cluster leaves pods in `ContainerCreating` waiting for a file.

**Do not add the `yadgar-deployable` topic to this repository.** The ApplicationSet in `yadgarhq/argocd` selects repositories by that topic AND a `chart/` directory, and this repository has the directory. Adding the topic would mint a second Application for the same chart at sync wave 10 — after the modules that read it — and two Applications owning one set of ConfigMaps is a fight neither wins.

**These ConfigMap names are reserved**: `shared`, `gateway`, `iam`, `task`, `iam-db`, `task-db`, `audit`, in namespace `yadgar`. No module chart renders a ConfigMap today, which is what makes the unprefixed names safe; a module chart that later renders one named after itself would collide with this repository.

## Status

| knob                          | reader                                                                      |
| ----------------------------- | --------------------------------------------------------------------------- |
| `tlsRotation.pollSeconds`     | `yadgar-lifecycle`, linked by all five services                             |
| `tlsRotation.splayMaxSeconds` | `yadgar-lifecycle`, linked by all five services                             |
| `audit.retentionDays`         | **none — awaiting its consumer.** The audit store is designed and not built |

The rotation knobs have a reader in the library and **no service reads them from here yet.** The five services pin `yadgar-lifecycle` by an immutable git tag, and the version that reads this repository has not been cut. The remaining work per service is a version bump, a call-site change, a volume and volume mount, and the deletion of the `tlsRotation` block from that service's own chart values.

**That is TWO pull requests per service, in order, and the reason is mechanical rather than stylistic.** Argo takes a module's chart from the module repository at HEAD, so a chart change is live on merge; the image is pinned by digest in `yadgarhq/argocd`, written by a separate release pipeline minutes later. Deleting the environment variables in the same pull request that adds the file therefore rolls the pod onto the OLD binary with neither source present, and `Schedule::from_env` answers with the compiled-in default this repository exists to delete. So the first pull request ADDS the file and KEEPS the environment variables, and a second one deletes them once the release has landed in `yadgarhq/argocd`. `yadgarhq/deploy`'s `MIGRATION_NOTES.md` carries both, as steps 2a and 2b.

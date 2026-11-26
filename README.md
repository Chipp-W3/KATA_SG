# KATA_SG

A web UI and a Python API, containerised, deployed on **GKE Autopilot** (GCP, `europe-west1`) by **GitHub Actions** on every merge to `main`.

**Public URL:** http://34.52.227.249 (HTTP only, see [limitations](#limitations-and-improvements)).

```
                      GitHub Actions ── OIDC (no key) ──► GCP
                      checks → images (matrix) → deploy
                                    │ push            │ kubectl apply -k
                                    ▼                 ▼
 Browser ──HTTP──► LoadBalancer ──► front (nginx) ──/api──► api (FastAPI) ──► Secret Manager
                   static IP        2-4 pods             ClusterIP, 2-10 pods     (pod identity)
                                                         2 zones, HPA on CPU
                                                         /metrics ──► Managed Prometheus
                                                         JSON logs ──► Cloud Logging
```

| Endpoint | Purpose |
|---|---|
| `/` | Static page showing which pod and which version answered |
| `/api/whoami` | Pod name and version (short commit SHA) |
| `/api/work?iterations=N` | Bounded CPU work, used to drive the autoscaler |
| `/api/admin/stats` | Version, uptime, requests served by the pod; requires the `X-Admin-Token` header (token from Secret Manager) |
| `/health`, `/ready` | Liveness and readiness probes |
| `/metrics` | Prometheus metrics (`http_request_duration_seconds` histogram) |

## Run locally

Requirements: Docker with Compose.

```bash
docker compose up --build
# UI:  http://localhost:8080
curl localhost:8080/api/whoami
curl -H "X-Admin-Token: local-dev-token" localhost:8080/api/admin/stats
```

The admin token defaults to `local-dev-token`; override it with `ADMIN_TOKEN=... docker compose up`. Locally the API reads it from the environment; on GKE it reads it from Secret Manager.

API tests and lint:

```bash
cd api
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest -q
```

## Build and deploy

### 1. Infrastructure (Terraform, applied manually)

Bootstrap once: a versioned GCS bucket for the state (`<project_id>-tfstate`), created by hand.

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars        # project_id, github_repo
terraform init -backend-config="bucket=<project_id>-tfstate"
terraform apply                                     # ~8 min (cluster)
```

Creates: APIs, Artifact Registry, Autopilot regional cluster with a dedicated node service account, static IP, the `admin-token` secret (container only), the Workload Identity Federation for GitHub, the CI service account.

Then, out of Terraform (so the value never lands in the state):

```bash
python -c "import secrets;open('token.txt','w').write(secrets.token_hex(32))"
gcloud secrets versions add admin-token --data-file=token.txt && rm token.txt
```

And the GitHub repository variables, from the Terraform outputs (none of them is a secret):

```bash
gh variable set GCP_WIF_PROVIDER --body "$(terraform output -raw wif_provider)"
gh variable set GCP_CI_SA        --body "$(terraform output -raw ci_service_account)"
gh variable set GCP_REGISTRY     --body "$(terraform output -raw registry)"
gh variable set FRONT_IP         --body "$(terraform output -raw front_ip)"
gh variable set GKE_CLUSTER      --body "$(terraform output -raw cluster_name)"
gh variable set GCP_REGION       --body "$(terraform output -raw region)"
```

### 2. Application (GitHub Actions, automatic)

```
pull_request ──► checks (ruff, pytest, terraform fmt)                              ~20 s
push to main ──► checks ──► images [api | front] ──────────► deploy               ~2 min 20
                            build → Trivy → push              auth OIDC
                            (same runner, SHA tag)            kustomize edit set image <sha>
                                                              kubectl apply -k k8s
                                                              rollout status ─ fail ─► rollout undo + red job
                                                              smoke test: public URL serves <sha>
```

- **Only `main` deploys**: the federation only accepts GitHub tokens from this repository *and* `refs/heads/main`; `images` and `deploy` are skipped on pull requests.
- **The pushed image is the scanned image**: build, Trivy scan (CRITICAL/HIGH with a fix available, blocking) and push run in the same job, so no image crosses runners.
- **Automatic rollback**: if the new pods are not ready within 180 s, `kubectl rollout undo` restores the previous version and the job turns red. With `maxUnavailable: 0`, the old pods keep serving during the whole attempt.
- **Smoke test on the version**, not only on HTTP 200: the old version also answers 200.
- Docs-only merges (`docs/**`, `*.md`) do not redeploy.

Manual rollback: `kubectl -n kata rollout undo deploy/api`, or `git revert` of the merge commit (redeploys the previous code).

Teardown: `kubectl delete -k k8s` first (otherwise the load balancer forwarding rule can stay and hold the IP), then `terraform destroy`.

## Technical decisions

| Area | Choice | Main alternative | Why |
|---|---|---|---|
| Runtime | GKE Autopilot, regional | GKE Standard; Cloud Run | No nodes to manage, hardened by default, multi-zone; still shows Kubernetes reliability features (probes, HPA, PDB). Cloud Run was the fallback |
| Infra as code | Terraform, GCS state, manual apply | `gcloud` script; Terraform in CI | Declarative and reviewable; infra changes rarely, so plan/apply by hand for now |
| Node identity | Dedicated `gke-nodes` service account | Default Compute SA | The default SA has no role in recent projects (image pulls fail); a node keeps its identity for life |
| App | Python 3.12, FastAPI, 1 uvicorn worker per pod | Flask | Typed validation, async; scaling is horizontal (HPA), not inside the pod |
| CPU endpoint | Sync `def` | `async def` | CPU work in `async def` would block the event loop and the probes. Limit found under load: threads still share the GIL, so heavy CPU work also slows the loop (worker processes would isolate it) |
| Images | Multi-stage, `-slim`/`alpine`, non-root UID:GID, `apt-get`/`apk upgrade` at build | Distroless | Small, non-root; base images lag behind security fixes |
| Docker cache | `requirements.txt` copied and installed **before** the code | Copy everything first | A code change does not reinstall dependencies |
| Front | nginx-unprivileged on 8080, proxies `/api` | Page served by the API | Same origin (no CORS), the API stays internal (ClusterIP) |
| Exposure | Service `LoadBalancer` + static IP | Gateway API + managed cert + Cloud Armor | Ready in minutes; L7/TLS listed as next step |
| Manifests | Kustomize, tag set to the SHA in CI | Helm | Plain YAML, built into kubectl |
| CI auth | Workload Identity Federation (OIDC) | JSON key in a GitHub secret | No long-lived secret to leak or rotate |
| App secret | Secret Manager, read at startup with the pod identity | Kubernetes Secret, ESO, CSI driver | Nothing to install, no copy in etcd, IAM on this secret for this service account only |
| Metrics | Histogram by method, **route template**, status + `PodMonitoring` | Counter only | One metric gives traffic, errors and p95 latency; route templates keep cardinality bounded |
| Logs | JSON on stdout (`severity` + fields) | Plain text | Cloud Logging turns fields into filters (`jsonPayload.status>=500`) |
| Git | GitHub flow, protected `main`, required `checks`, merge commits | GitFlow; squash | Short branches for continuous deployment; history keeps every step |

**Least privilege identities**

| Identity | Can do | Scope |
|---|---|---|
| `gke-nodes` (nodes) | Pull images, write logs and metrics | This registry only |
| `kata/api` (Kubernetes SA of the API pods) | Read the admin token | This secret only |
| `github-ci` (CI, via OIDC) | Push images, deploy Kubernetes objects | This registry; `container.developer` (no cluster admin) |
| `GITHUB_TOKEN` | Read the repository | `contents: read`; `id-token: write` only in `images` and `deploy` |

**Reliability**

- Readiness (`/ready`) and liveness (`/health`, no dependency check) are separate: a slow dependency removes a pod from the Service, it does not restart every pod.
- Rolling updates with `maxUnavailable: 0`: never below current capacity.
- `preStop` sleep 5 s: the endpoint removal reaches the load balancer and nginx before the process stops.
- PodDisruptionBudget `minAvailable: 1`: node upgrades and Autopilot consolidation never take the last ready pod.
- API pods spread over two zones (`DoNotSchedule`, `minDomains: 2`, `matchLabelKeys: pod-template-hash`, see the incident log).
- Pod Security `restricted` on the namespace: non-root, read-only root filesystem (+ `/tmp` emptyDir), all capabilities dropped, seccomp.
- If Secret Manager is unreachable at startup, the API keeps serving and only `/api/admin/stats` returns 503.

## Behaviour under load

### Scenario

[`load/k6.js`](load/k6.js), run from a home connection against the public URL:

```bash
k6 run -e BASE_URL=http://34.52.227.249 load/k6.js
```

- 10 virtual users for 1 min, ramp to 100 in 2 min, plateau of 5 min, ramp-down 1 min; each user waits 1 s between requests (about 90 req/s at the plateau).
- 90 % `GET /api/work` (CPU-bound, what scales), 10 % `GET /` (nginx only).
- Thresholds = SLOs: `p(95) < 500 ms` and `errors < 1 %`.
- At 4 min 40 s, one API pod was deleted on purpose (failure drill).

### Result: thresholds crossed, the ceiling is capacity, not the autoscaler

k6 (client side): **both thresholds crossed** (`http_req_duration` and `http_req_failed`).

API (server side, from our own `http_request_duration_seconds` histogram in Managed Prometheus):

| Metric (`/api/work`, 9 min) | Value |
|---|---|
| Requests answered | 15,484, **all HTTP 200** |
| Throughput served | ~33 req/s (about 90 req/s offered) |
| p50 / p95 latency | 549 ms / **2.39 s** |

Timeline (k6 started at 17:29, recorded every 10 s):

| Time | CPU / target | HPA replicas | API pods ready | Event |
|---|---|---|---|---|
| 17:29 | low | 2 | 2/2 | warm-up |
| 17:30:20 | rising | 4 | 2/4 | HPA scales up |
| 17:31:18 | 166 % | 9 | 3/9 | 6 pods `Pending` |
| 17:31:29 | 202 % | **10 (max)** | 3/10 | 7 pods `Pending` until the end |
| 17:31–17:38 | 200–260 % | 10 | **1 to 3** | liveness restarts on saturated pods |
| 17:33:42 | | | | one API pod deleted (drill) |
| 17:38 | 3 % | 10 | 3/10 | load stops |

**What worked**: the HPA reacted within about 1 minute and asked for the maximum (10) in about 2 minutes. The API itself never returned an error.

**Why the SLOs were missed** (diagnosed from Kubernetes events and node allocations):

1. **No room for the new pods.** 7 of 10 pods stayed `Pending` with `Insufficient memory`, and the cluster autoscaler could not add a node: `QUOTA_EXCEEDED` (free trial: 250 GB of SSD, 100 GB per node, 2 nodes in use). On each node, Autopilot's `gke-system-balloon-pod` reserves about 25 GB of the 28 GB allocatable with a `system-node-critical` priority, so our pods cannot preempt it (during the preparation, these placeholders were preempted and 10 pods fitted on 2 nodes). The real capacity was **3 API pods**.
2. **Liveness probes made the overload worse.** With the default 1 s timeout, `/health` timed out on saturated pods (`context deadline exceeded`), the kubelet restarted busy but healthy pods (3 and 4 restarts), and ready capacity dropped to 1 pod at times. Root cause in the app: `/api/work` runs in FastAPI's thread pool, but pure-Python hashing holds the GIL, so the event loop answering the probes is starved.
3. **Errors happened upstream of the API**: the API counted zero errors, so the failed requests are nginx `502/504` (pod restarting, 10 s proxy timeout) or client timeouts. Our server-side SLI misses them: the availability SLI should also be measured at the load balancer.

The failure drill cannot be isolated in this run (the service was already saturated).

### Follow-up

- **Probe fix** (PR #18): liveness `timeoutSeconds: 5`, `failureThreshold: 6` (only kill a stuck process, never a slow one), readiness `timeoutSeconds: 2`. Merged, but **not deployed**: the rollout needs room for one extra pod (`maxSurge: 1`, `maxUnavailable: 0`), there was none, the rollout timed out after 180 s and the **automatic rollback restored the previous version**, with the old pods serving throughout. `main` therefore contains a version that is not running; the running version is the previous commit (`kubectl -n kata get deploy -o wide`).
- **Next steps**, by impact: more quota (or larger nodes) so the HPA can reach 10 pods; CPU work in worker processes instead of threads (or more uvicorn workers per pod), so probes stay responsive; `maxSurge: 0` / `maxUnavailable: 1` when capacity is tight; availability SLI at the load balancer; rerun the test and the failure drill once capacity is available.

## Incident log

### Workstation crash during the first `terraform apply` (0:09)

- **What happened**: the laptop crashed about 3 minutes into the first `terraform apply`, while the GKE cluster was being created. On restart, the cluster, node service account, registry, IAM bindings and APIs all existed in GCP, but the remote state was **empty** and still **locked** by the dead process. The same crash zeroed `.git/config`, which was being written by `git push -u`.
- **Why it matters**: with an empty state, a new `apply` would try to recreate existing resources (conflicts), and nobody could run Terraform while the lock was held.
- **Diagnosis**: no `terraform` process alive; lock owner and time read from the `.tflock` object; actual resources listed with `gcloud`; no `errored.tfstate` (the process was killed, so it could not write one). On the Git side, the remote branch was intact (`gh api`); only local files were damaged.
- **Fix**: `terraform force-unlock` (for the GCS backend, the lock ID is the object *generation*, not the UUID shown in the lock content), then `terraform import` of the 15 resources, then `plan`: 0 to add, 2 metadata-only changes (labels and `deletion_protection`, which default differently after an import), `apply`, `plan` = no changes. Git: `.git/config` rewritten, branch re-fetched, `git fsck` clean.
- **Decision**: import rather than destroy and recreate: it saved about 7 minutes of cluster creation and is the tool designed to reconcile state and reality.
- **Prevention**: run `terraform apply` from CI (a single runner, with `concurrency`), never from a workstation; `force-unlock` only when it is certain that no process holds the lock.

### Zone spreading silently not applied (2:25 – 2:38)

- **Symptom**: pipeline green, but all API pods on a single node in a single zone, despite `whenUnsatisfiable: DoNotSchedule`. Found by checking placement after the deployment (`kubectl get nodes -L topology.kubernetes.io/zone`), not by the CI.
- **Cause 1**: the skew is only computed over zones that already have a node. With one node, one zone looks balanced. **Fix**: `minDomains: 2` (PR #16); Autopilot then created a node in a second zone.
- **Cause 2**: both new pods still landed in the same zone, because during the rolling update the old pods (still running in the other zone) were counted. **Fix**: `matchLabelKeys: [pod-template-hash]` (PR #17): only pods of the new revision are counted. Result: one API pod in `europe-west1-c`, one in `europe-west1-d`.

### Automatic rollback in real conditions (2:50 – 3:07)

- The probe fix (PR #18) could not roll out: the new API pod stayed `Pending` (no memory left, zone rule, no new node allowed by the quota), and with `maxUnavailable: 0` the old pods could not leave first.
- After 180 s, the `deploy` job ran `kubectl rollout undo` and turned red. The previous version kept serving during the whole attempt. This is the safety net working as designed, observed in a real situation rather than in a drill.

## Limitations and improvements

What is not done, by priority:

0. **Capacity under load**: the load test missed its SLOs because the cluster could only run 3 API pods (quota and Autopilot reservations, see [Behaviour under load](#behaviour-under-load)); the probe fix is merged but not deployed for the same reason.
1. **SLOs and alerting**: SLIs are measured (availability and p95 from the histogram) but no alert pages anyone yet. Next: SLO of 99.5 % availability and p95 < 500 ms, with a burn-rate alert (fast budget consumption) in Cloud Monitoring, written in Terraform.
2. **Validation before production**: today a PR runs lint, tests and `terraform fmt`, then `main` deploys straight to the only environment. Next: an ephemeral environment per PR (namespace `pr-<number>`, URL commented on the PR, separate service account restricted to that namespace), then staging on `main` and production promoted from a tag **with the same image digest**, behind a protected GitHub environment with approval; canary later.
3. **HTTP only, no WAF**: Gateway API + Google-managed certificate + Cloud Armor.
4. **Shared admin token**: replace with IAP or OIDC with roles.
5. **Single environment**: Terraform modules and Kustomize overlays per environment.
6. **Terraform in CI**: `plan` on every PR (read-only service account), `apply` after approval; it would also have prevented the incident above.
7. **Front spread across zones is only preferred** (`ScheduleAnyway`): both front pods currently run in one zone. A hard rule needs more quota than the free trial (2 nodes).
8. **Smoke test failure does not roll back** (only a rollout timeout does).
9. Supply chain: image signing (cosign, keyless) and SBOM, deploy by digest.
10. CI speed: Docker layer cache (`type=gha`), build only the services that changed (path filter + retag of unchanged images).
11. Distroless image for the API; GitOps (Argo CD); private cluster; NetworkPolicy (only the front may reach the API).
12. Known small issues: nginx resolves `api` at startup and exits if it is not resolvable (self-heals by restart); uvicorn startup messages are plain text; Starlette deprecation warning for `httpx` in tests.

## Contributing

- **GitHub flow**: one short branch per change, merged within the hour: `feat/…`, `fix/…`, `ci/…`, `docs/…`, `chore/…`.
- **Conventional Commits** for commits and PR titles (`feat(api): …`, `fix(k8s): …`), one idea per commit; no force-push, fixes stay visible.
- **Pull requests** use the template (context, changes, tests, risks, rollback) and reference their issue (`Closes #N`). Open them early as drafts to get CI feedback.
- **`main` is protected**: PR required, `checks` must be green and the branch up to date, enforced for admins too. Merge with a merge commit (squash is disabled) via auto-merge: `gh pr merge --merge --auto`.
- **Merging to `main` deploys to production.** In a team: one approval required and a `CODEOWNERS` file.

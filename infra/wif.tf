# GitHub Actions -> GCP without any JSON key: GitHub issues a short-lived OIDC
# token, Google STS exchanges it, then the workflow impersonates the CI service
# account.

# A deleted pool ID stays reserved for 30 days: a random suffix allows
# destroy/apply cycles in the same project.
resource "random_id" "wif_suffix" {
  byte_length = 2
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-${random_id.wif_suffix.hex}"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  # Claims of the GitHub token copied into attributes usable by IAM.
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Gate: only this repository, only from main (PRs and forks cannot deploy).
  attribute_condition = "assertion.repository == \"${var.github_repo}\" && assertion.ref == \"refs/heads/main\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "ci" {
  account_id   = "github-ci"
  display_name = "GitHub Actions CI/CD"
}

# Let workflows of the repository impersonate the CI service account.
resource "google_service_account_iam_member" "ci_wif" {
  service_account_id = google_service_account.ci.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# Push images: on this registry only, not the whole project.
resource "google_artifact_registry_repository_iam_member" "ci_push" {
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.ci.member
}

# Deploy: get cluster credentials and manage Kubernetes objects (no cluster admin).
resource "google_project_iam_member" "ci_deploy" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = google_service_account.ci.member
}

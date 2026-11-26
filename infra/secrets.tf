# Only the secret container is managed here. The value is added out of band:
#   openssl rand -hex 32 | gcloud secrets versions add admin-token --data-file=-
# so it never lands in the Terraform state.
resource "google_secret_manager_secret" "admin_token" {
  secret_id = "admin-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

data "google_project" "this" {}

locals {
  # Workload Identity Federation for GKE: the Kubernetes service account is an
  # IAM principal by itself, no Google service account or annotation needed.
  api_ksa_principal = join("/", [
    "principal://iam.googleapis.com/projects/${data.google_project.this.number}",
    "locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog",
    "subject/ns/${var.k8s_namespace}/sa/${var.k8s_service_account}",
  ])
}

# Least privilege: the API pods can read this one secret, not every secret of the project.
resource "google_secret_manager_secret_iam_member" "api_reads_admin_token" {
  secret_id = google_secret_manager_secret.admin_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.api_ksa_principal
}

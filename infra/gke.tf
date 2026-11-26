# Dedicated node identity. The default Compute service account has no role in
# recent projects: nodes could neither pull images nor ship logs and metrics.
resource "google_service_account" "nodes" {
  account_id   = "gke-nodes"
  display_name = "GKE Autopilot nodes"
}

# Logging, monitoring and metadata permissions required by GKE nodes.
resource "google_project_iam_member" "nodes_default" {
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = google_service_account.nodes.member
}

# Pull images from the application registry only.
resource "google_artifact_registry_repository_iam_member" "nodes_pull" {
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.nodes.member
}

resource "google_container_cluster" "main" {
  name     = "kata"
  location = var.region # regional: control plane and nodes spread across zones

  enable_autopilot = true

  cluster_autoscaling {
    auto_provisioning_defaults {
      service_account = google_service_account.nodes.email
      oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    }
  }

  release_channel {
    channel = "REGULAR"
  }

  # Default is true; it would make `terraform destroy` fail.
  deletion_protection = false

  depends_on = [google_project_service.apis]
}

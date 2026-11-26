resource "google_artifact_registry_repository" "images" {
  location      = var.region # same region as the cluster: fast pulls, no egress cost
  repository_id = "kata"
  format        = "DOCKER"
  description   = "Application images, tagged with the git commit SHA."

  depends_on = [google_project_service.apis]
}

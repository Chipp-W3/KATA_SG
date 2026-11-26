# Values consumed by GitHub Actions as repository variables (not secrets:
# none of them grants access on its own).

output "wif_provider" {
  description = "Full provider name for google-github-actions/auth."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_service_account" {
  description = "Service account impersonated by the CI."
  value       = google_service_account.ci.email
}

output "registry" {
  description = "Docker registry prefix for image names."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "front_ip" {
  description = "Static public IP of the front LoadBalancer."
  value       = google_compute_address.front.address
}

output "cluster_name" {
  value = google_container_cluster.main.name
}

output "region" {
  value = var.region
}

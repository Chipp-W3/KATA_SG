locals {
  apis = [
    "compute.googleapis.com",              # default VPC, static IP, load balancer
    "container.googleapis.com",            # GKE
    "artifactregistry.googleapis.com",     # image registry
    "secretmanager.googleapis.com",        # application secrets
    "iam.googleapis.com",                  # service accounts, WIF pools
    "iamcredentials.googleapis.com",       # service account impersonation (CI)
    "sts.googleapis.com",                  # OIDC token exchange (CI)
    "cloudresourcemanager.googleapis.com", # project IAM bindings
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service = each.value

  # Keep APIs enabled on destroy: disabling them breaks other resources
  # and re-enabling is slow.
  disable_on_destroy = false
}

variable "project_id" {
  description = "GCP project ID (immutable, not the display name)."
  type        = string
}

variable "region" {
  description = "Region for the cluster, registry and static IP."
  type        = string
  default     = "europe-west1"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy through WIF, as owner/repo."
  type        = string
}

variable "k8s_namespace" {
  description = "Kubernetes namespace of the application."
  type        = string
  default     = "kata"
}

variable "k8s_service_account" {
  description = "Kubernetes service account of the API pods (reads Secret Manager)."
  type        = string
  default     = "api"
}

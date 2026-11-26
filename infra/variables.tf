variable "project_id" {
  description = "GCP project ID (immutable, not the display name)."
  type        = string
}

variable "region" {
  description = "Region for the cluster and the registry."
  type        = string
  default     = "europe-west1"
}

terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # The bucket is passed at init time (a backend cannot use variables):
  #   terraform init -backend-config="bucket=<project_id>-tfstate"
  backend "gcs" {
    prefix = "kata-final"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = {
    app        = "kata"
    managed-by = "terraform"
  }
}

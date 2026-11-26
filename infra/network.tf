# Reserved before the first deployment: the public URL is known from the start
# and survives a re-creation of the Service. Used by the front Service
# (spec.loadBalancerIP).
resource "google_compute_address" "front" {
  name         = "kata-front"
  region       = var.region
  address_type = "EXTERNAL"

  depends_on = [google_project_service.apis]
}

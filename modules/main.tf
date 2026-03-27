# Terraform Global Infrastructure Configurations

# 1. Terraform Settings and Provider
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = "proyecto-sura-clustering-2026" 
  region  = "us-central1"
}

# 2. Bronze Layer: Raw Storage Bucket
resource "google_storage_bucket" "raw_data" {
  name                        = "sura-clustering-raw"
  location                    = "US-CENTRAL1"
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
}

# 3. Silver Layer: Cleaned Data Dataset
resource "google_bigquery_dataset" "cleaned_data" {
  dataset_id                  = "sura_clustering_cleaned"
  project                     = "proyecto-sura-clustering-2026"
  location                    = "US"
}

# 4. Gold Layer: Processed Data Dataset
resource "google_bigquery_dataset" "processed_data" {
  dataset_id                  = "sura_clustering_processed"
  project                     = "proyecto-sura-clustering-2026"
  location                    = "US"
}
terraform {
  required_version = ">= 1.14.0, < 2.0.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.66.0"
    }
  }
}

provider "hcloud" {}

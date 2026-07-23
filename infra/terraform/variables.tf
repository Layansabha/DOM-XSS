variable "project_name" {
  description = "Lowercase name used for Hetzner Cloud resources and labels."
  type        = string
  default     = "dom-xss"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.project_name))
    error_message = "project_name must be 3-63 lowercase letters, digits, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be development, staging, or production."
  }
}

variable "location" {
  description = "Hetzner Cloud location for the server."
  type        = string
  default     = "nbg1"
}

variable "server_type" {
  description = "Hetzner server type. Keep at least 8 GB RAM when OWASP ZAP is enabled."
  type        = string
  default     = "cpx31"
}

variable "server_image" {
  description = "Operating-system image used by the VPS."
  type        = string
  default     = "ubuntu-24.04"
}

variable "ssh_public_key" {
  description = "Public SSH key authorized for the deploy user."
  type        = string

  validation {
    condition = anytrue([
      startswith(trimspace(var.ssh_public_key), "ssh-ed25519 "),
      startswith(trimspace(var.ssh_public_key), "ssh-rsa "),
      startswith(trimspace(var.ssh_public_key), "ecdsa-sha2-"),
    ])
    error_message = "ssh_public_key must be a valid OpenSSH public key."
  }
}

variable "admin_cidrs" {
  description = "IPv4 or IPv6 CIDRs allowed to connect over SSH. Prefer a workstation /32 or /128."
  type        = list(string)

  validation {
    condition = (
      length(var.admin_cidrs) > 0
      && alltrue([
        for cidr in var.admin_cidrs :
        can(cidrhost(cidr, 0)) && !contains(["0.0.0.0/0", "::/0"], cidr)
      ])
    )
    error_message = "admin_cidrs must contain valid restricted CIDRs; world-open SSH is rejected."
  }
}

variable "repository_url" {
  description = "Git repository cloned during cloud-init."
  type        = string
  default     = "https://github.com/Layansabha/DOM-XSS.git"

  validation {
    condition     = startswith(var.repository_url, "https://")
    error_message = "repository_url must use HTTPS."
  }
}

variable "repository_ref" {
  description = "Branch, tag, or commit checked out during cloud-init."
  type        = string
  default     = "main"

  validation {
    condition = (
      can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$", var.repository_ref))
      && !strcontains(var.repository_ref, "..")
      && !strcontains(var.repository_ref, "@{")
    )
    error_message = "repository_ref must be a safe branch, tag, or commit name."
  }
}

variable "enable_ipv6" {
  description = "Assign a public IPv6 address to the server."
  type        = bool
  default     = true
}

variable "enable_backups" {
  description = "Enable paid Hetzner server backups."
  type        = bool
  default     = false
}

variable "enable_delete_protection" {
  description = "Protect the server from accidental deletion and rebuild."
  type        = bool
  default     = true
}

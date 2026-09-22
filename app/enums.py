"""Allowed values for ticket classification and department routing."""

from enum import StrEnum


class TicketCategory(StrEnum):
    ACCESS_AUTHENTICATION = "access_authentication"
    SOFTWARE_APPLICATION = "software_application"
    HARDWARE_DEVICE = "hardware_device"
    NETWORK_CONNECTIVITY = "network_connectivity"
    SECURITY_INCIDENT = "security_incident"
    OTHER = "other"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Department(StrEnum):
    IDENTITY_ACCESS = "identity_access"
    APPLICATION_SUPPORT = "application_support"
    SERVICE_DESK = "service_desk"
    INFRASTRUCTURE_NETWORK = "infrastructure_network"
    SECURITY = "security"

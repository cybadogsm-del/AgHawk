from __future__ import annotations

from turfhelm.customers.repository import (
    ContactRecord,
    CustomerRecord,
    CustomerRepository,
    SiteRecord,
)
from turfhelm.security.context import SecurityContext

_MAX_NAME_LENGTH = 100
_MAX_ADDRESS_LENGTH = 200
_MAX_PHONE_LENGTH = 40


class CustomerService:
    """Validated customer, site, and contact configuration boundary."""

    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    def list_customers(self, context: SecurityContext) -> list[CustomerRecord]:
        return self._repository.list_customers(context)

    def list_sites(self, context: SecurityContext, customer_id: str) -> list[SiteRecord]:
        return self._repository.list_sites(context, customer_id)

    def list_contacts(
        self,
        context: SecurityContext,
        customer_id: str,
        *,
        site_id: str | None = None,
    ) -> list[ContactRecord]:
        return self._repository.list_contacts(context, customer_id, site_id=site_id)

    def create_customer(
        self,
        context: SecurityContext,
        name: str,
        *,
        correlation_id: str,
    ) -> CustomerRecord:
        self._repository.require_manage(context)
        return self._repository.create_customer(
            context,
            self._normalize(name, "name", _MAX_NAME_LENGTH),
            correlation_id=correlation_id,
        )

    def create_site(
        self,
        context: SecurityContext,
        customer_id: str,
        address: str,
        *,
        correlation_id: str,
    ) -> SiteRecord:
        self._repository.require_manage(context)
        return self._repository.create_site(
            context,
            customer_id,
            self._normalize(address, "address", _MAX_ADDRESS_LENGTH),
            correlation_id=correlation_id,
        )

    def create_contact(
        self,
        context: SecurityContext,
        customer_id: str,
        name: str,
        phone: str,
        *,
        site_id: str | None = None,
        correlation_id: str,
    ) -> ContactRecord:
        self._repository.require_manage(context)
        return self._repository.create_contact(
            context,
            customer_id,
            self._normalize(name, "name", _MAX_NAME_LENGTH),
            self._normalize(phone, "phone", _MAX_PHONE_LENGTH),
            site_id=site_id,
            correlation_id=correlation_id,
        )

    def archive_customer(
        self,
        context: SecurityContext,
        customer_id: str,
        *,
        correlation_id: str,
    ) -> CustomerRecord:
        return self._repository.archive_customer(
            context, customer_id, correlation_id=correlation_id
        )

    def archive_site(
        self,
        context: SecurityContext,
        customer_id: str,
        site_id: str,
        *,
        correlation_id: str,
    ) -> SiteRecord:
        return self._repository.archive_site(
            context, customer_id, site_id, correlation_id=correlation_id
        )

    def archive_contact(
        self,
        context: SecurityContext,
        customer_id: str,
        contact_id: str,
        *,
        correlation_id: str,
    ) -> ContactRecord:
        return self._repository.archive_contact(
            context, customer_id, contact_id, correlation_id=correlation_id
        )

    @staticmethod
    def _normalize(value: object, field: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError(f"{field} is required")
        if len(normalized) > maximum:
            raise ValueError(f"{field} must contain at most {maximum} characters")
        return normalized

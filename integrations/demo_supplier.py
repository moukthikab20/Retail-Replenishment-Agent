"""Demo supplier provider — catalog vendors from demo master data."""

from __future__ import annotations

from integrations.contracts import ProviderHealth, SupplierRecord, SupplierTerms
from integrations.failures import ProviderFailureCode, ProviderError
from services.demo_catalog import PRODUCT_BY_SKU, VENDOR_BY_ID, VENDORS

SOURCE_LABEL = "Demo"
PROVIDER_NAME = "Demo Supplier Provider"
DEFAULT_VENDOR_ID = "V001"
DEFAULT_VENDOR_NAME = "Maple Grove Dairy"
DEFAULT_LEAD_TIME_DAYS = 2


class DemoSupplierProvider:
    provider_name = PROVIDER_NAME
    source_label = SOURCE_LABEL

    def __init__(
        self,
        *,
        vendor_id: str = DEFAULT_VENDOR_ID,
        vendor_name: str = DEFAULT_VENDOR_NAME,
        lead_time_days: int | None = DEFAULT_LEAD_TIME_DAYS,
    ) -> None:
        self._vendor_id = vendor_id
        self._vendor_name = vendor_name
        self._lead_time_days = lead_time_days
        self._vendors = {v["vendor_id"]: v for v in VENDORS}
        # Keep constructor overrides as aliases for the default vendor.
        if vendor_id not in self._vendors:
            self._vendors[vendor_id] = {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "lead_time_days": lead_time_days or DEFAULT_LEAD_TIME_DAYS,
            }

    def get_default_vendor(self) -> SupplierRecord:
        return self.require_supplier(self._vendor_id)

    def get_supplier(self, vendor_id: str) -> SupplierRecord | None:
        if vendor_id in {
            "demo",
            "default",
            self._vendor_name,
            DEFAULT_VENDOR_NAME,
            "Demo Vendor Co.",
            # Legacy demo vendor labels (pre-rename) — resolve to catalog entry.
            "FreshFields Dairy",
            "Metro Beverage Supply",
            "NorthStar Snacks",
            "HomeCare Distribution",
            "PantryPro Foods",
            "Everyday Personal Care",
            "ValueSource Wholesale",
            "Prime Retail Supply",
        }:
            return self.get_default_vendor()
        row = self._vendors.get(vendor_id)
        if row is None:
            # Allow lookup by vendor display name.
            for candidate in self._vendors.values():
                if candidate.get("vendor_name") == vendor_id:
                    row = candidate
                    break
        if row is None:
            return None
        return SupplierRecord(
            vendor_id=str(row["vendor_id"]),
            vendor_name=str(row["vendor_name"]),
            lead_time_days=int(row.get("lead_time_days") or DEFAULT_LEAD_TIME_DAYS),
            terms="Net 30 (demo)",
            source=self.source_label,
            provider_name=self.provider_name,
        )

    def get_supplier_terms(
        self, vendor_id: str, sku: str | None = None
    ) -> SupplierTerms | None:
        resolved_id = vendor_id
        if sku and sku in PRODUCT_BY_SKU and vendor_id in {"demo", "default", self._vendor_id}:
            resolved_id = str(PRODUCT_BY_SKU[sku]["vendor_id"])
        elif sku and sku in PRODUCT_BY_SKU and vendor_id not in self._vendors:
            # Prefer product's assigned vendor when caller passes a sku context.
            resolved_id = str(PRODUCT_BY_SKU[sku]["vendor_id"])
        supplier = self.get_supplier(resolved_id)
        if supplier is None:
            return None
        return SupplierTerms(
            vendor_id=supplier.vendor_id,
            sku=sku,
            lead_time_days=supplier.lead_time_days,
            minimum_order_quantity=None,
            currency="USD",
            source=self.source_label,
            provider_name=self.provider_name,
        )

    def get_expected_lead_time(
        self, vendor_id: str, sku: str | None = None
    ) -> int | None:
        terms = self.get_supplier_terms(vendor_id, sku=sku)
        return terms.lead_time_days if terms else None

    def require_supplier(self, vendor_id: str) -> SupplierRecord:
        row = self.get_supplier(vendor_id)
        if row is None:
            raise ProviderError(
                code=ProviderFailureCode.RECORD_NOT_FOUND.value,
                message=f"Supplier not found: {vendor_id}",
                provider=self.provider_name,
            )
        return row

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            ok=True,
            status="healthy",
            provider_name=self.provider_name,
            source=self.source_label,
            message=f"Supplier Data — {self.source_label} ({len(self._vendors)} vendors).",
            details={
                "vendor_id": self._vendor_id,
                "vendor_count": len(self._vendors),
                "real_supplier_api": False,
            },
        )


def vendor_name_for_sku(sku: str) -> str:
    """Resolve display vendor name for a SKU from the demo catalog."""
    product = PRODUCT_BY_SKU.get(sku)
    if not product:
        return DEFAULT_VENDOR_NAME
    vendor = VENDOR_BY_ID.get(str(product["vendor_id"]))
    if not vendor:
        return DEFAULT_VENDOR_NAME
    return str(vendor["vendor_name"])

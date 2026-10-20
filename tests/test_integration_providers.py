"""Provider contract + factory tests for the integration adapter layer."""

from __future__ import annotations

import pytest

from integrations.csv_inventory import CSVInventoryProvider
from integrations.csv_product import CSVProductProvider
from integrations.csv_sales import CSVSalesProvider
from integrations.demo_supplier import DemoSupplierProvider
from integrations.failures import ProviderConfigError
from integrations.factory import (
    get_erp_adapter,
    get_inventory_provider,
    get_product_provider,
    get_provider_summary,
    get_sales_provider,
    get_supplier_provider,
    reset_providers,
    validate_provider_configuration,
)
from integrations.mock_erp import MockERPAdapter
from services import (
    batch_run_service,
    erp_service,
    forecast_service,
    inventory_service,
    order_lifecycle_service,
    policy_service,
    product_service,
)


def test_inventory_provider_contract():
    provider = CSVInventoryProvider()
    result = provider.get_inventory_position("ST001", "SKU-1001")
    assert result is not None
    assert result.position.store_id == "ST001"
    assert result.source == "Demo CSV"
    assert result.provider_name
    assert provider.get_inventory_freshness("ST001", "SKU-1001") is not None
    assert provider.get_inventory_position("ST001", "SKU-MISSING") is None
    health = provider.health_check()
    assert health.ok is True
    assert health.source == "Demo CSV"


def test_sales_provider_contract():
    provider = CSVSalesProvider()
    history = provider.get_sales_history("ST001", "SKU-1001", lookback_days=28)
    assert history.source == "Demo CSV"
    assert history.average_daily_sales >= 0
    assert provider.count_history_days("ST001", "SKU-1001") >= 0
    missing = provider.get_sales_history("ST001", "SKU-DOES-NOT-EXIST", lookback_days=7)
    assert missing.daily_sales == []
    assert missing.average_daily_sales == 0.0
    health = provider.health_check()
    assert health.ok is True


def test_product_provider_contract():
    provider = CSVProductProvider()
    product = provider.get_product("SKU-1001")
    assert product is not None
    assert product.case_pack >= 1
    assert product.vendor_id is not None
    assert product.vendor_id.startswith("V")
    assert float(product.unit_cost) > 0
    assert product.source == "Demo CSV"
    assert provider.get_product("SKU-MISSING") is None
    assert provider.list_stores()
    assert provider.list_skus_for_store("ST001")
    assert provider.health_check().ok is True


def test_supplier_provider_contract():
    provider = DemoSupplierProvider()
    default = provider.get_default_vendor()
    assert default.vendor_name
    assert provider.get_supplier(default.vendor_id) is not None
    assert provider.get_expected_lead_time(default.vendor_id) is not None
    assert provider.get_supplier("unknown-vendor-xyz") is None
    terms = provider.get_supplier_terms(default.vendor_id, sku="SKU-1001")
    assert terms is not None
    assert provider.health_check().ok is True


def test_erp_adapter_queue_status_health_and_idempotent_transmit():
    adapter = MockERPAdapter(force_fail=False)
    health = adapter.health_check()
    assert health.ok is True
    assert health.source == "Mock ERP"
    payload = {
        "purchase_order_id": "PO-TEST-1",
        "sku": "SKU-1001",
        "store_id": "ST001",
        "quantity": 6,
        "unit_cost": 2.5,
        "vendor": "Demo Vendor Co.",
    }
    first = adapter.transmit(payload)
    assert first.ok is True
    assert first.erp_reference
    status = adapter.get_order_status(first.erp_reference)
    assert status["status"] == "acknowledged"
    with pytest.raises(Exception):
        adapter.queue_order(payload)


def test_factory_selects_configured_providers(monkeypatch):
    monkeypatch.setattr("integrations.factory.INVENTORY_PROVIDER", "csv")
    monkeypatch.setattr("integrations.factory.SALES_PROVIDER", "csv")
    monkeypatch.setattr("integrations.factory.PRODUCT_PROVIDER", "csv")
    monkeypatch.setattr("integrations.factory.SUPPLIER_PROVIDER", "demo")
    monkeypatch.setattr("integrations.factory.ERP_PROVIDER", "mock")
    monkeypatch.setattr("integrations.factory.ERP_ADAPTER", "mock")
    reset_providers()
    selected = validate_provider_configuration()
    assert selected == {
        "inventory": "csv",
        "sales": "csv",
        "product": "csv",
        "supplier": "demo",
        "erp": "mock",
    }
    assert isinstance(get_inventory_provider(force_new=True), CSVInventoryProvider)
    assert isinstance(get_sales_provider(force_new=True), CSVSalesProvider)
    assert isinstance(get_product_provider(force_new=True), CSVProductProvider)
    assert isinstance(get_supplier_provider(force_new=True), DemoSupplierProvider)
    assert isinstance(get_erp_adapter(force_new=True), MockERPAdapter)


def test_unknown_provider_rejected_no_silent_fallback(monkeypatch):
    monkeypatch.setattr("integrations.factory.ERP_PROVIDER", "sap")
    monkeypatch.setattr("integrations.factory.ERP_ADAPTER", "sap")
    reset_providers()
    with pytest.raises(ProviderConfigError) as err:
        validate_provider_configuration()
    assert "sap" in str(err.value).lower()
    assert "not available" in str(err.value).lower()


def test_provider_summary_does_not_leak_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-should-not-appear")
    monkeypatch.setenv("CRON_SECRET", "cron-secret-value")
    monkeypatch.setenv("DEMO_ACCESS_CODE", "access-secret")
    reset_providers()
    summary = get_provider_summary()
    dumped = str(summary)
    assert "sk-secret-should-not-appear" not in dumped
    assert "cron-secret-value" not in dumped
    assert "access-secret" not in dumped
    assert "password" not in dumped.lower() or "[redacted]" in dumped.lower()


def test_business_services_use_providers_not_csv_imports():
    # Smoke: services resolve through providers.
    product = product_service.get_product_details("SKU-1001")
    assert product.sku == "SKU-1001"
    inv = inventory_service.get_inventory_position("ST001", "SKU-1001")
    assert inv.on_hand >= 0
    forecast = forecast_service.get_demand_forecast("ST001", "SKU-1001")
    assert forecast.forecast_units is not None
    assert policy_service.count_history_days("ST001", "SKU-1001") >= 0
    assert order_lifecycle_service._default_vendor_name()
    erp = erp_service.adapter_health()
    assert erp.get("real_erp") is False


def test_end_to_end_batch_via_configured_adapters():
    policy_service.ensure_default_policy()
    result = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1001"), ("ST001", "SKU-1002")],
        trigger_type="manual",
        initiated_by="admin.demo",
    )
    assert result["status"] in {"completed", "completed_with_errors"}
    assert result["scored_items"] >= 1
    summary = get_provider_summary()
    assert summary["providers"]["inventory"]["source"] == "Demo CSV"
    assert summary["providers"]["erp"]["source"] == "Mock ERP"

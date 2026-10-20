"""Inventory on Hand — current-state operational view."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from services.inventory_on_hand_service import (
    InventoryFilters,
    apply_inventory_filters,
    get_inventory_row_detail,
)
from ui_components import empty_state, status_pill


@st.cache_data(ttl=120, show_spinner=False)
def _load_inventory_dataset() -> dict:
    from services.inventory_on_hand_service import build_inventory_on_hand_dataset

    return build_inventory_on_hand_dataset()


def _open_inventory_panel(*, row_key: str) -> None:
    st.session_state["selected_inventory_row"] = str(row_key)


def _close_inventory_panel() -> None:
    st.session_state["selected_inventory_row"] = None


def _inventory_panel_field(label: str, value: str) -> str:
    return (
        f'<div class="il-del-panel-field">'
        f'<div class="lab">{escape(label)}</div>'
        f'<div class="val">{escape(value)}</div>'
        f"</div>"
    )


def render_inventory_details_panel(row: dict[str, Any]) -> None:
    with st.container(key="inventory_side_panel"):
        title_col, close_col = st.columns([10, 1], gap="small")
        with title_col:
            st.markdown(
                '<div class="inventory-details-title">Inventory Details</div>',
                unsafe_allow_html=True,
            )
        with close_col:
            st.button(
                "×",
                key=f"close_inventory_{row['row_key']}",
                help=None,
                on_click=_close_inventory_panel,
            )

        st.markdown(
            f'<div class="il-inv-panel-product">{escape(str(row.get("product_name") or "—"))}</div>'
            f'<div class="il-inv-panel-sku">{escape(str(row.get("sku") or "—"))}</div>',
            unsafe_allow_html=True,
        )
        dos_display = (
            f"{row.get('days_of_supply_display')} days"
            if row.get("days_of_supply") is not None
            else "—"
        )
        on_hand_display = f"{int(row.get('on_hand') or 0):,} units"
        in_transit_display = f"{int(row.get('in_transit') or 0):,} units"
        safety_display = f"{int(row.get('safety_stock') or 0):,} units"
        forecast_display = f"{float(row.get('forecast_units') or 0):,.0f} units"
        st.markdown(
            f'<div class="il-del-panel-grid">'
            f"{_inventory_panel_field('Store', str(row.get('store_name') or '—'))}"
            f"{_inventory_panel_field('Vendor', str(row.get('vendor_name') or '—'))}"
            f"{_inventory_panel_field('Current Inventory', on_hand_display)}"
            f"{_inventory_panel_field('In Transit', in_transit_display)}"
            f"{_inventory_panel_field('Safety Stock', safety_display)}"
            f"{_inventory_panel_field('7-Day Demand Forecast', forecast_display)}"
            f"{_inventory_panel_field('Days of Supply', dos_display)}"
            f'<div class="il-del-panel-field">'
            f'<div class="lab">Inventory Status</div>'
            f'<div class="val">{status_pill(str(row.get("status_kind") or "neutral"), str(row.get("status_label") or "—"))}</div>'
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div class="il-inv-panel-section">'
            f'<div class="il-inv-panel-section-lab">Next Expected Delivery</div>'
            f'<div class="il-inv-panel-section-val">{escape(str(row.get("next_delivery_display") or "No inbound delivery scheduled"))}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

        decision = row.get("decision") or {}
        if decision:
            created_html = ""
            if decision.get("created_at"):
                created_html = (
                    f'<div class="il-inv-panel-meta">{escape(str(decision.get("created_at")))}</div>'
                )
            st.markdown(
                f'<div class="il-inv-panel-section">'
                f'<div class="il-inv-panel-section-lab">Current Replenishment Decision</div>'
                f'<div class="il-inv-panel-section-val">{escape(str(decision.get("summary") or "—"))}</div>'
                f"{created_html}"
                f"</div>",
                unsafe_allow_html=True,
            )
            rec_id = decision.get("recommendation_id")
            if rec_id:
                if st.button("View Decision", key=f"view_decision_{row['row_key']}", type="primary"):
                    st.session_state["nav_recommendation_id"] = rec_id
                    st.session_state["recommendation_id"] = rec_id
                    st.switch_page("pages/2_Review.py")


def _inventory_row_html(row: dict[str, Any], *, selected: bool) -> str:
    selected_cls = " is-selected" if selected else ""
    product = escape(str(row.get("product_name") or "—"))
    sku = escape(str(row.get("sku") or ""))
    return (
        f'<div class="il-inv-table-row{selected_cls}">'
        f'<div class="il-inv-cell il-inv-product">'
        f'<div class="name">{product}</div>'
        f'<div class="sku">{sku}</div>'
        f"</div>"
        f'<div class="il-inv-cell">{escape(str(row.get("store_name") or "—"))}</div>'
        f'<div class="il-inv-cell">{escape(str(row.get("vendor_name") or "—"))}</div>'
        f'<div class="il-inv-cell num">{int(row.get("on_hand") or 0):,}</div>'
        f'<div class="il-inv-cell num">{int(row.get("in_transit") or 0):,}</div>'
        f'<div class="il-inv-cell num">{int(row.get("safety_stock") or 0):,}</div>'
        f'<div class="il-inv-cell num">{escape(str(row.get("days_of_supply_display") or "—"))}</div>'
        f"</div>"
    )


def render_inventory_on_hand() -> None:
    dataset = _load_inventory_dataset()
    all_rows: list[dict[str, Any]] = dataset["rows"]
    vendors: list[str] = dataset["vendors"]
    stores = dataset["stores"]

    store_names = ["All Stores"] + [s["store_name"] for s in stores]
    vendor_names = ["All Vendors"] + vendors
    status_options = {
        "all": "All Statuses",
        "stockout_risk": "Stockout Risk",
        "low_stock": "Low Stock",
        "healthy": "Healthy",
        "excess": "Excess",
        "incoming": "Incoming",
    }

    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([1.4, 1, 1, 1])
        with f1:
            search = st.text_input("Search product / SKU", key="inv_search_input")
        with f2:
            store_pick = st.selectbox("Store", options=store_names, key="inv_store_pick")
        with f3:
            vendor_pick = st.selectbox("Vendor", options=vendor_names, key="inv_vendor_pick")
        with f4:
            status_pick = st.selectbox(
                "Inventory status",
                options=list(status_options.keys()),
                format_func=lambda k: status_options[k],
                key="inv_status_pick",
            )

    store_id = None
    if store_pick != "All Stores":
        from services import product_service

        store_id = product_service.store_id_for_display_name(store_pick)
    vendor = None if vendor_pick == "All Vendors" else vendor_pick
    filters = InventoryFilters(
        search=search or "",
        store_id=store_id,
        vendor=vendor,
        status=status_pick,
    )
    filtered = apply_inventory_filters(all_rows, filters)
    selected_key = str(st.session_state.get("selected_inventory_row") or "").strip()

    if not filtered:
        empty_state("No inventory records match the selected filters.")
        selected_row = get_inventory_row_detail(filtered, selected_key) if selected_key else None
        if selected_row:
            render_inventory_details_panel(selected_row)
        return

    st.markdown(
        """
        <div class="il-inv-table">
          <div class="il-inv-table-head">
            <div>Product</div>
            <div>Store</div>
            <div>Vendor</div>
            <div>On Hand</div>
            <div>In Transit</div>
            <div>Safety Stock</div>
            <div>Days of Supply</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for row in filtered:
        row_key = str(row["row_key"])
        with st.container(key=f"inv_hit_{row_key}"):
            st.markdown(
                _inventory_row_html(row, selected=(row_key == selected_key)),
                unsafe_allow_html=True,
            )
            st.button(
                " ",
                key=f"inv_row_{row_key}",
                use_container_width=True,
                type="secondary",
                on_click=_open_inventory_panel,
                kwargs={"row_key": row_key},
            )

    selected_row = get_inventory_row_detail(filtered, selected_key) if selected_key else None
    if selected_row:
        render_inventory_details_panel(selected_row)

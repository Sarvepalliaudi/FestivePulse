"""
FestivePulse — Complete Product Management Module
Add, View, Edit, Search, Filter, Deactivate & Delete products with full persistence and audit safety.
"""

import streamlit as st
import pandas as pd
from repositories.product_repository import (
    ProductRepository, DuplicateSkuError, ProductReferencedError, ProductValidationError
)
from services.currency_utils import format_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_standard_sidebar,
    render_empty_state,
    clean_html
)
from config import GST_SLABS, UNITS_OF_MEASURE, MASTER_FESTIVALS, REGIONS

st.set_page_config(page_title="Product Management — FestivePulse", page_icon="🛍️", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("🛍️ Product Management & Catalog")

# Top action tabs
prod_tabs = st.tabs([
    "📋 Catalog & Search",
    "➕ Add New Product",
    "✏️ Edit Product",
    "🔒 Deactivate / Manage Status"
])

# -------------------------------------------------------------
# TAB 1: CATALOG & SEARCH & FILTER
# -------------------------------------------------------------
with prod_tabs[0]:
    st.subheader("Product Catalog")

    # Filters row
    cats = ProductRepository.get_categories()
    cat_options = {0: "All Categories"}
    for c in cats:
        cat_options[c["category_id"]] = c["category_name"]

    f_options = ["All Festivals"] + [f["code"] for f in MASTER_FESTIVALS]
    r_options = ["All Regions"] + REGIONS

    col_f1, col_f2, col_f3, col_f4 = st.columns([1.2, 1, 1, 1.8])
    with col_f1:
        sel_cat = st.selectbox("Category Filter:", options=list(cat_options.keys()), format_func=lambda x: cat_options[x], key="cat_filt")
    with col_f2:
        sel_fest = st.selectbox("Festival Filter:", options=f_options, key="fest_filt")
    with col_f3:
        sel_reg = st.selectbox("Region Filter:", options=r_options, key="reg_filt")
    with col_f4:
        search_query = st.text_input("🔍 Search Name, SKU or Barcode:", placeholder="e.g. Kaju Katli, Diya, SKU-SWT", key="search_filt")

    col_sub_f1, col_sub_f2 = st.columns([2, 1])
    with col_sub_f1:
        include_deactivated = st.checkbox("Show Deactivated / Inactive Products", value=False)

    fest_arg = None if sel_fest == "All Festivals" else sel_fest
    reg_arg = None if sel_reg == "All Regions" else sel_reg
    cat_arg = None if sel_cat == 0 else sel_cat
    search_arg = search_query.strip() if search_query else None

    # Fetch from repository
    products_list = ProductRepository.get_all_products(
        category_id=cat_arg,
        festival_tag=fest_arg,
        region_tag=reg_arg,
        search=search_arg,
        include_inactive=include_deactivated
    )

    if products_list:
        st.write(f"Displaying **{len(products_list)}** product(s):")
        df_p = pd.DataFrame(products_list)

        # Polish display values
        df_display = df_p.copy()
        df_display["cost_price"] = df_display["cost_price"].apply(lambda x: format_inr(x))
        df_display["selling_price"] = df_display["selling_price"].apply(lambda x: format_inr(x))
        df_display["mrp"] = df_display["mrp"].apply(lambda x: format_inr(x) if pd.notnull(x) else "-")
        df_display["gst_rate"] = df_display["gst_rate"].apply(lambda x: f"{x:.1f}%")
        df_display["current_stock_display"] = df_display.apply(lambda r: f"{r['current_stock']} {r['unit_of_measure']}", axis=1)
        df_display["is_active_display"] = df_display["is_active"].apply(lambda x: "Active ✅" if x else "Deactivated ⛔")
        df_display["tags_display"] = df_display["festival_tags"].apply(lambda t: ", ".join(t) if t else "General")

        cols_to_show = [
            "sku", "product_name", "category_name", "current_stock_display",
            "min_safety_stock", "cost_price", "selling_price", "mrp", "gst_rate",
            "stock_status", "is_active_display", "tags_display"
        ]

        st.dataframe(
            df_display[cols_to_show].rename(columns={
                "sku": "SKU",
                "product_name": "Product Name",
                "category_name": "Category",
                "current_stock_display": "Stock on Hand",
                "min_safety_stock": "Reorder Level",
                "cost_price": "Purchase Cost",
                "selling_price": "Selling Price",
                "mrp": "MRP",
                "gst_rate": "GST",
                "stock_status": "Health",
                "is_active_display": "Status",
                "tags_display": "Festivals"
            }),
            use_container_width=True
        )
    else:
        st.info("No products found matching your search and filter criteria.")


# -------------------------------------------------------------
# TAB 2: ADD NEW PRODUCT
# -------------------------------------------------------------
with prod_tabs[1]:
    st.subheader("➕ Add New Product to Catalog")
    st.markdown("All fields are validated. Optional opening stock automatically creates an initial inventory batch.")

    cats = ProductRepository.get_categories()
    if not cats:
        st.error("No product categories defined. Please set up categories first.")
        st.stop()

    cat_map = {c["category_name"]: c["category_id"] for c in cats}

    with st.form("form_add_product", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            p_name = st.text_input("Product Name *", placeholder="e.g. Royal Shahi Kaju Katli (500g)")
            p_sku = st.text_input("SKU Code (Must be unique) *", placeholder="e.g. SKU-SWT-004").strip().upper()
            p_barcode = st.text_input("Barcode / EAN (Optional)", placeholder="e.g. 890123450099")
            p_cat = st.selectbox("Category *", options=list(cat_map.keys()))
            p_uom = st.selectbox("Unit of Measure *", options=UNITS_OF_MEASURE)

        with c2:
            p_cost = st.number_input("Purchase Cost Price (₹) *", min_value=0.0, step=10.0, value=150.0)
            p_sell = st.number_input("Selling Price (₹) *", min_value=0.0, step=10.0, value=250.0)
            p_mrp = st.number_input("MRP (Maximum Retail Price ₹)", min_value=0.0, step=10.0, value=275.0)
            p_gst = st.selectbox("GST Slab *", options=GST_SLABS, index=1)
            p_hsn = st.text_input("HSN Code", placeholder="e.g. 21069099")

        st.markdown("#### 📦 Inventory & Reorder Thresholds")
        c3, c4 = st.columns(2)
        with c3:
            p_reorder_level = st.number_input("Reorder Level (Min Safety Stock Buffer) *", min_value=0, value=20, step=5)
            p_reorder_pack = st.number_input("Standard Pack / Reorder Quantity *", min_value=1, value=50, step=10)
        with c4:
            p_initial_stock = st.number_input("Initial Opening Stock (Units)", min_value=0, value=0, step=10)
            p_initial_loc = st.text_input("Storage Location", value="Main Store Rack A1")

        st.markdown("#### 🪔 Festival & Regional Localization")
        c5, c6 = st.columns(2)
        with c5:
            all_f_codes = [f["code"] for f in MASTER_FESTIVALS]
            p_fest_tags = st.multiselect("Festival Associations (Optional)", options=all_f_codes, default=["DIWALI"])
            p_reg_tags = st.multiselect("Regional Targets (Optional)", options=REGIONS, default=["Pan-India"])
        with c6:
            p_is_perish = st.checkbox("Is Perishable? (e.g. fresh sweets/mithai)", value=False)
            p_shelf_days = st.number_input("Shelf Life in Days", min_value=1, value=10, disabled=not p_is_perish)

        btn_add = st.form_submit_button("Save Product to Catalog", type="primary", use_container_width=True)

        if btn_add:
            try:
                new_id = ProductRepository.create_product(
                    data={
                        "product_name": p_name,
                        "sku": p_sku,
                        "barcode": p_barcode,
                        "category_id": cat_map[p_cat],
                        "unit_of_measure": p_uom,
                        "cost_price": p_cost,
                        "selling_price": p_sell,
                        "mrp": p_mrp,
                        "gst_rate": p_gst,
                        "hsn_code": p_hsn,
                        "min_safety_stock": p_reorder_level,
                        "reorder_quantity": p_reorder_pack,
                        "is_perishable": p_is_perish,
                        "shelf_life_days": p_shelf_days if p_is_perish else None,
                        "festival_tags": p_fest_tags,
                        "region_tags": p_reg_tags
                    },
                    initial_stock=p_initial_stock,
                    initial_storage_location=p_initial_loc
                )
                st.success(f"🎉 Product '{p_name}' successfully created with SKU: **{p_sku}** (Product ID: {new_id})!")
                if p_initial_stock > 0:
                    st.info(f"Opening stock batch created with {p_initial_stock} {p_uom} at {p_initial_loc}.")
                st.rerun()
            except DuplicateSkuError as err:
                st.error(f"❌ Duplicate Error: {str(err)}")
            except ProductValidationError as err:
                st.error(f"⚠️ Validation Error: {str(err)}")
            except Exception as err:
                st.error(f"Database Error: {str(err)}")


# -------------------------------------------------------------
# TAB 3: EDIT PRODUCT
# -------------------------------------------------------------
with prod_tabs[2]:
    st.subheader("✏️ Edit Existing Product")
    all_prods = ProductRepository.get_all_products(include_inactive=True)

    if all_prods:
        prod_map = {f"{p['sku']} — {p['product_name']} (Stock: {p['current_stock']})": p["product_id"] for p in all_prods}
        sel_prod_label = st.selectbox("Select Product to Modify:", options=list(prod_map.keys()))
        target_id = prod_map[sel_prod_label]
        target_prod = ProductRepository.get_product_by_id(target_id)

        if target_prod:
            cats = ProductRepository.get_categories()
            cat_map = {c["category_name"]: c["category_id"] for c in cats}

            with st.form("form_edit_product"):
                ec1, ec2 = st.columns(2)
                with ec1:
                    e_name = st.text_input("Product Name *", value=target_prod["product_name"])
                    e_sku = st.text_input("SKU Code *", value=target_prod["sku"]).strip().upper()
                    e_barcode = st.text_input("Barcode", value=str(target_prod.get("barcode") or ""))
                    
                    cat_names = list(cat_map.keys())
                    cat_ids = list(cat_map.values())
                    cur_cat_idx = cat_ids.index(target_prod["category_id"]) if target_prod["category_id"] in cat_ids else 0
                    e_cat = st.selectbox("Category *", options=cat_names, index=cur_cat_idx)
                    
                    uom_idx = UNITS_OF_MEASURE.index(target_prod["unit_of_measure"]) if target_prod["unit_of_measure"] in UNITS_OF_MEASURE else 0
                    e_uom = st.selectbox("Unit of Measure *", options=UNITS_OF_MEASURE, index=uom_idx)

                with ec2:
                    e_cost = st.number_input("Purchase Cost Price (₹) *", min_value=0.0, step=10.0, value=float(target_prod["cost_price"]))
                    e_sell = st.number_input("Selling Price (₹) *", min_value=0.0, step=10.0, value=float(target_prod["selling_price"]))
                    e_mrp = st.number_input("MRP (₹)", min_value=0.0, step=10.0, value=float(target_prod["mrp"] or target_prod["selling_price"]))
                    
                    gst_idx = GST_SLABS.index(target_prod["gst_rate"]) if target_prod["gst_rate"] in GST_SLABS else 1
                    e_gst = st.selectbox("GST Slab *", options=GST_SLABS, index=gst_idx)
                    e_hsn = st.text_input("HSN Code", value=str(target_prod.get("hsn_code") or ""))

                ec3, ec4 = st.columns(2)
                with ec3:
                    e_reorder_level = st.number_input("Reorder Level (Min Safety Stock) *", min_value=0, value=int(target_prod["min_safety_stock"]))
                    e_reorder_pack = st.number_input("Standard Pack / Reorder Size *", min_value=1, value=int(target_prod["reorder_quantity"]))
                with ec4:
                    e_is_perish = st.checkbox("Is Perishable?", value=bool(target_prod["is_perishable"]))
                    e_shelf_days = st.number_input("Shelf Life Days", min_value=1, value=int(target_prod["shelf_life_days"] or 7), disabled=not e_is_perish)

                all_f_codes = [f["code"] for f in MASTER_FESTIVALS]
                cur_fest_tags = [t for t in target_prod.get("festival_tags", []) if t in all_f_codes]
                e_fest_tags = st.multiselect("Festival Associations", options=all_f_codes, default=cur_fest_tags)

                cur_reg_tags = [r for r in target_prod.get("region_tags", []) if r in REGIONS]
                e_reg_tags = st.multiselect("Regional Targets", options=REGIONS, default=cur_reg_tags)

                btn_update = st.form_submit_button("Update Product Changes", type="primary", use_container_width=True)

                if btn_update:
                    try:
                        ProductRepository.update_product(
                            product_id=target_id,
                            data={
                                "product_name": e_name,
                                "sku": e_sku,
                                "barcode": e_barcode,
                                "category_id": cat_map[e_cat],
                                "unit_of_measure": e_uom,
                                "cost_price": e_cost,
                                "selling_price": e_sell,
                                "mrp": e_mrp,
                                "gst_rate": e_gst,
                                "hsn_code": e_hsn,
                                "min_safety_stock": e_reorder_level,
                                "reorder_quantity": e_reorder_pack,
                                "is_perishable": e_is_perish,
                                "shelf_life_days": e_shelf_days if e_is_perish else None,
                                "festival_tags": e_fest_tags,
                                "region_tags": e_reg_tags
                            }
                        )
                        st.success(f"Product '{e_name}' successfully updated!")
                        st.rerun()
                    except DuplicateSkuError as err:
                        st.error(f"❌ Duplicate SKU Error: {str(err)}")
                    except ProductValidationError as err:
                        st.error(f"⚠️ Validation Error: {str(err)}")
                    except Exception as err:
                        st.error(f"Database Error: {str(err)}")
    else:
        st.info("No products available to edit.")


# -------------------------------------------------------------
# TAB 4: DEACTIVATE / REACTIVATE / SAFE DELETION
# -------------------------------------------------------------
with prod_tabs[3]:
    st.subheader("🔒 Lifecycle Management: Deactivate, Reactivate & Safe Delete")
    st.markdown(
        "**Audit Protection:** Products with sales transactions or stock history cannot be permanently deleted, "
        "protecting financial ledgers and GSTR-3B audit trails. Such products can be **deactivated** so they "
        "no longer appear in billing or purchasing."
    )

    all_prods_manage = ProductRepository.get_all_products(include_inactive=True)

    if all_prods_manage:
        manage_map = {
            f"[{'ACTIVE' if p['is_active'] else 'INACTIVE'}] {p['sku']} — {p['product_name']}": p["product_id"]
            for p in all_prods_manage
        }
        sel_m_label = st.selectbox("Select Product to Manage:", options=list(manage_map.keys()))
        target_m_id = manage_map[sel_m_label]
        target_m = ProductRepository.get_product_by_id(target_m_id)

        # Show reference audit
        refs = ProductRepository.get_product_reference_counts(target_m_id)
        st.markdown(clean_html(f"""
        <div style="background: rgba(18, 24, 38, 0.7); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 1rem; margin: 1rem 0;">
            <h4 style="margin: 0 0 0.5rem 0; color: #F8FAFC;">Audit Reference Status for {target_m['product_name']} ({target_m['sku']})</h4>
            <div style="display: flex; gap: 2rem;">
                <div>Sales Invoices: <b>{refs['sales_items']}</b></div>
                <div>Stock Batches: <b>{refs['inventory_batches']}</b></div>
                <div>Stock Adjustments: <b>{refs['stock_adjustments']}</b></div>
                <div>Status: <b style="color: {'#34D399' if target_m['is_active'] else '#FB7185'};">{'ACTIVE' if target_m['is_active'] else 'DEACTIVATED'}</b></div>
            </div>
        </div>
        """), unsafe_allow_html=True)

        col_act1, col_act2 = st.columns(2)

        with col_act1:
            if target_m["is_active"]:
                st.warning("Deactivating will hide this item from the POS billing counter and Reorder Advisor.")
                if st.button("⛔ Deactivate Product", type="secondary", use_container_width=True):
                    ProductRepository.deactivate_product(target_m_id)
                    st.success(f"Product '{target_m['product_name']}' is now deactivated.")
                    st.rerun()
            else:
                st.info("Reactivating will restore this product to active POS billing and procurement.")
                if st.button("✅ Reactivate Product", type="primary", use_container_width=True):
                    ProductRepository.reactivate_product(target_m_id)
                    st.success(f"Product '{target_m['product_name']}' is now reactivated.")
                    st.rerun()

        with col_act2:
            st.error("⚠️ **Permanent Deletion** (Permitted only for products with ZERO sales or inventory history).")
            confirm_del = st.checkbox(
                f"I understand this permanently removes '{target_m['product_name']}' ({target_m['sku']})",
                key=f"chk_del_prod_{target_m_id}"
            )
            if st.button("🗑️ Permanently Delete Product", type="secondary", use_container_width=True, disabled=not confirm_del):
                try:
                    ProductRepository.delete_product(target_m_id)
                    st.success(f"Product '{target_m['product_name']}' was permanently removed.")
                    st.rerun()
                except ProductReferencedError as err:
                    st.error(f"🛑 Action Prevented: {str(err)}")
    else:
        render_empty_state("No Products Found", "Your product catalog is currently empty. Add your first product using the 'Add New Product' tab.")

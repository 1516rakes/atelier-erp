import streamlit as st
import sqlite3
import pandas as pd
import bcrypt
import os
import shutil
import re
from datetime import datetime
import plotly.express as px
import io
from fpdf import FPDF

# ==========================================
# 1. إعدادات النظام الأساسية
# ==========================================
st.set_page_config(page_title="Atelier Master ERP", page_icon="🧵", layout="wide")
st.markdown("""
    <style>
    .reportview-container, .sidebar .sidebar-content { direction: rtl; text-align: right; }
    h1, h2, h3, h4 { color: #1e293b; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .stButton>button { width: 100%; border-radius: 6px; font-weight: bold; background-color: #2563eb; color: white; }
    div[data-testid="stMetricValue"] { color: #059669; }
    </style>
    """, unsafe_allow_html=True)

DB_NAME = "atelier_master.db"
BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

# ==========================================
# 2. الأمان والتشفير (Bcrypt)
# ==========================================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

# ==========================================
# 3. بناء قاعدة البيانات المتقدمة (ERP Schema)
# ==========================================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        # 1. المستخدمين
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT
            )
        """)
        # مدير افتراضي
        if cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            cursor.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                           ("admin", hash_password("admin123"), "مدير", datetime.now().strftime("%Y-%m-%d")))
        
        # 2. العملاء والمقاسات
        cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL, created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS measurements (customer_id INTEGER PRIMARY KEY, neck REAL, chest REAL, waist REAL, total_length REAL, FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE)")
        
        # 3. الموردين والمخزون
        cursor.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, company TEXT)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT NOT NULL, category TEXT,
                supplier_id INTEGER, purchase_price REAL DEFAULT 0, selling_price REAL DEFAULT 0,
                quantity REAL NOT NULL DEFAULT 0, unit TEXT, min_stock REAL DEFAULT 5.0,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )
        """)
        
        # 4. حركة المخزون
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER,
                movement_type TEXT CHECK(movement_type IN ('إضافة', 'صرف', 'تسوية')),
                qty_changed REAL NOT NULL, user_id INTEGER, date TEXT, notes TEXT,
                FOREIGN KEY(item_id) REFERENCES inventory(id), FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        
        # 5. الطلبات والمدفوعات
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_no TEXT UNIQUE NOT NULL,
                customer_id INTEGER, employee_id INTEGER, details TEXT, total_price REAL NOT NULL,
                status TEXT NOT NULL, order_date TEXT, delivery_date TEXT,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, amount REAL NOT NULL, payment_date TEXT, user_id INTEGER, FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE)")
        
        # 6. سجل التدقيق
        cursor.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, target TEXT, timestamp TEXT)")
        conn.commit()

init_db()

def log_action(user_id, action, target):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("INSERT INTO audit_logs (user_id, action, target, timestamp) VALUES (?, ?, ?, ?)",
                              (user_id, action, target, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def fetch_data(query, params=()):
    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql_query(query, conn, params=params)

# ==========================================
# 4. نظام تسجيل الدخول الآمن
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 نظام الإدارة المتكامل (Secure Login)")
    with st.form("login_form"):
        user = st.text_input("اسم المستخدم")
        pwd = st.text_input("كلمة المرور", type="password")
        if st.form_submit_button("تسجيل الدخول"):
            with sqlite3.connect(DB_NAME) as conn:
                res = conn.cursor().execute("SELECT id, password_hash, role FROM users WHERE username = ?", (user,)).fetchone()
                if res and check_password(pwd, res[1]):
                    st.session_state.update({'logged_in': True, 'user_id': res[0], 'role': res[2], 'username': user})
                    log_action(res[0], "تسجيل دخول", "النظام")
                    st.rerun()
                else:
                    st.error("❌ بيانات الدخول خاطئة.")
    st.stop()

# ==========================================
# 5. الواجهة الجانبية والأقسام
# ==========================================
st.sidebar.title(f"👤 {st.session_state.username}")
st.sidebar.caption(f"الصلاحية: {st.session_state.role}")
if st.sidebar.button("🚪 خروج"):
    log_action(st.session_state.user_id, "تسجيل خروج", "النظام")
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")
menu = st.sidebar.radio("القائمة الرئيسية", ["📊 لوحة التحكم", "👥 العملاء والمقاسات", "📦 إدارة المخزون والموردين", "🧾 الفواتير والمدفوعات", "⚙️ إعدادات النظام"])

# ------------------------------------------
# 1. لوحة التحكم
# ------------------------------------------
if menu == "📊 لوحة التحكم":
    st.title("📊 لوحة المؤشرات المالية والتشغيلية")
    
    df_low = fetch_data("SELECT item_name, quantity, min_stock FROM inventory WHERE quantity <= min_stock")
    if not df_low.empty:
        st.warning(f"🚨 **تنبيه:** يوجد {len(df_low)} أصناف تحتاج لإعادة طلب (وصلت لحد الأمان).")
    
    t_sales = fetch_data("SELECT SUM(total_price) as t FROM orders")['t'][0] or 0.0
    t_paid = fetch_data("SELECT SUM(amount) as a FROM payments")['a'][0] or 0.0
    t_clients = fetch_data("SELECT COUNT(*) as c FROM customers")['c'][0] or 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("إجمالي المبيعات", f"{t_sales:,.2f} ج")
    c2.metric("المقبوضات", f"{t_paid:,.2f} ج")
    c3.metric("الديون المتأخرة", f"{(t_sales - t_paid):,.2f} ج")
    c4.metric("عدد العملاء", str(t_clients))
    
    st.markdown("---")
    df_orders = fetch_data("SELECT status, COUNT(*) as count FROM orders GROUP BY status")
    if not df_orders.empty:
        fig = px.pie(df_orders, names='status', values='count', hole=0.4, title="حالة الطلبات الحالية")
        st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------
# 2. العملاء والمقاسات (CRUD + Excel)
# ------------------------------------------
elif menu == "👥 العملاء والمقاسات":
    st.title("👥 سجل العملاء وإدارة المقاسات")
    t1, t2, t3 = st.tabs(["➕ عميل جديد", "🔍 بحث وتعديل/حذف", "📥 تصدير البيانات"])
    
    with t1:
        with st.form("new_client"):
            col1, col2 = st.columns(2)
            c_name = col1.text_input("اسم العميل *")
            c_phone = col2.text_input("رقم الهاتف *")
            st.write("المقاسات (سم):")
            m1, m2, m3, m4 = st.columns(4)
            neck = m1.number_input("الرقبة", 30.0)
            chest = m2.number_input("الصدر", 90.0)
            waist = m3.number_input("الخصر", 80.0)
            total_l = m4.number_input("الطول", 140.0)
            
            if st.form_submit_button("حفظ العميل"):
                if c_name and c_phone:
                    try:
                        with sqlite3.connect(DB_NAME) as conn:
                            c = conn.cursor()
                            c.execute("INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)", (c_name, c_phone, datetime.now().strftime("%Y-%m-%d")))
                            cid = c.lastrowid
                            c.execute("INSERT INTO measurements (customer_id, neck, chest, waist, total_length) VALUES (?, ?, ?, ?, ?)", (cid, neck, chest, waist, total_l))
                            conn.commit()
                        log_action(st.session_state.user_id, "إضافة عميل", f"عميل ID: {cid}")
                        st.success("تم تسجيل العميل بنجاح.")
                    except sqlite3.IntegrityError:
                        st.error("رقم الهاتف مسجل مسبقاً.")
                else:
                    st.error("يرجى ملء الحقول الإلزامية.")
                    
    with t2:
        df_c = fetch_data("SELECT c.id, c.name, c.phone, m.neck, m.chest FROM customers c JOIN measurements m ON c.id=m.customer_id")
        if not df_c.empty:
            target_id = st.selectbox("اختر العميل", df_c['id'].tolist(), format_func=lambda x: df_c[df_c['id']==x]['name'].values[0])
            with st.form("edit_c"):
                new_name = st.text_input("الاسم الجديد", value=df_c[df_c['id']==target_id]['name'].values[0])
                if st.form_submit_button("تحديث البيانات"):
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.cursor().execute("UPDATE customers SET name=? WHERE id=?", (new_name, target_id))
                        conn.commit()
                    log_action(st.session_state.user_id, "تعديل عميل", f"عميل ID: {target_id}")
                    st.success("تم التحديث")
                    st.rerun()
            if st.session_state.role == "مدير":
                if st.button("❌ حذف العميل نهائياً", type="primary"):
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.cursor().execute("DELETE FROM customers WHERE id=?", (target_id,))
                        conn.commit()
                    log_action(st.session_state.user_id, "حذف عميل", f"عميل ID: {target_id}")
                    st.success("تم الحذف.")
                    st.rerun()
                    
    with t3:
        if not df_c.empty:
            buf = io.BytesIO()
            df_c.to_excel(buf, index=False, engine='openpyxl')
            st.download_button("📥 تصدير لقاعدة العملاء (Excel)", data=buf.getvalue(), file_name="customers.xlsx", mime="application/vnd.ms-excel")

# ------------------------------------------
# 3. إدارة المخزون وحركة الأصناف
# ------------------------------------------
elif menu == "📦 إدارة المخزون والموردين":
    st.title("📦 المستودع، الموردين وحركة الأصناف")
    tb1, tb2, tb3 = st.tabs(["🏭 الموردين", "➕ إضافة صنف جديد", "🔄 حركة المخزون (صرف/إضافة)"])
    
    with tb1:
        with st.form("add_supplier"):
            s_name = st.text_input("اسم المورد")
            s_phone = st.text_input("رقم هاتف المورد")
            if st.form_submit_button("حفظ المورد"):
                with sqlite3.connect(DB_NAME) as conn:
                    conn.cursor().execute("INSERT INTO suppliers (name, phone) VALUES (?, ?)", (s_name, s_phone))
                    conn.commit()
                st.success("تمت الإضافة.")
        st.dataframe(fetch_data("SELECT * FROM suppliers"), use_container_width=True)

    with tb2:
        df_sup = fetch_data("SELECT id, name FROM suppliers")
        sup_dict = dict(zip(df_sup['id'], df_sup['name'])) if not df_sup.empty else {0: "بدون مورد"}
        with st.form("add_item"):
            item_n = st.text_input("اسم الصنف (قماش، زرار..)")
            sup_id = st.selectbox("المورد", options=list(sup_dict.keys()), format_func=lambda x: sup_dict.get(x, "بدون"))
            col_p1, col_p2 = st.columns(2)
            p_price = col_p1.number_input("سعر الشراء (التكلفة)", 0.0)
            s_price = col_p2.number_input("سعر البيع للعميل", 0.0)
            qty = st.number_input("الرصيد الافتتاحي", 0.0)
            if st.form_submit_button("حفظ الصنف"):
                with sqlite3.connect(DB_NAME) as conn:
                    c = conn.cursor()
                    c.execute("INSERT INTO inventory (item_name, supplier_id, purchase_price, selling_price, quantity) VALUES (?, ?, ?, ?, ?)",
                              (item_n, sup_id if sup_id!=0 else None, p_price, s_price, qty))
                    c.execute("INSERT INTO stock_movements (item_id, movement_type, qty_changed, user_id, date, notes) VALUES (?, 'إضافة', ?, ?, ?, 'رصيد افتتاحي')",
                              (c.lastrowid, qty, st.session_state.user_id, datetime.now().strftime("%Y-%m-%d")))
                    conn.commit()
                st.success("تم الإضافة للمستودع.")
        st.dataframe(fetch_data("SELECT i.id, i.item_name, s.name as supplier, i.quantity, i.purchase_price FROM inventory i LEFT JOIN suppliers s ON i.supplier_id=s.id"), use_container_width=True)

    with tb3:
        df_inv = fetch_data("SELECT id, item_name, quantity FROM inventory")
        if not df_inv.empty:
            inv_dict = dict(zip(df_inv['id'], df_inv['item_name']))
            with st.form("stock_move"):
                i_id = st.selectbox("الصنف", options=list(inv_dict.keys()), format_func=lambda x: inv_dict[x])
                m_type = st.radio("نوع الحركة", ["صرف", "إضافة"])
                m_qty = st.number_input("الكمية", 0.1)
                m_notes = st.text_input("ملاحظات (مثال: منصرف لطلب رقم كذا)")
                if st.form_submit_button("تنفيذ الحركة"):
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        # التحديث
                        op = "+" if m_type == "إضافة" else "-"
                        c.execute(f"UPDATE inventory SET quantity = quantity {op} ? WHERE id = ?", (m_qty, i_id))
                        c.execute("INSERT INTO stock_movements (item_id, movement_type, qty_changed, user_id, date, notes) VALUES (?, ?, ?, ?, ?, ?)",
                                  (i_id, m_type, m_qty, st.session_state.user_id, datetime.now().strftime("%Y-%m-%d"), m_notes))
                        conn.commit()
                    log_action(st.session_state.user_id, f"حركة مخزون ({m_type})", f"صنف ID: {i_id}")
                    st.success("تم تحديث المخزون.")
            
            st.subheader("سجل الحركات (Audit Trail)")
            st.dataframe(fetch_data("SELECT sm.date, i.item_name, sm.movement_type, sm.qty_changed, sm.notes FROM stock_movements sm JOIN inventory i ON sm.item_id=i.id ORDER BY sm.id DESC LIMIT 20"), use_container_width=True)

# ------------------------------------------
# 4. الطلبات والفواتير والـ PDF
# ------------------------------------------
elif menu == "🧾 الفواتير والمدفوعات":
    st.title("🧾 نظام الفواتير والمقبوضات")
    
    def make_pdf(inv_no, c_name, details, total, paid):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(190, 10, txt="Atelier Master - Official Invoice", ln=True, align='C')
        pdf.line(10, 20, 200, 20)
        pdf.set_font("Arial", size=12)
        pdf.ln(10)
        pdf.cell(190, 10, txt=f"Invoice Number: {inv_no}", ln=True)
        pdf.cell(190, 10, txt=f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=True)
        pdf.cell(190, 10, txt=f"Client Name: {c_name}", ln=True)
        pdf.cell(190, 10, txt=f"Order Details: {details}", ln=True)
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 10, txt=f"Total Amount: {total} EGP", ln=True)
        pdf.cell(190, 10, txt=f"Paid Amount: {paid} EGP", ln=True)
        pdf.cell(190, 10, txt=f"Remaining Balance: {total - paid} EGP", ln=True)
        return pdf.output(dest='S').encode('latin-1')

    t1, t2 = st.tabs(["🛒 إنشاء فاتورة تفصيل", "💸 سداد الدفعات والطباعة"])
    
    with t1:
        df_clients = fetch_data("SELECT id, name FROM customers")
        if not df_clients.empty:
            c_dict = dict(zip(df_clients['id'], df_clients['name']))
            with st.form("add_order"):
                cid = st.selectbox("العميل", options=list(c_dict.keys()), format_func=lambda x: c_dict[x])
                details = st.text_area("تفاصيل الموديل والتفصيل")
                tot = st.number_input("إجمالي الحساب (ج.م)", min_value=0.0)
                first_pay = st.number_input("مقدم الحجز (ج.م)", min_value=0.0)
                status = st.selectbox("الحالة", ["قيد التنفيذ", "بروفة", "تم التسليم"])
                
                if st.form_submit_button("إصدار الفاتورة"):
                    inv = f"INV-{datetime.now().strftime('%y%m%d%H%M')}"
                    with sqlite3.connect(DB_NAME) as conn:
                        c = conn.cursor()
                        c.execute("INSERT INTO orders (invoice_no, customer_id, employee_id, details, total_price, status, order_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  (inv, cid, st.session_state.user_id, details, tot, status, datetime.now().strftime("%Y-%m-%d")))
                        oid = c.lastrowid
                        if first_pay > 0:
                            c.execute("INSERT INTO payments (order_id, amount, payment_date, user_id) VALUES (?, ?, ?, ?)",
                                      (oid, first_pay, datetime.now().strftime("%Y-%m-%d"), st.session_state.user_id))
                        conn.commit()
                    log_action(st.session_state.user_id, "إصدار فاتورة", f"فاتورة: {inv}")
                    st.success(f"تم التسجيل برقم {inv}")
                    st.rerun()

    with t2:
        df_o = fetch_data("SELECT o.id, o.invoice_no, c.name, o.details, o.total_price FROM orders o JOIN customers c ON o.customer_id = c.id")
        if not df_o.empty:
            oid = st.selectbox("اختر الفاتورة", df_o['id'].tolist(), format_func=lambda x: df_o[df_o['id']==x]['invoice_no'].values[0])
            o_data = df_o[df_o['id']==oid].iloc[0]
            
            pays = fetch_data(f"SELECT amount, payment_date FROM payments WHERE order_id={oid}")
            t_paid = pays['amount'].sum() if not pays.empty else 0.0
            
            st.info(f"العميل: {o_data['name']} | الإجمالي: {o_data['total_price']} | المدفوع: {t_paid} | المتبقي: {o_data['total_price'] - t_paid}")
            
            with st.form("pay_form"):
                new_p = st.number_input("تسجيل دفعة جديدة", min_value=1.0)
                if st.form_submit_button("تأكيد الدفع"):
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.cursor().execute("INSERT INTO payments (order_id, amount, payment_date, user_id) VALUES (?, ?, ?, ?)",
                                              (oid, new_p, datetime.now().strftime("%Y-%m-%d"), st.session_state.user_id))
                        conn.commit()
                    log_action(st.session_state.user_id, "تسجيل دفعة", f"لطلب ID: {oid}")
                    st.success("تم الحفظ")
                    st.rerun()
            
            pdf_data = make_pdf(o_data['invoice_no'], o_data['name'], o_data['details'], o_data['total_price'], t_paid)
            st.download_button("🖨️ طباعة الفاتورة (PDF)", data=pdf_data, file_name=f"{o_data['invoice_no']}.pdf", mime="application/pdf")

# ------------------------------------------
# 5. الإعدادات والمديرين
# ------------------------------------------
elif menu == "⚙️ إعدادات النظام":
    st.title("⚙️ الصيانة والأمان (للمديرين فقط)")
    if st.session_state.role != "مدير":
        st.error("🛑 ليس لديك صلاحية لدخول هذا القسم.")
    else:
        tb_users, tb_backup, tb_audit = st.tabs(["👥 إدارة المستخدمين", "💾 النسخ الاحتياطي", "🕵️ سجل التدقيق"])
        
        with tb_users:
            with st.form("new_user"):
                col1, col2 = st.columns(2)
                u_name = col1.text_input("اسم المستخدم")
                u_pwd = col2.text_input("كلمة المرور", type="password")
                u_role = st.selectbox("الصلاحية", ["مدير", "محاسب", "خياط", "موظف استقبال"])
                if st.form_submit_button("إضافة موظف"):
                    if len(u_pwd) < 6:
                        st.error("كلمة المرور قصيرة جداً.")
                    else:
                        try:
                            with sqlite3.connect(DB_NAME) as conn:
                                conn.cursor().execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                                                      (u_name, hash_password(u_pwd), u_role, datetime.now().strftime("%Y-%m-%d")))
                                conn.commit()
                            log_action(st.session_state.user_id, "إنشاء مستخدم", f"مستخدم: {u_name}")
                            st.success("تم الإضافة.")
                        except sqlite3.IntegrityError:
                            st.error("اسم المستخدم موجود.")
            st.dataframe(fetch_data("SELECT id, username, role, created_at FROM users"), use_container_width=True)

        with tb_backup:
            st.write("أنشئ نقطة استعادة لتأمين بيانات المشغل.")
            if st.button("🚀 إنشاء نسخة احتياطية (Backup)"):
                bname = f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db"
                shutil.copyfile(DB_NAME, os.path.join(BACKUP_DIR, bname))
                st.success(f"تم الحفظ: {bname}")
            
            blist = os.listdir(BACKUP_DIR)
            if blist:
                sel_b = st.selectbox("استعادة النظام من نسخة قديمة", blist)
                if st.button("⚠️ تأكيد الاستعادة (Restore)"):
                    shutil.copyfile(os.path.join(BACKUP_DIR, sel_b), DB_NAME)
                    st.success("تمت الاستعادة، يرجى إعادة تشغيل التطبيق.")
                    
        with tb_audit:
            st.write("مراقبة تحركات جميع الموظفين داخل النظام.")
            st.dataframe(fetch_data("SELECT a.timestamp, u.username, a.action, a.target FROM audit_logs a JOIN users u ON a.user_id = u.id ORDER BY a.id DESC LIMIT 100"), use_container_width=True)

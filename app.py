import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import plotly.express as px
import urllib.parse
from fpdf import FPDF

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Murlidhar Academy", layout="wide")

# --- SESSION STATE ---
if 'submitted' not in st.session_state: st.session_state.submitted = False
if 'absent_list' not in st.session_state: st.session_state.absent_list = []
if 'msg_details' not in st.session_state: st.session_state.msg_details = {}
# Fee Receipt State
if 'fee_submitted' not in st.session_state: st.session_state.fee_submitted = False
if 'last_receipt' not in st.session_state: st.session_state.last_receipt = {}

# --- GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def get_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

try:
    client = get_connection()
    sh = client.open("Murlidhar_Attendance")
    worksheet_students = sh.worksheet("Students")
    worksheet_attendance = sh.worksheet("Attendance_Log")
    worksheet_leave = sh.worksheet("Leave_Log")
    worksheet_batches = sh.worksheet("Batches")
    worksheet_fees = sh.worksheet("Fees_Log")
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# --- SIDEBAR MENU ---
st.sidebar.title("Murlidhar Academy")
menu = st.sidebar.radio("Go to", ["Mark Attendance", "Fees Management", "Student Analysis", "Download Reports", "Manage Students (Admin)", "Add Leave Note"])

# --- FUNCTION: LOAD DATA ---
def load_data():
    st.cache_data.clear()
    students = pd.DataFrame(worksheet_students.get_all_records())
    leaves = pd.DataFrame(worksheet_leave.get_all_records())
    batches = pd.DataFrame(worksheet_batches.get_all_records())
    return students, leaves, batches

def get_batch_list():
    _, _, batches_df = load_data()
    if batches_df.empty: return ["Morning", "Evening"]
    return batches_df['Batch_Name'].tolist()

# --- PDF GENERATOR CLASS ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'Murlidhar Academy', 0, 1, 'C')
        self.set_font('Arial', 'I', 10)
        self.cell(0, 10, 'Attendance & Fees Report', 0, 1, 'C')
        self.line(10, 30, 200, 30)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

# --- 1. MARK ATTENDANCE PAGE ---
if menu == "Mark Attendance":
    st.header("📝 Daily Attendance Marking")
    
    if st.session_state.submitted:
        if st.button("🔄 Start New Attendance"):
            st.session_state.submitted = False
            st.session_state.absent_list = []
            st.rerun()
    
    if not st.session_state.submitted:
        batch_options = get_batch_list()
        batch_options.insert(0, "All")
        col1, col2 = st.columns(2)
        with col1: selected_date = st.date_input("Select Date", date.today())
        with col2: selected_batch = st.selectbox("Select Batch", batch_options)
        students_df, leaves_df, _ = load_data()

        if selected_batch != "All" and not students_df.empty:
            students_df = students_df[students_df['Batch'] == selected_batch]

        if students_df.empty: st.warning("No students found.")
        else:
            students_df['Status'] = "Present"
            if not leaves_df.empty:
                for index, row in students_df.iterrows():
                    sid = row['Student_ID']
                    student_leaves = leaves_df[leaves_df['Student_ID'] == sid]
                    for _, leave in student_leaves.iterrows():
                        try:
                            s_date = datetime.strptime(str(leave['Start_Date']), "%Y-%m-%d").date()
                            e_date = datetime.strptime(str(leave['End_Date']), "%Y-%m-%d").date()
                            if s_date <= selected_date <= e_date: students_df.at[index, 'Status'] = "On Leave"
                        except: pass
            
            st.info("Uncheck box to mark Absent.")
            students_df['Present'] = students_df['Status'].apply(lambda x: True if x == 'Present' else False)
            edited_df = st.data_editor(students_df[['Student_ID', 'Name', 'Present', 'Status']], 
                column_config={"Present": st.column_config.CheckboxColumn("Present?", default=True), "Status": st.column_config.TextColumn("Status", disabled=True), "Student_ID": st.column_config.NumberColumn("ID", disabled=True)}, 
                hide_index=True, use_container_width=True)

            st.divider()
            c1, c2 = st.columns(2)
            with c1: subject = st.text_input("Subject", placeholder="e.g. Maths")
            with c2: topic = st.text_input("Topic Name", placeholder="e.g. Chapter 1")

            if st.button("Submit Attendance", type="primary"):
                records_to_save = []
                absent_list = []
                for index, row in edited_df.iterrows():
                    final_status = ""
                    if row['Present']: final_status = "Present"
                    elif row['Status'] == "On Leave": final_status = "On Leave"
                    else:
                        final_status = "Absent"
                        orig_row = students_df[students_df['Student_ID'] == row['Student_ID']].iloc[0]
                        absent_list.append({"Name": row['Name'], "Student_Mobile": orig_row['Student_Mobile'], "Parent_Mobile": orig_row['Parent_Mobile']})
                    records_to_save.append([str(selected_date), datetime.now().strftime("%H:%M:%S"), int(row['Student_ID']), row['Name'], final_status, subject, topic])
                
                worksheet_attendance.append_rows(records_to_save)
                st.session_state.submitted = True
                st.session_state.absent_list = absent_list
                st.session_state.msg_details = {"subject": subject, "topic": topic}
                st.rerun()
    else:
        st.success("✅ Attendance Submitted!")
        absent_list = st.session_state.absent_list
        details = st.session_state.msg_details
        if absent_list:
            st.divider()
            st.subheader("📲 WhatsApp Actions")
            col_opt1, col_opt2 = st.columns(2)
            with col_opt1: msg_target = st.radio("Send To:", ["Student", "Parents"], horizontal=True)
            with col_opt2: use_custom_msg = st.checkbox("✍️ Write Custom Message?")
            
            if use_custom_msg: custom_text = st.text_area("Message:", value="Hi {name}, ")
            
            for student in absent_list:
                name = student['Name']
                number = student['Student_Mobile'] if msg_target == "Student" else student['Parent_Mobile']
                if use_custom_msg: final_msg = custom_text.replace("{name}", name)
                else:
                    if msg_target == "Student": final_msg = f"Hi {name}, you were absent in {details['subject']}. Topic: {details['topic']}."
                    else: final_msg = f"Namaste, {name} is absent today in Murlidhar Academy. Topic missed: {details['topic']}."
                url = f"https://wa.me/{number}?text={urllib.parse.quote(final_msg)}"
                st.link_button(f"Message {name} 🟢", url)

# --- 2. FEES MANAGEMENT ---
elif menu == "Fees Management":
    st.header("💰 Fees Management")
    if st.session_state.fee_submitted:
        if st.button("🔄 Add Another Fee"):
            st.session_state.fee_submitted = False
            st.session_state.last_receipt = {}
            st.rerun()

    if not st.session_state.fee_submitted:
        students_df, _, _ = load_data()
        if students_df.empty: st.warning("No students available.")
        else:
            with st.form("fee_form", clear_on_submit=False):
                st.subheader("Payment Details")
                s_name = st.selectbox("Select Student", students_df['Name'].unique())
                col1, col2 = st.columns(2)
                with col1: fee_date = st.date_input("Date", date.today())
                with col2: amount = st.number_input("Amount (₹)", min_value=1, step=100)
                col3, col4 = st.columns(2)
                with col3: mode = st.selectbox("Payment Mode", ["Cash", "UPI", "Bank Transfer", "Cheque"])
                with col4: status = st.selectbox("Status", ["Fees Complete", "Partial Payment", "Pending"])
                remarks = st.text_input("Remarks", placeholder="e.g., January Fees")
                
                if st.form_submit_button("Submit Fee", type="primary"):
                    s_data = students_df[students_df['Name'] == s_name].iloc[0]
                    sid = int(s_data['Student_ID'])
                    s_mob = s_data['Student_Mobile']
                    p_mob = s_data['Parent_Mobile']
                    receipt_no = f"REC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    worksheet_fees.append_row([receipt_no, str(fee_date), sid, s_name, amount, mode, status, remarks])
                    st.session_state.fee_submitted = True
                    st.session_state.last_receipt = {"name": s_name, "amount": amount, "date": str(fee_date), "mode": mode, "status": status, "no": receipt_no, "s_mob": s_mob, "p_mob": p_mob}
                    st.rerun()
    else:
        receipt = st.session_state.last_receipt
        st.success("✅ Fee Saved Successfully!")
        c1, c2 = st.columns([1, 1])
        
        pdf = PDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.set_fill_color(240, 240, 240)
        pdf.rect(10, 45, 190, 80, 'F')
        pdf.ln(10)
        pdf.cell(0, 10, f"Receipt No: {receipt['no']}", 0, 1, 'R')
        pdf.cell(0, 10, f"Date: {receipt['date']}", 0, 1, 'R')
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(50, 10, "Student Name:", 0, 0)
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, receipt['name'], 0, 1)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(50, 10, "Amount Paid:", 0, 0)
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, f"Rs. {receipt['amount']}/-", 0, 1)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(50, 10, "Payment Mode:", 0, 0)
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, receipt['mode'], 0, 1)
        
        pdf_bytes = pdf.output(dest='S').encode('latin-1', 'ignore')
        
        with c1:
            st.download_button("Download PDF Receipt", pdf_bytes, f"Receipt_{receipt['name']}.pdf", "application/pdf")
        with c2:
            wa_msg = f"*Murlidhar Academy Receipt*\nName: {receipt['name']}\nAmount: ₹{receipt['amount']}\nDate: {receipt['date']}\nMode: {receipt['mode']}\nThank you!"
            st.link_button(f"Message {receipt['name']}", f"https://wa.me/{receipt['s_mob']}?text={urllib.parse.quote(wa_msg)}")

# --- 3. STUDENT ANALYSIS PAGE ---
elif menu == "Student Analysis":
    st.header("📊 Student Report")
    students_df, _, _ = load_data()
    all_attendance = pd.DataFrame(worksheet_attendance.get_all_records())
    
    if not students_df.empty:
        s_name = st.selectbox("Select Student", students_df['Name'].unique())
        s_details = students_df[students_df['Name'] == s_name].iloc[0]
        
        with st.expander("💬 WhatsApp Message"):
            msg_to = st.radio("To:", ["Student", "Parent"], horizontal=True, key="anl_rad")
            custom_msg_anl = st.text_area("Message:", value=f"Hi {s_name}, ")
            num = s_details['Student_Mobile'] if msg_to == "Student" else s_details['Parent_Mobile']
            st.link_button("Open WhatsApp", f"https://wa.me/{num}?text={urllib.parse.quote(custom_msg_anl)}")

        if not all_attendance.empty:
            student_data = all_attendance[all_attendance['Name'] == s_name]
            if not student_data.empty:
                total = len(student_data)
                present = len(student_data[student_data['Status'] == 'Present'])
                c1, c2 = st.columns(2)
                c1.metric("Total Classes", total)
                c2.metric("Attendance %", f"{round((present/total)*100, 1)}%")
                fig = px.pie(values=[present, total-present], names=['Present', 'Absent/Leave'], 
                             title=f"Attendance: {s_name}", color_discrete_sequence=['green', 'red'])
                st.plotly_chart(fig)
            else: st.warning("No records found.")
    else: st.info("No students found.")

# --- 4. DOWNLOAD REPORTS (UPDATED WITH BATCH) ---
elif menu == "Download Reports":
    st.header("📥 Download Attendance Reports")
    all_attendance = pd.DataFrame(worksheet_attendance.get_all_records())
    students_df, _, _ = load_data()
    batch_list = get_batch_list()
    
    if all_attendance.empty: st.warning("No data available.")
    else:
        # Layout: 4 Columns
        c1, c2, c3, c4 = st.columns(4)
        with c1: start_date = st.date_input("From", date.today().replace(day=1))
        with c2: end_date = st.date_input("To", date.today())
        
        # Batch Filter
        with c3: 
            selected_batch = st.selectbox("Select Batch", ["All Batches"] + batch_list)
        
        # Filter Student List based on Batch
        student_options = ["All Students"]
        if selected_batch != "All Batches" and not students_df.empty:
            # Only show students belonging to selected batch
            batch_students = students_df[students_df['Batch'] == selected_batch]['Name'].tolist()
            student_options += batch_students
        elif not students_df.empty:
            student_options += students_df['Name'].tolist()
            
        with c4: selected_student = st.selectbox("Select Student", student_options)

        if st.button("Generate PDF", type="primary"):
            # 1. Filter by Date
            all_attendance['Date_Obj'] = pd.to_datetime(all_attendance['Date'], format='%Y-%m-%d', errors='coerce').dt.date
            mask = (all_attendance['Date_Obj'] >= start_date) & (all_attendance['Date_Obj'] <= end_date)
            filtered_df = all_attendance.loc[mask]
            
            # 2. Filter by Batch (Indirectly via Name)
            if selected_batch != "All Batches":
                # Get names of students in this batch
                valid_names = students_df[students_df['Batch'] == selected_batch]['Name'].tolist()
                filtered_df = filtered_df[filtered_df['Name'].isin(valid_names)]

            # 3. Filter by Student
            if selected_student != "All Students":
                filtered_df = filtered_df[filtered_df['Name'] == selected_student]
            
            if filtered_df.empty: st.error(f"No records found for Batch: {selected_batch}")
            else:
                pdf = PDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.cell(200, 10, txt=f"Report: {selected_batch} ({start_date} to {end_date})", ln=True, align='C')
                pdf.ln(10)
                pdf.set_fill_color(200, 220, 255)
                pdf.set_font("Arial", 'B', 10)
                for h in ["Date", "Name", "Status", "Subject", "Topic"]: pdf.cell(38, 10, h, 1, 0, 'C', 1)
                pdf.ln()
                pdf.set_font("Arial", size=10)
                for _, row in filtered_df.iterrows():
                    s = str(row.get('Status', ''))
                    pdf.set_text_color(255, 0, 0) if s == 'Absent' else pdf.set_text_color(0, 0, 0)
                    pdf.cell(38, 10, str(row.get('Date', '')), 1, 0, 'C')
                    pdf.cell(38, 10, str(row.get('Name', '')), 1, 0, 'L')
                    pdf.cell(38, 10, s, 1, 0, 'C')
                    pdf.set_text_color(0, 0, 0)
                    pdf.cell(38, 10, str(row.get('Subject', '')), 1, 0, 'L')
                    pdf.cell(38, 10, str(row.get('Topic', '')), 1, 1, 'L')
                
                st.download_button("Download PDF", pdf.output(dest='S').encode('latin-1', 'ignore'), f"Report_{selected_batch}.pdf", "application/pdf")

# --- 5. ADMIN PANEL ---
elif menu == "Manage Students (Admin)":
    st.header("🛠️ Admin Panel")
    t1, t2, t3, t4 = st.tabs(["Add", "Edit", "Delete", "Batches"])
    batch_list = get_batch_list()

    with t1:
        with st.form("add_form", clear_on_submit=False):
            nid = st.number_input("ID", min_value=1, step=1, key="ai")
            nnm = st.text_input("Name", key="an")
            nb = st.selectbox("Batch", batch_list, key="ab")
            nsm = st.text_input("S. Mobile", value="91", key="asm")
            npm = st.text_input("P. Mobile", value="91", key="apm")
            if st.form_submit_button("Add"):
                df, _, _ = load_data()
                if not df.empty and nid in df['Student_ID'].values: st.error("ID Exists!")
                elif nnm == "": st.error("Name Required")
                else:
                    worksheet_students.append_row([int(nid), nnm, nb, nsm, npm])
                    st.success("Added!")
                    st.session_state.an = ""
                    st.session_state.ai = nid + 1
                    st.rerun()
    with t2:
        df, _, _ = load_data()
        if not df.empty:
            enm = st.selectbox("Select", df['Name'].tolist())
            cur = df[df['Name'] == enm].iloc[0]
            with st.form("edit"):
                nn = st.text_input("Name", value=cur['Name'])
                try: bi = batch_list.index(cur['Batch'])
                except: bi = 0
                nb = st.selectbox("Batch", batch_list, index=bi)
                ns = st.text_input("S. Mob", value=str(cur['Student_Mobile']))
                np = st.text_input("P. Mob", value=str(cur['Parent_Mobile']))
                if st.form_submit_button("Update"):
                    c = worksheet_students.find(str(cur['Student_ID']))
                    worksheet_students.update(f"B{c.row}:E{c.row}", [[nn, nb, ns, np]])
                    st.success("Updated!")
                    st.rerun()
    with t3:
        df, _, _ = load_data()
        if not df.empty:
            dn = st.selectbox("Delete Student", df['Name'].tolist())
            if st.button("DELETE", type="primary"):
                sid = df[df['Name'] == dn]['Student_ID'].values[0]
                c = worksheet_students.find(str(sid))
                worksheet_students.delete_rows(c.row)
                st.success("Deleted!")
                st.rerun()
    with t4:
        with st.form("nbatch"):
            bn = st.text_input("New Batch")
            if st.form_submit_button("Create"):
                worksheet_batches.append_row([bn])
                st.success("Created!")
                st.rerun()

# --- 6. LEAVE NOTE ---
elif menu == "Add Leave Note":
    st.header("🗓️ Leave Note")
    df, _, _ = load_data()
    if not df.empty:
        with st.form("leave"):
            sn = st.selectbox("Student", df['Name'].unique())
            c1, c2 = st.columns(2)
            d1 = c1.date_input("From")
            d2 = c2.date_input("To")
            r = st.text_input("Reason")
            if st.form_submit_button("Save"):
                sid = df[df['Name'] == sn]['Student_ID'].values[0]
                worksheet_leave.append_row([int(sid), sn, str(d1), str(d2), r])
                st.success("Saved!")

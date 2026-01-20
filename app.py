import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import plotly.express as px

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Murlidhar Attendance", layout="wide")

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
    # NEW: Batches Sheet
    worksheet_batches = sh.worksheet("Batches") 
except Exception as e:
    st.error(f"Connection Error or 'Batches' tab missing: {e}")
    st.stop()

# --- SIDEBAR MENU ---
st.sidebar.title("Murlidhar Academy")
menu = st.sidebar.radio("Go to", ["Mark Attendance", "Student Analysis", "Manage Students (Admin)", "Add Leave Note"])

# --- FUNCTION: LOAD DATA ---
def load_data():
    st.cache_data.clear()
    students = pd.DataFrame(worksheet_students.get_all_records())
    leaves = pd.DataFrame(worksheet_leave.get_all_records())
    batches = pd.DataFrame(worksheet_batches.get_all_records())
    return students, leaves, batches

# --- HELPER: GET BATCH LIST ---
def get_batch_list():
    _, _, batches_df = load_data()
    if batches_df.empty:
        return ["Morning", "Evening"] # Default fallback
    return batches_df['Batch_Name'].tolist()

# --- 1. MARK ATTENDANCE PAGE ---
if menu == "Mark Attendance":
    st.header("📝 Daily Attendance Marking")
    
    # Get Dynamic Batches
    batch_options = get_batch_list()
    batch_options.insert(0, "All") # Add 'All' at the start

    col1, col2 = st.columns(2)
    with col1:
        selected_date = st.date_input("Select Date", date.today())
    with col2:
        selected_batch = st.selectbox("Select Batch", batch_options)

    students_df, leaves_df, _ = load_data()

    if selected_batch != "All" and not students_df.empty:
        students_df = students_df[students_df['Batch'] == selected_batch]

    if students_df.empty:
        st.warning("No students found in this batch.")
    else:
        students_df['Status'] = "Present"
        students_df['Is_Leave'] = False 

        if not leaves_df.empty:
            for index, row in students_df.iterrows():
                sid = row['Student_ID']
                student_leaves = leaves_df[leaves_df['Student_ID'] == sid]
                for _, leave in student_leaves.iterrows():
                    try:
                        s_date = datetime.strptime(str(leave['Start_Date']), "%Y-%m-%d").date()
                        e_date = datetime.strptime(str(leave['End_Date']), "%Y-%m-%d").date()
                        if s_date <= selected_date <= e_date:
                            students_df.at[index, 'Status'] = "On Leave"
                            students_df.at[index, 'Is_Leave'] = True
                    except:
                        pass
        
        st.info("Uncheck box to mark Absent.")
        
        students_df['Present'] = students_df['Status'].apply(lambda x: True if x == 'Present' else False)
        
        edited_df = st.data_editor(
            students_df[['Student_ID', 'Name', 'Present', 'Status']],
            column_config={
                "Present": st.column_config.CheckboxColumn("Present?", default=True),
                "Status": st.column_config.TextColumn("Status", disabled=True),
                "Student_ID": st.column_config.NumberColumn("ID", disabled=True)
            },
            hide_index=True,
            use_container_width=True
        )

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            subject = st.selectbox("Subject", ["Maths", "Reasoning", "Polity", "History", "Geography", "English", "Gujarati"])
        with c2:
            topic = st.text_input("Topic Name", placeholder="e.g. Bandharan Part-1")

        if st.button("Submit Attendance", type="primary"):
            records_to_save = []
            absent_list = []
            
            for index, row in edited_df.iterrows():
                final_status = ""
                if row['Present']:
                    final_status = "Present"
                elif row['Status'] == "On Leave":
                    final_status = "On Leave"
                else:
                    final_status = "Absent"
                    orig_row = students_df[students_df['Student_ID'] == row['Student_ID']].iloc[0]
                    absent_list.append({
                        "Name": row['Name'],
                        "Student_Mobile": orig_row['Student_Mobile'],
                        "Parent_Mobile": orig_row['Parent_Mobile']
                    })

                records_to_save.append([
                    str(selected_date),
                    datetime.now().strftime("%H:%M:%S"),
                    int(row['Student_ID']),
                    row['Name'],
                    final_status,
                    subject,
                    topic
                ])
            
            worksheet_attendance.append_rows(records_to_save)
            st.success("✅ Attendance Saved!")
            
            if absent_list:
                st.divider()
                st.subheader("📲 WhatsApp Actions")
                msg_target = st.radio("Send Message To:", ["Student", "Parents"], horizontal=True)
                
                for student in absent_list:
                    name = student['Name']
                    if msg_target == "Student":
                        number = student['Student_Mobile']
                        msg = f"Hi {name}, you were absent in {subject} class. Topic: {topic}."
                    else:
                        number = student['Parent_Mobile']
                        msg = f"Namaste, {name} is absent today in Murlidhar Academy. Topic missed: {topic}."
                    
                    url = f"https://wa.me/{number}?text={msg}"
                    st.link_button(f"Message {name}", url)

# --- 2. STUDENT ANALYSIS PAGE ---
elif menu == "Student Analysis":
    st.header("📊 Student Report")
    students_df, _, _ = load_data()
    all_attendance = pd.DataFrame(worksheet_attendance.get_all_records())
    
    if all_attendance.empty:
        st.info("No data yet.")
    else:
        if not students_df.empty:
            s_name = st.selectbox("Select Student", students_df['Name'].unique())
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
            else:
                st.warning("No records found.")

# --- 3. MANAGE STUDENTS & BATCHES ---
elif menu == "Manage Students (Admin)":
    st.header("🛠️ Admin Panel")
    
    # NEW TAB: Manage Batches
    tab1, tab2, tab3, tab4 = st.tabs(["Add Student", "Edit Student", "Delete Student", "Manage Batches"])
    
    batch_list = get_batch_list()

    # -- ADD STUDENT --
    with tab1:
        st.subheader("Add New Student")
        with st.form("add_student_form", clear_on_submit=True):
            new_id = st.number_input("Student ID / Roll No", min_value=1, step=1, format="%d")
            new_name = st.text_input("Full Name")
            # Use Dynamic Batch List
            new_batch = st.selectbox("Batch", batch_list)
            s_mobile = st.text_input("Student Mobile", value="91")
            p_mobile = st.text_input("Parent Mobile", value="91")
            
            if st.form_submit_button("Add Student"):
                students_df, _, _ = load_data()
                if not students_df.empty and new_id in students_df['Student_ID'].values:
                    st.error("⚠️ ID already exists!")
                else:
                    worksheet_students.append_row([int(new_id), new_name, new_batch, s_mobile, p_mobile])
                    st.success(f"✅ {new_name} added to {new_batch}!")
                    st.rerun()

    # -- EDIT STUDENT --
    with tab2:
        st.subheader("Edit Student")
        students_df, _, _ = load_data()
        if not students_df.empty:
            edit_name = st.selectbox("Select Student", students_df['Name'].tolist())
            curr = students_df[students_df['Name'] == edit_name].iloc[0]
            
            with st.form("edit_form"):
                st.write(f"ID: {curr['Student_ID']}")
                n_name = st.text_input("Name", value=curr['Name'])
                # Dynamic Batch List with current Index
                try:
                    b_index = batch_list.index(curr['Batch'])
                except:
                    b_index = 0
                n_batch = st.selectbox("Batch", batch_list, index=b_index)
                
                n_smob = st.text_input("Student Mobile", value=str(curr['Student_Mobile']))
                n_pmob = st.text_input("Parent Mobile", value=str(curr['Parent_Mobile']))
                
                if st.form_submit_button("Update"):
                    cell = worksheet_students.find(str(curr['Student_ID']))
                    worksheet_students.update(f"B{cell.row}:E{cell.row}", [[n_name, n_batch, n_smob, n_pmob]])
                    st.success("Updated!")
                    st.rerun()

    # -- DELETE STUDENT --
    with tab3:
        st.subheader("Delete Student")
        students_df, _, _ = load_data()
        if not students_df.empty:
            del_name = st.selectbox("Select Student", students_df['Name'].tolist(), key="del")
            if st.button("DELETE", type="primary"):
                sid = students_df[students_df['Name'] == del_name]['Student_ID'].values[0]
                cell = worksheet_students.find(str(sid))
                worksheet_students.delete_rows(cell.row)
                st.success("Deleted!")
                st.rerun()

    # -- NEW: MANAGE BATCHES --
    with tab4:
        st.subheader("Manage Batches")
        st.write("Current Batches:", ", ".join(batch_list))
        
        with st.form("add_batch"):
            new_b_name = st.text_input("New Batch Name (e.g., GPSC-2025)")
            if st.form_submit_button("Create Batch"):
                if new_b_name:
                    worksheet_batches.append_row([new_b_name])
                    st.success(f"Batch '{new_b_name}' created!")
                    st.rerun()
                else:
                    st.error("Please enter a name.")

# --- 4. ADD LEAVE PAGE ---
elif menu == "Add Leave Note":
    st.header("🗓️ Add Leave Note")
    students_df, _, _ = load_data()
    
    if not students_df.empty:
        with st.form("leave_form"):
            s_name = st.selectbox("Student Name", students_df['Name'].unique())
            c1, c2 = st.columns(2)
            start_d = c1.date_input("From")
            end_d = c2.date_input("To")
            reason = st.text_input("Reason")
            
            if st.form_submit_button("Save Leave"):
                sid = students_df[students_df['Name'] == s_name]['Student_ID'].values[0]
                worksheet_leave.append_row([int(sid), s_name, str(start_d), str(end_d), reason])
                st.success("Leave Added!")

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
    # Secrets mathi credentials levu
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

try:
    client = get_connection()
    sh = client.open("Murlidhar_Attendance") # Sheet nu naam barabar hovu joye
    worksheet_students = sh.worksheet("Students")
    worksheet_attendance = sh.worksheet("Attendance_Log")
    worksheet_leave = sh.worksheet("Leave_Log")
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# --- SIDEBAR MENU ---
st.sidebar.title("Murlidhar Academy")
menu = st.sidebar.radio("Go to", ["Mark Attendance", "Student Analysis", "Add Leave Note"])

# --- FUNCTION: LOAD DATA ---
def load_data():
    students = pd.DataFrame(worksheet_students.get_all_records())
    leaves = pd.DataFrame(worksheet_leave.get_all_records())
    return students, leaves

# --- 1. MARK ATTENDANCE PAGE ---
if menu == "Mark Attendance":
    st.header("📝 Daily Attendance Marking")
    
    col1, col2 = st.columns(2)
    with col1:
        selected_date = st.date_input("Select Date", date.today())
    with col2:
        selected_batch = st.selectbox("Select Batch", ["Morning", "Evening", "All"])

    students_df, leaves_df = load_data()

    # Filter Logic
    if selected_batch != "All" and not students_df.empty:
        students_df = students_df[students_df['Batch'] == selected_batch]

    if students_df.empty:
        st.warning("No students found. Please add students in Google Sheet first.")
    else:
        # Default Settings
        students_df['Status'] = "Present"
        students_df['Is_Leave'] = False 

        # Leave Logic Check
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
                        pass # Date format error ignore kare
        
        st.info("Tip: Uncheck box to mark Absent.")
        
        # Prepare Data for Editor
        students_df['Present'] = students_df['Status'].apply(lambda x: True if x == 'Present' else False)
        
        edited_df = st.data_editor(
            students_df[['Student_ID', 'Name', 'Present', 'Status']],
            column_config={
                "Present": st.column_config.CheckboxColumn("Present?", default=True),
                "Status": st.column_config.TextColumn("Status", disabled=True)
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
                    # Get mobile numbers
                    orig_row = students_df[students_df['Student_ID'] == row['Student_ID']].iloc[0]
                    absent_list.append({
                        "Name": row['Name'],
                        "Student_Mobile": orig_row['Student_Mobile'],
                        "Parent_Mobile": orig_row['Parent_Mobile']
                    })

                records_to_save.append([
                    str(selected_date),
                    datetime.now().strftime("%H:%M:%S"),
                    row['Student_ID'],
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
                msg_target = st.radio("Who to message?", ["Student", "Parents"], horizontal=True)
                
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
    students_df, _ = load_data()
    all_attendance = pd.DataFrame(worksheet_attendance.get_all_records())
    
    if all_attendance.empty:
        st.info("No data yet.")
    else:
        s_name = st.selectbox("Select Student", students_df['Name'].unique())
        student_data = all_attendance[all_attendance['Name'] == s_name]
        
        if not student_data.empty:
            total = len(student_data)
            present = len(student_data[student_data['Status'] == 'Present'])
            
            c1, c2 = st.columns(2)
            c1.metric("Total Classes", total)
            c2.metric("Attendance", f"{round((present/total)*100, 1)}%")
            
            fig = px.pie(values=[present, total-present], names=['Present', 'Absent/Leave'], 
                         title=f"Attendance: {s_name}", color_discrete_sequence=['green', 'red'])
            st.plotly_chart(fig)
        else:
            st.warning("No records found for this student.")

# --- 3. ADD LEAVE PAGE ---
elif menu == "Add Leave Note":
    st.header("🗓️ Add Leave Note")
    students_df, _ = load_data()
    
    with st.form("leave_form"):
        s_name = st.selectbox("Select Student", students_df['Name'].unique())
        col1, col2 = st.columns(2)
        start_d = col1.date_input("From Date")
        end_d = col2.date_input("To Date")
        reason = st.text_input("Reason")
        
        if st.form_submit_button("Save Leave"):
            sid = students_df[students_df['Name'] == s_name]['Student_ID'].values[0]
            worksheet_leave.append_row([int(sid), s_name, str(start_d), str(end_d), reason])
            st.success("Leave Added Successfully!")

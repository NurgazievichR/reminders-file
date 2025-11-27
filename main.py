import json
import os
import shutil

from collections import defaultdict
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from adastra_client import AdAstraClient
from textus_cleint import TextUsClient
from graph_client import GraphClient

import time

need_date = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)).date().isoformat()
# need_date = '2025-10-13'
SYSTEM_GUID = "4212879f-9dca-4ba8-9141-65c536de9da3"

#FULL READY
def prepare_date_dir(root: str = "data", days: int = 7):
    #from here we clean every date besides [TODAY - {days}, TODAY] 
    today = date.today()

    keep = {
        (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(-1, days + 1)
    }

    try:
        dirs = os.listdir(root)
    except FileNotFoundError:
        print(f"file {root} was not found")
        return

    for d in dirs:
        full = os.path.join(root, d)

        if not os.path.isdir(full):
            continue

        if d not in keep:
            shutil.rmtree(full, ignore_errors=True)
            print(f"🧹 removed {d}")

def get_interpreter_details(client, interpreter_id):
    try:
        resp = client.get_account_detail_by_id(interpreter_id)
    except Exception as e:
        print(e)
        return None, None, None

    data = resp.get("data", resp) 
    email = data.get("email")
    phone = data.get("phoneNumber")
    name = f"{(data.get('firstName') or '').strip()} {(data.get('lastName') or '').strip()}".strip()

    return email, phone, name


def collect_all_appointments(client):

    all_appointments = []
    page = 1
    size = 100

    while True:
        params = {
            "page": page,
            "items_per_page": size,
            # "search": "jhm"
        }

        filters = {
            "accounts": [],
            "communicationTypes": [],
            "langs": [],
            "serviceTypes": [],
            "startDate": need_date,
            "endDate": need_date,
            "status" : [2] #Confirmed ones
        }

        resp = client.filter_appointments_system(
            SYSTEM_GUID,
            filters=filters,
            params=params
        )

        items = resp.get("data", [])    
        if not items:
            break

        all_appointments.extend(items)

        if len(items) < size:
            break
        page += 1

    print(f"✅ Tottally collected {len(all_appointments)} appointments")
    return all_appointments


def group_appointments(client: AdAstraClient, all_appointments):
    grouped_osi = defaultdict(list)
    grouped_vis = defaultdict(list)

    for appointment in all_appointments:
        code = appointment.get("code")
        print(f"processing {code}",end=' ')
        language_to = appointment.get("languageTo")

        if language_to == "American Sign Language":
            print('ASL')
            continue
        
        start_time = appointment.get("startTime")
        communication_type = appointment.get("fK_CommunicationType")
        is_virtual = communication_type != 'oc'
        
        assigned_interpreter_id = appointment.get("fK_Interpreter")
        if not assigned_interpreter_id:
            print("No assigned interpreter")
            continue

        grouped_dict = grouped_vis if is_virtual else grouped_osi
        interpreter_email, interpreter_phone, interpreter_full_name = get_interpreter_details(client, assigned_interpreter_id)

        if not interpreter_email:
            print('The interpreter does not have email')
            continue

        appointment_data = {
            "code": code,
            "email": interpreter_email,
            "phone": interpreter_phone,
            "interpreter_name": interpreter_full_name,

            "start_time": start_time,
            "language_to": language_to,
            "comm_type": communication_type,

            # "description": appointment.get("description"),
            # "consumer": appointment.get("consumer"),
            # "location": appointment.get("address"),
        }

        if is_virtual:
            appointment_detailed = client.get_appointment(code)
            virtual_data = {
                "virtualAddress": appointment_detailed.get("virtualAddress") or "n/a",
                "meetingPinCode": appointment_detailed.get("meetingPinCode") or "n/a",
                "pin": appointment_detailed.get("pin") or "n/a",
                "noteInterpreter": appointment_detailed.get("noteInterpreter") or "n/a",
                }
            appointment_data.update(virtual_data)

        grouped_dict[interpreter_email].append(appointment_data)
        print(f"success {interpreter_email}")
    
    return grouped_osi, grouped_vis

from datetime import datetime


def _format_time(iso_str: str) -> str:
    """'2025-11-25T14:00:00' -> '02:00 pm'."""
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%I:%M %p").lower().lstrip("0")  # 01:15 PM -> 1:15 pm


def build_vis_body(assignments: list[dict]) -> str:
    lines: list[str] = []

    lines.append(
        "Hello,\n\n"
        "Reminding you of your virtual assignment(s) for tomorrow. "
        "Please be camera presentable and ensure to join the session 5–10 minutes prior "
        "to avoid any tardiness/tech issues.\n"
    )

    assignments_sorted = sorted(assignments, key=lambda a: a["start_time"])

    for idx, a in enumerate(assignments_sorted, start=1):
        time_str = _format_time(a["start_time"])
        code = a.get("code")
        link = a.get("virtualAddress")
        meetingPinCode = a.get("meetingPinCode")
        pin = a.get("pin")
        noteInterpreter = a.get("noteInterpreter")

        lines.append(f"\n{idx}) Assignment {code}:")
        lines.append(f"\nTime: {time_str}")
        lines.append(f"\nLink: {link}")
        lines.append(f"\nDial-in or Meeting number: {meetingPinCode}")
        lines.append(f"\nPIN/Passcode: {pin}")
        lines.append(f"\nNotes: {noteInterpreter}\n")

    lines.append(
        "\nLet us know if you experience any problems right away.\n\n"
        "Thank you,\n"
        "Ramazan"
    )
    return "".join(lines)


def main():
    print(f"Processing {need_date} reminders...")

    #We create data folder where we will keep info about reminders, for debugging if there are some wrong cases for example
    date_dir = os.path.join("data", need_date)
    os.makedirs(date_dir, exist_ok=True) 
    prepare_date_dir()

    adastra_client = AdAstraClient()
    adastra_client.login()

    appointments = collect_all_appointments(adastra_client)
    with open(os.path.join(date_dir, "appointments.json"), "w", encoding="utf-8") as f:
        json.dump(appointments, f, indent=4, ensure_ascii=False)

    grouped_osi, grouped_vis = group_appointments(adastra_client, appointments)
    with open(os.path.join(date_dir, "grouped_apps_osi.json"), "w", encoding="utf-8") as f:
        json.dump(grouped_osi, f, indent=4, ensure_ascii=False)
    with open(os.path.join(date_dir, "grouped_apps_vis.json"), "w", encoding="utf-8") as f:
        json.dump(grouped_vis, f, indent=4, ensure_ascii=False)

    print(f"sending OSI reminders...")
    textus_client = TextUsClient()
    
    for interpreter, assignments in grouped_osi.items():
        times = [a["start_time"] for a in assignments if a.get("start_time")]
        phone = assignments[0].get("phone").strip()
        if not phone or not times:
            print(f'error sending, phone {phone}, time {times}')
            continue
        conversation_id = textus_client.send_reminder(phone, times)
        print(f"Sent to {phone}, times: {"".join(times)}")
        if conversation_id:
            textus_client.close_conversation(conversation_id)

    print(f"sending VIS reminders...")  
    client = GraphClient()
    for interpreter, assignments in grouped_vis.items():
        to = interpreter
        # to = "interpreting@ad-astrainc.com"

        subject = "Reminder"
        body = build_vis_body(assignments)
        client.send_message(to, subject, body)
        print(f"Sent to {interpreter}")

if __name__ == '__main__':
    main()
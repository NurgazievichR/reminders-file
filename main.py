import json
import os
import shutil

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from adastra_client import AdAstraClient
from textus_cleint import TextUsClient

import time

need_date = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)).date().isoformat()
# need_date = '2025-10-13'
SYSTEM_GUID = "4212879f-9dca-4ba8-9141-65c536de9da3"


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


def get_assigned_interpreter_for_assignment(client, assignment_id):
    try:
        data = client.get_interpreters_for_assignment(assignment_id) 
    except Exception as e:
        print(f"failed to load interpreters for {assignment_id}: {e}")
        return None

    if not isinstance(data, list):
        return None

    for row in data:
        status = row.get("assignStatusName")
        if status == "Assign":
            return row.get("fK_Interpreter")

    return None


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


def group_appointments(client, all_appointments):
    grouped_osi = defaultdict(list)
    grouped_vis = defaultdict(list)

    for appointment in all_appointments:
        code = appointment.get("code")
        print(f"processing {code}",end=' ')
        status = appointment.get("statusName")
        language_to = appointment.get("languageTo")

        if status != "Confirmed" or language_to == "American Sign Language":
            print(status if status != "Confirmed" else language_to)
            continue
        
        start_time = appointment.get("startTime")
        communication_type = appointment.get("fK_CommunicationType")
        is_virtual = communication_type != 'oc'
        
        assigned_interpreter_id = get_assigned_interpreter_for_assignment(client, code)
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
            virtual_data = {
                "virtualAddress": appointment.get("virtualAddress") or "NO LINK",
                "callerNumber": appointment.get("callerNumber") or "NO NUMBER",
                "pin": appointment.get("pin") or "NO PIN"
                }
            appointment_data.update(virtual_data)

        grouped_dict[interpreter_email].append(appointment_data)
        print(f"success {interpreter_email}")
    
    return grouped_osi, grouped_vis

        
def cleanup_last_date_dirs(root="data", days=7):
    # deletes all files that is keeped more than one week
    try:
        date_dirs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    except FileNotFoundError:
        return

    while len(date_dirs) > days:
        oldest = date_dirs.pop(0) 
        shutil.rmtree(os.path.join(root, oldest), ignore_errors=True)
        print(f"🧹 removed {oldest}")



def main():
    cleanup_last_date_dirs()
    date_dir = os.path.join("data", need_date)
    os.makedirs(date_dir, exist_ok=True)

    print(f"Processing {need_date} reminders...")
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
        phone = assignments[0].get("phone")
        if not phone or not times:
            print(f'error sending, phone {phone}, time {times}')
            continue
        conversation_id = textus_client.send_reminder(phone, times)
        print(f"Sent to {phone}, times: {"".join(times)}")
        if conversation_id:
            textus_client.close_conversation(conversation_id)

    print(f"sending VIS reminders...")  
    
    # for interpreter, assignments in grouped_vis.items():
        
    #     for assignment in assignments:




if __name__ == '__main__':
    main()
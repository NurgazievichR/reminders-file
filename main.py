import json

from collections import defaultdict
from datetime import date, datetime

from adastra_client import AdAstraClient

need_date = date.today().strftime("%Y-%m-%d")
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
            page=page,
            size=size
        )

        items = resp.get("data", [])
        if not items:
            break

        all_appointments.extend(items)

        if len(items) < size:
            break

        page += 1

    print(f"✅ Всего собрано {len(all_appointments)} назначений")
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

        



def main():
    adastra_client = AdAstraClient()
    adastra_client.login()

    appointments = collect_all_appointments(adastra_client)
    file_name = f"data/appointments_{need_date.replace('-','_')}.json"
    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(appointments, f, indent=4, ensure_ascii=False)

    grouped_osi, grouped_vis = group_appointments(adastra_client, appointments)

    file_name_osi = f"data/{need_date.replace('-','_')}_grouped_apps_osi.json"
    file_name_vis = f"data/{need_date.replace('-','_')}_grouped_apps_vis.json"
    with open(file_name_osi, "w", encoding="utf-8") as f:
        json.dump(grouped_osi, f, indent=4, ensure_ascii=False)
    with open(file_name_vis, "w", encoding="utf-8") as f:
        json.dump(grouped_vis, f, indent=4, ensure_ascii=False)


if __name__ == '__main__':
    main()
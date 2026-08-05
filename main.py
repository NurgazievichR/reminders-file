import json
import os
import shutil

from collections import defaultdict
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from decouple import config

from adastra_client import AdAstraClient
from textus_cleint import TextUsClient
from graph_client import GraphClient
from timezones import format_time_with_tz

import time

need_date = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)).date().isoformat()
# need_date = '2025-10-13'
SYSTEM_GUID = "4212879f-9dca-4ba8-9141-65c536de9da3"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

#Onsite Consecutive / Onsite Simultaneous -> SMS
ONSITE_COMM_TYPES = ("oc", "os")
#Scheduled Telephonic (OPI) -> email, but with its own template
OPI_COMM_TYPES = ("st",)
#everything else (tpp, svi, ...) is treated as video -> email with link/PIN

OPI_INSTRUCTION_LINK = "https://connectsupport.helpwise.help/articles/247501-how-to-join-a-prescheduled-opi-call2-how-to-see-and-download-call-logs"
#OPI replies should land in the OPI team's own inbox, not the general one
OPI_MAILBOX = "opi@ad-astrainc.com"

#ASL goes through the DHOH TextUs inbox instead of the regular IPI one, same
#template as everyone else per comm type (onsite text unchanged, video gets
#its own SMS template since it normally only exists as an email)
LANGUAGE_ASL = "American Sign Language"

#FULL READY
def prepare_date_dir(root: str = DATA_DIR, days: int = 7):
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
    grouped_opi = defaultdict(list)
    grouped_osi_asl = defaultdict(list)
    grouped_vis_asl = defaultdict(list)

    for appointment in all_appointments:
        code = appointment.get("code")
        print(f"processing {code}",end=' ')
        language_to = appointment.get("languageTo")
        is_asl = language_to == LANGUAGE_ASL

        start_time = appointment.get("startTime")
        communication_type = appointment.get("fK_CommunicationType")
        comm_norm = (communication_type or "").strip().lower()

        if comm_norm in ONSITE_COMM_TYPES:
            grouped_dict = grouped_osi_asl if is_asl else grouped_osi
        elif comm_norm in OPI_COMM_TYPES:
            #no ASL through scheduled telephonic (it's a spoken-language-only channel)
            grouped_dict = grouped_opi
        else:
            grouped_dict = grouped_vis_asl if is_asl else grouped_vis

        is_virtual = grouped_dict in (grouped_vis, grouped_vis_asl)

        assigned_interpreter_id = appointment.get("fK_Interpreter")
        if not assigned_interpreter_id:
            print("No assigned interpreter")
            continue

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

        appointment_detailed = client.get_appointment(code)
        appointment_data["time_zone_name"] = appointment_detailed.get("timeZoneName")

        if is_virtual:
            virtual_data = {
                "virtualAddress": appointment_detailed.get("virtualAddress") or "n/a",
                "meetingPinCode": appointment_detailed.get("callerNumber") or "n/a",
                "pin": appointment_detailed.get("pin") or "n/a",
                "noteInterpreter": appointment_detailed.get("noteInterpreter") or "n/a",
                }
            appointment_data.update(virtual_data)

        grouped_dict[interpreter_email].append(appointment_data)
        print(f"success {interpreter_email}")

    return grouped_osi, grouped_vis, grouped_opi, grouped_osi_asl, grouped_vis_asl

from datetime import datetime


def _format_time(iso_str: str, time_zone_name: str | None = None) -> str:
    """'2025-11-25T14:00:00' -> '2:00 pm EST'."""
    return format_time_with_tz(iso_str, time_zone_name)


def _format_date(iso_str: str) -> str:
    """'2025-11-25T14:00:00' -> '11/25/2025'."""
    dt = datetime.fromisoformat(iso_str)
    return f"{dt.month}/{dt.day}/{dt.year}"


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
        time_str = _format_time(a["start_time"], a.get("time_zone_name"))
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
        "\nJust a friendly reminder to send us a screenshot when you connect to your virtual meeting. "
        "Please make sure to email it to interpreting@ad-astrainc.com. "
        "It is important that we receive this in the event a client reports that you are not connected, "
        "as it allows us to resolve any technical issues in a timely manner.\n"
    )

    lines.append("One more reminder to submit your VOS form immediately after completing the assignment. Payment processing begins once we receive your VOS—submitting it promptly helps ensure timely payment.")

    lines.append(
        "\nLet us know if you experience any problems right away.\n\n"
        "Thank you,\n"
        "Ramazan"
    )
    return "".join(lines)


def build_opi_body(assignments: list[dict]) -> str:
    lines: list[str] = []

    lines.append(
        "Hello,\n\n"
        "Reminding you of your scheduled telephonic (OPI) assignment(s) for tomorrow.\n"
    )

    assignments_sorted = sorted(assignments, key=lambda a: a["start_time"])

    for idx, a in enumerate(assignments_sorted, start=1):
        date_str = _format_date(a["start_time"])
        time_str = _format_time(a["start_time"], a.get("time_zone_name"))

        lines.append(f"\n{idx}) Assignment Number: {a.get('code')}")
        lines.append(f"\nDate and Time: {date_str}, {time_str}\n")

    lines.append(
        "\nPlatform: Ad Astra Connect\n"
        "\nHow to start the session: Log in Ad Astra Connect and Amazon Connect using "
        "your OPI credentials, click on appointment, click on start the session once "
        "the appointment opens.\n"
        f"\nInstruction link, if needed: {OPI_INSTRUCTION_LINK}\n"
        "\nReminder: Please leave the session if the client didn't join after 5-10 minutes "
        "from the start time.\n"
        "\nImportant note: OPI scheduled telephonic doesn't require VOS form submission. "
        "The system will invoice the appointment.\n"
        "\nHelpline: opi@ad-astrainc.com or call via 301 408 4242 Extension 145\n"
    )

    lines.append(
        "\nLet us know if you experience any problems right away.\n\n"
        "Thank you,\n"
        "Ramazan"
    )
    return "".join(lines)


def main():
    print(f"Processing {need_date} reminders...")

    #We create data folder where we will keep info about reminders, for debugging if there are some wrong cases for example
    date_dir = os.path.join(DATA_DIR, need_date)
    os.makedirs(date_dir, exist_ok=True) 
    prepare_date_dir()

    adastra_client = AdAstraClient()
    adastra_client.login()

    appointments = collect_all_appointments(adastra_client)
    with open(os.path.join(date_dir, "appointments.json"), "w", encoding="utf-8") as f:
        json.dump(appointments, f, indent=4, ensure_ascii=False)

    grouped_osi, grouped_vis, grouped_opi, grouped_osi_asl, grouped_vis_asl = group_appointments(adastra_client, appointments)
    with open(os.path.join(date_dir, "grouped_apps_osi.json"), "w", encoding="utf-8") as f:
        json.dump(grouped_osi, f, indent=4, ensure_ascii=False)
    with open(os.path.join(date_dir, "grouped_apps_vis.json"), "w", encoding="utf-8") as f:
        json.dump(grouped_vis, f, indent=4, ensure_ascii=False)
    with open(os.path.join(date_dir, "grouped_apps_opi.json"), "w", encoding="utf-8") as f:
        json.dump(grouped_opi, f, indent=4, ensure_ascii=False)
    with open(os.path.join(date_dir, "grouped_apps_osi_asl.json"), "w", encoding="utf-8") as f:
        json.dump(grouped_osi_asl, f, indent=4, ensure_ascii=False)
    with open(os.path.join(date_dir, "grouped_apps_vis_asl.json"), "w", encoding="utf-8") as f:
        json.dump(grouped_vis_asl, f, indent=4, ensure_ascii=False)

    print(f"sending OSI reminders...")
    textus_client = TextUsClient()

    for interpreter, assignments in grouped_osi.items():
        times = [a["start_time"] for a in assignments if a.get("start_time")]
        tz_names = [a.get("time_zone_name") for a in assignments if a.get("start_time")]
        phone = assignments[0].get("phone").strip()
        if not phone or not times:
            print(f'error sending, phone {phone}, time {times}')
            continue
        conversation_id = textus_client.send_reminder(phone, times, time_zone_names=tz_names)
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

    print(f"sending OPI reminders...")
    for interpreter, assignments in grouped_opi.items():
        subject = "Reminder - Scheduled Telephonic (OPI) Assignment"
        body = build_opi_body(assignments)
        client.send_message(interpreter, subject, body, from_mailbox=OPI_MAILBOX)
        print(f"Sent to {interpreter}")

    print(f"sending ASL OSI reminders...")
    dhoh_textus_client = TextUsClient(account_slug=config("DHOH_ACCOUNT_SLUG"))

    for interpreter, assignments in grouped_osi_asl.items():
        times = [a["start_time"] for a in assignments if a.get("start_time")]
        tz_names = [a.get("time_zone_name") for a in assignments if a.get("start_time")]
        phone = (assignments[0].get("phone") or "").strip()
        if not phone or not times:
            print(f'error sending, phone {phone}, time {times}')
            continue
        conversation_id = dhoh_textus_client.send_reminder(phone, times, time_zone_names=tz_names)
        print(f"Sent to {phone}, times: {"".join(times)}")
        if conversation_id:
            dhoh_textus_client.close_conversation(conversation_id)

    print(f"sending ASL VIS reminders...")
    for interpreter, assignments in grouped_vis_asl.items():
        phone = (assignments[0].get("phone") or "").strip()
        if not phone:
            print(f'error sending, no phone for {interpreter}')
            continue
        conversation_id = dhoh_textus_client.send_video_reminder(phone, assignments)
        print(f"Sent to {phone}")
        if conversation_id:
            dhoh_textus_client.close_conversation(conversation_id)

if __name__ == '__main__':
    main()
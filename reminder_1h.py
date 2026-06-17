import json
import os

import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from decouple import config

import main
from adastra_client import AdAstraClient
from textus_cleint import TextUsClient
from graph_client import GraphClient

NY = ZoneInfo("America/New_York")
REMINDER_1H_MIN_MINUTES = 52
REMINDER_1H_MAX_MINUTES = 67
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SENT_1H_PATH = os.path.join(DATA_DIR, "sent_1h.json")
OAH_KEYWORD = config("OAH_KEYWORD", default="OAH")


def parse_start_time(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(NY)


def minutes_until_start(start_time: str, now: datetime | None = None) -> float:
    now = now or datetime.now(NY)
    return (parse_start_time(start_time) - now).total_seconds() / 60


def is_in_1h_window(start_time: str, now: datetime | None = None) -> bool:
    minutes = minutes_until_start(start_time, now)
    return REMINDER_1H_MIN_MINUTES <= minutes <= REMINDER_1H_MAX_MINUTES


def is_oah_appointment(appointment: dict) -> bool:
    keyword = OAH_KEYWORD.strip().lower()
    if not keyword:
        return True

    for value in appointment.values():
        if isinstance(value, str) and keyword in value.lower():
            return True
    return False


def load_sent_1h() -> dict[str, str]:
    if not os.path.exists(SENT_1H_PATH):
        return {}
    with open(SENT_1H_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_sent_1h(sent: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(SENT_1H_PATH), exist_ok=True)
    with open(SENT_1H_PATH, "w", encoding="utf-8") as f:
        json.dump(sent, f, indent=2, ensure_ascii=False)


def build_vis_body_1h(assignments: list[dict]) -> str:
    lines = [
        "Hello,\n\n"
        "This is a reminder that your virtual assignment(s) start in about one hour. "
        "Please be camera presentable and ensure to join the session 5–10 minutes prior "
        "to avoid any tardiness/tech issues.\n"
    ]

    for idx, a in enumerate(sorted(assignments, key=lambda x: x["start_time"]), start=1):
        time_str = main._format_time(a["start_time"])
        lines.append(f"\n{idx}) Assignment {a.get('code')}:")
        lines.append(f"\nTime: {time_str}")
        lines.append(f"\nLink: {a.get('virtualAddress')}")
        lines.append(f"\nDial-in or Meeting number: {a.get('meetingPinCode')}")
        lines.append(f"\nPIN/Passcode: {a.get('pin')}")
        lines.append(f"\nNotes: {a.get('noteInterpreter')}\n")

    lines.append(
        "\nJust a friendly reminder to send us a screenshot when you connect to your virtual meeting. "
        "Please make sure to email it to interpreting@ad-astrainc.com.\n"
        "\nLet us know if you experience any problems right away.\n\n"
        "Thank you,\n"
        "Ramazan"
    )
    return "".join(lines)


def filter_appointments(appointments: list[dict], need_date: str, sent_1h: dict[str, str]) -> list[dict]:
    now = datetime.now(NY)
    filtered = []

    for appointment in appointments:
        code = appointment.get("code")
        start_time = appointment.get("startTime")
        code_str = str(code)

        if not is_oah_appointment(appointment):
            print(f"skip {code} not OAH")
            continue

        if not start_time:
            print(f"skip {code} no start time")
            continue

        minutes = minutes_until_start(start_time, now)
        if not is_in_1h_window(start_time, now):
            print(f"skip {code} {minutes:.0f} min until start (need {REMINDER_1H_MIN_MINUTES}-{REMINDER_1H_MAX_MINUTES})")
            continue

        if sent_1h.get(code_str) == need_date:
            print(f"skip {code} already sent 1h reminder today")
            continue

        filtered.append(appointment)

    print(f"✅ {len(filtered)} appointments ready for 1h reminder")
    return filtered


def send_same_day_sms(textus_client: TextUsClient, phone: str, times: list[str]) -> str | None:
    time_fmt = textus_client._format_times(times)
    body = (
        f"Hello,\n\n"
        f"This is a reminder that your assignment(s) start in about one hour at {time_fmt}.\n"
        f"To acknowledge receipt, please reply with 1 or please reply with 2 if you need one of our project managers to place a call to you."
        f"\nFriendly reminder to submit your VOS form immediately after completing the assignment. Payment processing begins once we receive your VOS—submitting it promptly helps ensure timely payment."
    )

    to = textus_client.to_e164_us(phone)
    if not to:
        print(f"❌ Invalid number format: {phone}")
        return None

    url = f"{textus_client.host}/{textus_client.account_slug}/messages"
    resp = requests.post(
        url,
        json={"to": to, "body": body},
        headers=textus_client.headers,
        timeout=30,
    )
    if resp.status_code == 201:
        conversation_path = resp.json().get("conversation")
        if conversation_path:
            return conversation_path.rsplit("/", 1)[-1]
    else:
        print(f"❌ send_reminder failed [{resp.status_code}]: {resp.text[:300]}")
    return None


def main_1h():
    need_date = datetime.now(NY).date().isoformat()
    print(f"Processing {need_date} 1h OAH reminders ({REMINDER_1H_MIN_MINUTES}-{REMINDER_1H_MAX_MINUTES} min window)...")

    date_dir = os.path.join(DATA_DIR, need_date)
    os.makedirs(date_dir, exist_ok=True)
    main.prepare_date_dir()

    sent_1h = load_sent_1h()

    adastra_client = AdAstraClient()
    adastra_client.login()

    main.need_date = need_date
    appointments = main.collect_all_appointments(adastra_client)
    appointments = filter_appointments(appointments, need_date, sent_1h)

    if not appointments:
        print("Nothing to send.")
        return

    grouped_osi, grouped_vis = main.group_appointments(adastra_client, appointments)

    textus_client = TextUsClient()
    print("sending OSI 1h reminders...")
    for interpreter, assignments in grouped_osi.items():
        times = [a["start_time"] for a in assignments if a.get("start_time")]
        phone = (assignments[0].get("phone") or "").strip()
        if not phone or not times:
            print(f"error sending, phone {phone}, time {times}")
            continue

        conversation_id = send_same_day_sms(textus_client, phone, times)
        print(f"Sent to {phone}, times: {', '.join(times)}")
        if conversation_id:
            textus_client.close_conversation(conversation_id)

        for a in assignments:
            sent_1h[str(a["code"])] = need_date

    print("sending VIS 1h reminders...")
    graph_client = GraphClient()
    for interpreter, assignments in grouped_vis.items():
        graph_client.send_message(interpreter, "Reminder", build_vis_body_1h(assignments))
        print(f"Sent to {interpreter}")
        for a in assignments:
            sent_1h[str(a["code"])] = need_date

    save_sent_1h(sent_1h)


if __name__ == "__main__":
    main_1h()

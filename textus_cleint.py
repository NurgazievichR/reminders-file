import requests
import re

from typing import Optional
from decouple import config
from datetime import datetime

class TextUsClient:
    def __init__(self, host: str | None = None, token: str | None = None, account_slug: str | None = None):
        self.host = (host or config("TEXTUS_HOST", default="https://next.textus.com")).rstrip("/")
        self.token = token or config("TEXTUS_API_TOKEN")
        self.account_slug = account_slug or config("ACCOUNT_SLUG")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.textus+jsonld",
            "Content-Type": "application/vnd.textus+jsonld",
        }

    @staticmethod
    def to_e164_us(phone: str) -> Optional[str]:
        #fixed the number
        if not phone:
            return None

        s = phone.strip()

        if re.fullmatch(r"\+1\d{10}", s):
            return s

        digits = re.sub(r"\D", "", s)

        if len(digits) == 11 and digits.startswith("1"):
            # '1XXXXXXXXXX' -> '+1XXXXXXXXXX'
            return f"+{digits}"

        if len(digits) == 10:
            # 'XXXXXXXXXX' -> '+1XXXXXXXXXX'
            return f"+1{digits}"

        return None

    @staticmethod
    def _format_times(times: list[str]) -> str:
        if not times:
            return ""

        formatted = []
        for t in times:
            try:
                dt = datetime.fromisoformat(t)
                formatted.append(dt.strftime("%-I:%M %p"))
            except Exception:
                formatted.append(str(t))

        if len(formatted) == 1:
            return formatted[0]
        if len(formatted) == 2:
            return f"{formatted[0]} and {formatted[1]}"
        return f"{', '.join(formatted[:-1])} and {formatted[-1]}"

    def send_reminder(self, phone_number: str, times: list[str]) -> str | None:
        to = self.to_e164_us(phone_number)
        if not to:
            print(f"❌ Invalid number format: {phone_number}")
            return None

        time_fmt = self._format_times(times)
        body = (
            f"Good evening,\n\n"
            f"This is a reminder of your assignment(s) for tomorrow at {time_fmt}.\n"
            f"To acknowledge receipt, please reply with 1 or please reply with 2 if you need one of our project managers to place a call to you."
            f"\nFriendly reminder to submit your VOS form immediately after completing the assignment. Payment processing begins once we receive your VOS—submitting it promptly helps ensure timely payment."
        )

        url = f"{self.host}/{self.account_slug}/messages"
        payload = {"to": to, "body": body}

        resp = requests.post(url, json=payload, headers=self.headers, timeout=30)
        if resp.status_code == 201:
            data = resp.json()
            conversation_path = data.get("conversation")
            if conversation_path:
                return conversation_path.rsplit("/", 1)[-1]
        else:
            print(f"❌ send_reminder failed [{resp.status_code}]: {resp.text[:300]}")
        return None
    
    def close_conversation(self, conversation_id: str) -> bool:
        url = f"{self.host}/conversations/{conversation_id}/close"
        resp = requests.put(url, headers=self.headers, timeout=30)
        if resp.status_code == 200:
            return True
        print(f"❌ close_conversation failed [{resp.status_code}]: {resp.text[:300]}")
        return False
    
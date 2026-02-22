import time
import httpx
from decouple import config


class GraphClient:
    def __init__(self):
        self.tenant_id = config("AZ_TENANT_ID")
        self.client_id = config("AZ_CLIENT_ID")
        self.client_secret = config("AZ_CLIENT_SECRET")
        self.mailbox = config("MAILBOX")

        # token cache
        self._token = None
        self._exp_ts = 0.0

    # ------------------ helpers ------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers=None,
        data=None,
        json=None,
        timeout=30,
    ):
        r = httpx.request(
            method,
            url,
            headers=headers,
            data=data,
            json=json,
            timeout=timeout,
        )
        r.raise_for_status()
        return r

    # ------------------ login ------------------

    def get_token(self) -> str:
        now = time.time()

        # токен ещё жив (с запасом 60 сек)
        if self._token and (self._exp_ts - now > 60):
            return self._token

        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        resp = self._request("POST", url, data=data)
        js = resp.json()

        self._token = js["access_token"]
        self._exp_ts = now + js["expires_in"]

        return self._token

    # ------------------ SEND MAIL ------------------

    def send_message(self, who: str, subject: str, body_text: str):
        url = f"https://graph.microsoft.com/v1.0/users/{self.mailbox}/sendMail"

        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body_text,
                },
                "toRecipients": [
                    {"emailAddress": {"address": who}}
                ],
            },
            "saveToSentItems": True,
        }

        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
        }

        self._request("POST", url, headers=headers, json=payload)

    # ------------------ TAG MESSAGE ------------------

    def tag_message(self, message_id: str, tag: str):
        url = f"https://graph.microsoft.com/v1.0/users/{self.mailbox}/messages/{message_id}"

        payload = {
            "categories": [tag]
        }

        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
        }

        self._request("PATCH", url, headers=headers, json=payload)

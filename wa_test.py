import os, httpx
from dotenv import load_dotenv
load_dotenv()
r = httpx.post(
    f"https://graph.facebook.com/v23.0/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages",
    headers={"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"},
    json={"messaging_product": "whatsapp", "to": os.environ["MY_NUMBER"],
          "type": "text", "text": {"body": "KarigarSetu test: Kapshi tan size 8, 5 pairs available"}},
)
print(r.status_code, r.json())
import json
import uuid
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8000/generate"
TENANT = "11111111-1111-1111-1111-111111111111"
BODY = json.dumps({"meter": "api_call"}).encode()

sent = 0
while True:
    key = f"fill-{uuid.uuid4()}"
    req = urllib.request.Request(
        URL,
        data=BODY,
        headers={
            "Content-Type": "application/json",
            "X-Tenant-Id": TENANT,
            "Idempotency-Key": key,
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            print(f"hit cap after {sent} new clicks")
            break
        raise
    sent += 1
    if sent % 100 == 0:
        print(f"sent {sent}")
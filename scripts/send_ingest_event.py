"""Send a GCS OBJECT_FINALIZE-style Pub/Sub push envelope to a running rag-ingest service.

Usage: python scripts/send_ingest_event.py http://localhost:8080 <file-name>
"""
import base64
import json
import sys

import requests

url, name = sys.argv[1].rstrip("/"), sys.argv[2]
envelope = {
    "message": {
        "attributes": {
            "eventType": "OBJECT_FINALIZE",
            "bucketId": "local",
            "objectId": name,
        },
        "data": base64.b64encode(json.dumps({"name": name}).encode()).decode(),
        "messageId": "local-test",
    },
    "subscription": "local",
}
r = requests.post(f"{url}/", json=envelope, timeout=300)
print(name, "->", r.status_code)

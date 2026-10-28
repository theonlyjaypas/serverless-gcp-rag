import json
import logging

from fastapi import FastAPI, Request, Response

from pipeline import ingest_object

app = FastAPI()
log = logging.getLogger("ingest")
logging.basicConfig(level=logging.INFO)


@app.post("/")
async def receive(request: Request):
    envelope = await request.json()
    message = envelope.get("message", {})
    attrs = message.get("attributes", {})

    event_type = attrs.get("eventType")
    bucket = attrs.get("bucketId")
    name = attrs.get("objectId")

    if event_type != "OBJECT_FINALIZE":
        return Response(status_code=204)

    if not bucket or not name:
        # Malformed event: non-2xx sends it to the DLQ after retries, so it can be inspected.
        log.error("missing bucketId or objectId in event: %s", json.dumps(attrs))
        return Response(status_code=400)

    try:
        result = ingest_object(bucket, name)
        log.info(json.dumps({"event": "ingested", **result}))
        return Response(status_code=204)
    except Exception:
        # Non-2xx tells Pub/Sub to retry; after 5 attempts it goes to the DLQ.
        log.exception("ingest failed for %s/%s", bucket, name)
        return Response(status_code=500)

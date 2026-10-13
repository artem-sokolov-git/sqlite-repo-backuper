import json
import logging
import urllib.request

log = logging.getLogger(__name__)


def notify_failure(url: str, message: str) -> None:
    """POST a JSON payload to the webhook; a broken webhook must never break the daemon."""
    body = json.dumps({"status": "error", "message": message}).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except (OSError, ValueError) as e:
        log.warning("webhook notification failed: %s", e)

"""Owner and agent views; secrets never cross this response projection."""


def present_intent(intent: dict, owner: bool = False) -> dict:
    value = {key: intent[key] for key in ("id", "action", "digest", "status", "created_at", "expires_at")}
    if not owner:
        value["action"] = {**intent["action"], "recipient": "[owner only]", "email": "[owner only]"}
    value["reason"] = intent.get("reason")
    invoice = intent.get("invoice")
    value["invoice"] = (
        None
        if not invoice
        else {
            "invoice_id": invoice["invoice_id"],
            "status": invoice.get("status"),
            "orders": [
                {"id": order.get("id"), "status": order.get("status")} for order in invoice.get("orders", [])
            ],
            "payment_link": invoice.get("payment_link") if owner and intent["status"] == "UNPAID" else None,
            "total_minor": invoice.get("total_minor"),
            "currency": invoice.get("currency"),
        }
    )
    return value


def present_x402_intent(intent: dict) -> dict:
    """Never project signing keys, payment signatures or internal SDK state."""
    value = {
        key: intent[key]
        for key in ("id", "kind", "action", "digest", "status", "created_at", "expires_at")
    }
    value["reason"] = intent.get("reason")
    value["settlement"] = intent.get("settlement")
    value["result"] = intent.get("result") if intent["status"] == "SUCCEEDED" else None
    return value

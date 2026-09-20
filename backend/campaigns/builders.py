def build_campaign_brief(validated_data: dict) -> dict:
    offer = validated_data.get("offer") or {"type": "none"}

    return {
        "schema_version": "1.0",
        "campaign_type": validated_data["campaign_type"],
        "goal": validated_data["goal"],
        "audience": validated_data["audience"],
        "offer": {
            "type": offer.get("type", "none"),
            "value": offer.get("value"),
            "code": offer.get("code"),
            "details": offer.get("details"),
        },
        "product": validated_data.get("product"),
        "destination_url": validated_data.get("destination_url"),
        "tone_override": validated_data.get("tone_override"),
        "additional_instructions": (
            validated_data.get("additional_instructions") or ""
        ),
    }

def build_campaign_brief(validated_data: dict) -> dict:
    offer = validated_data.get("offer") or {"type": "none"}
    product = validated_data.get("product")

    normalized_product = None
    if product:
        normalized_product = {
            "name": product["name"],
            "url": product.get("url"),
            "description": product.get("description"),
        }

    return {
        "schema_version": "1.0",
        "campaign_type": validated_data["campaign_type"],
        "goal": validated_data["goal"],
        "audience": {
            "description": validated_data["audience"]["description"],
        },
        "offer": {
            "type": offer.get("type", "none"),
            "value": offer.get("value"),
            "code": offer.get("code"),
            "details": offer.get("details"),
        },
        "product": normalized_product,
        "destination_url": validated_data.get("destination_url"),
        "tone_override": validated_data.get("tone_override"),
        "additional_instructions": (
            validated_data.get("additional_instructions") or ""
        ),
    }

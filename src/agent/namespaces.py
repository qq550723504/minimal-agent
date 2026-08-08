"""Collision-safe namespacing for administrator-provided identifiers."""


def encode_namespace_segment(value: str) -> str:
    """Preserve simple IDs while escaping dots in a namespace segment."""

    if "." not in value:
        return value
    # ``~`` is outside the manifest identifier alphabet, so this cannot
    # collide with an unencoded segment supplied by a plugin administrator.
    return f"~{value.encode('utf-8').hex()}"


def namespaced_id(*segments: str) -> str:
    return ".".join(encode_namespace_segment(segment) for segment in segments)


def capability_namespaced_id(*segments: str) -> str:
    """Create a namespaced capability ID that satisfies the tool-name grammar."""

    legacy = ".".join(segments)
    if all("." not in segment for segment in segments) and not legacy.startswith(
        "mcp-ns-"
    ):
        return legacy
    encoded = "-".join(
        f"{len(segment.encode('utf-8')):x}-{segment.encode('utf-8').hex()}"
        for segment in segments
    )
    return f"mcp-ns-{encoded}"

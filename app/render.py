from typing import Any


def _display_name(signup: dict[str, Any]) -> str:
    username = str(signup.get("username_at_signup", "")).lstrip("@")
    return f"@{username}"


def _numbered_section(signups: list[dict[str, Any]], empty_text: str) -> list[str]:
    if not signups:
        return [empty_text]
    return [f"{index}) {_display_name(signup)}" for index, signup in enumerate(signups, start=1)]


def split_signups(signups: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    in_list = [signup for signup in signups if signup.get("status") == "in"]
    waitlist = [signup for signup in signups if signup.get("status") == "waitlist"]
    return in_list, waitlist


def render_event_message(event: dict[str, Any], signups: list[dict[str, Any]]) -> str:
    if event.get("is_deleted"):
        return "This invite has been deleted."

    in_list, waitlist = split_signups(signups)
    invite_text = str(event.get("invite_text") or "").strip()
    status = event.get("status")
    if status:
        status = str(status).capitalize()
    else:
        status = "Open" if event.get("is_open", True) else "Closed"
    max_capacity = event.get("max_capacity", "?")

    lines: list[str] = []
    if invite_text:
        lines.append(invite_text)
        lines.append("")

    lines.extend(
        [
            f"Status: {status}",
            f"Max capacity: {max_capacity}",
            "",
            "I'm In:",
            *_numbered_section(in_list, "No signups yet."),
        ]
    )

    if waitlist:
        lines.extend(["", "Waitlist:", *_numbered_section(waitlist, "No waitlist yet.")])

    return "\n".join(lines)

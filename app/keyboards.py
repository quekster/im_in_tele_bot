from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def invite_keyboard(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("I'm in!", callback_data=f"invite:join:{event_id}"),
                InlineKeyboardButton("Waitlist me", callback_data=f"invite:waitlist:{event_id}"),
                InlineKeyboardButton("I'm out...", callback_data=f"invite:leave:{event_id}"),
            ]
        ]
    )

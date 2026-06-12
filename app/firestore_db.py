from __future__ import annotations

import asyncio
import logging
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import firestore


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"in", "waitlist"}


def _sort_key(signup: dict[str, Any]) -> Any:
    return signup.get("created_at") or signup.get("updated_at") or 0


def _active_sorted(signups: list[dict[str, Any]], status: str | None = None) -> list[dict[str, Any]]:
    filtered = [signup for signup in signups if signup.get("status") in ACTIVE_STATUSES]
    if status:
        filtered = [signup for signup in filtered if signup.get("status") == status]
    return sorted(filtered, key=_sort_key)


def _normalize_username(username: str) -> str:
    return username.strip().lstrip("@").lower()


class FirestoreDB:
    def __init__(self, project_id: str | None = None, database: str | None = None) -> None:
        self.project_id = project_id
        self.database = database
        self._client: firestore.Client | None = None

    @property
    def client(self) -> firestore.Client:
        if self._client is None:
            self._client = firestore.Client(project=self.project_id, database=self.database)
        return self._client

    def new_event_id(self) -> str:
        return self.client.collection("events").document().id

    async def remember_user(self, chat_id: int, user_id: int, username: str, full_name: str | None = None) -> None:
        await asyncio.to_thread(self._remember_user_sync, chat_id, user_id, username, full_name)

    def _remember_user_sync(self, chat_id: int, user_id: int, username: str, full_name: str | None = None) -> None:
        clean_username = username.lstrip("@")
        self.client.collection("known_users").document(str(user_id)).set(
            {
                "user_id": user_id,
                "username": clean_username,
                "username_lower": clean_username.lower(),
                "full_name": full_name,
                "chat_ids": firestore.ArrayUnion([chat_id]),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

    async def get_known_user_by_username(self, username: str, chat_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_known_user_by_username_sync, username, chat_id)

    def _get_known_user_by_username_sync(self, username: str, chat_id: int) -> dict[str, Any] | None:
        target = _normalize_username(username)
        query = self.client.collection("known_users").where("username_lower", "==", target).limit(5)
        for snap in query.stream():
            data = snap.to_dict() or {}
            if chat_id in data.get("chat_ids", []):
                data["id"] = snap.id
                return data
        return None

    async def get_topic_settings(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_topic_settings_sync)

    def _get_topic_settings_sync(self) -> dict[str, Any] | None:
        snap = self.client.collection("settings").document("telegram").get()
        return snap.to_dict() if snap.exists else None

    async def set_topic_settings(self, chat_id: int, message_thread_id: int | None) -> None:
        await asyncio.to_thread(self._set_topic_settings_sync, chat_id, message_thread_id)

    def _set_topic_settings_sync(self, chat_id: int, message_thread_id: int | None) -> None:
        self.client.collection("settings").document("telegram").set(
            {
                "allowed_chat_id": chat_id,
                "tourneys_message_thread_id": message_thread_id,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
        )

    async def create_event(
        self,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int | None,
        message_id: int,
        invite_text: str,
        max_capacity: int,
        created_by_user_id: int,
        poster_file_id: str | None = None,
        poster_message_id: int | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._create_event_sync,
            event_id,
            chat_id,
            message_thread_id,
            message_id,
            invite_text,
            max_capacity,
            created_by_user_id,
            poster_file_id,
            poster_message_id,
        )

    def _create_event_sync(
        self,
        event_id: str,
        chat_id: int,
        message_thread_id: int | None,
        message_id: int,
        invite_text: str,
        max_capacity: int,
        created_by_user_id: int,
        poster_file_id: str | None,
        poster_message_id: int | None,
    ) -> None:
        self.client.collection("events").document(event_id).set(
            {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "message_id": message_id,
                "invite_text": invite_text,
                "max_capacity": max_capacity,
                "is_open": True,
                "is_deleted": False,
                "poster_file_id": poster_file_id,
                "poster_message_id": poster_message_id,
                "created_by_user_id": created_by_user_id,
                "created_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
        )

    async def get_event(self, event_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_event_sync, event_id)

    def _get_event_sync(self, event_id: str) -> dict[str, Any] | None:
        snap = self.client.collection("events").document(event_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["id"] = snap.id
        return data

    async def get_event_by_message(self, chat_id: int, message_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_event_by_message_sync, chat_id, message_id)

    def _get_event_by_message_sync(self, chat_id: int, message_id: int) -> dict[str, Any] | None:
        query = (
            self.client.collection("events")
            .where("chat_id", "==", chat_id)
            .where("message_id", "==", message_id)
            .limit(1)
        )
        for snap in query.stream():
            data = snap.to_dict() or {}
            data["id"] = snap.id
            return data
        return None

    async def list_signups(self, event_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_signups_sync, event_id)

    def _list_signups_sync(self, event_id: str) -> list[dict[str, Any]]:
        snaps = self.client.collection("events").document(event_id).collection("signups").stream()
        signups = []
        for snap in snaps:
            data = snap.to_dict() or {}
            if data.get("status") in ACTIVE_STATUSES:
                data["id"] = snap.id
                signups.append(data)
        return sorted(signups, key=_sort_key)

    async def join_event(self, event_id: str, user_id: int, username: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._join_event_sync, event_id, user_id, username)

    def _join_event_sync(self, event_id: str, user_id: int, username: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any]:
            event_snap = event_ref.get(transaction=transaction)
            if not event_snap.exists:
                return {"ok": False, "message": "This invite is no longer available."}

            event = event_snap.to_dict() or {}
            if event.get("is_deleted"):
                return {"ok": False, "message": "This invite is no longer available."}
            if not event.get("is_open", True):
                return {"ok": False, "message": "This invite is closed."}

            signups = self._transaction_signups(event_ref, transaction)
            user_signup = self._find_signup(signups, user_id)
            if user_signup and user_signup.get("status") == "in":
                return {"ok": False, "message": "You're already in."}
            if user_signup and user_signup.get("status") == "waitlist":
                return {"ok": False, "message": "You're already on the waitlist."}

            in_list = _active_sorted(signups, "in")
            if len(in_list) >= int(event.get("max_capacity", 0)):
                return {"ok": False, "message": "Event is full. Press Waitlist me to join the waitlist."}

            transaction.set(
                event_ref.collection("signups").document(str(user_id)),
                {
                    "user_id": user_id,
                    "username_at_signup": username,
                    "status": "in",
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.update(event_ref, {"updated_at": firestore.SERVER_TIMESTAMP})
            return {"ok": True, "message": "You're in!", "changed": True}

        return txn(transaction)

    async def waitlist_event(self, event_id: str, user_id: int, username: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._waitlist_event_sync, event_id, user_id, username)

    def _waitlist_event_sync(self, event_id: str, user_id: int, username: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any]:
            event_snap = event_ref.get(transaction=transaction)
            if not event_snap.exists:
                return {"ok": False, "message": "This invite is no longer available."}

            event = event_snap.to_dict() or {}
            if event.get("is_deleted"):
                return {"ok": False, "message": "This invite is no longer available."}
            if not event.get("is_open", True):
                return {"ok": False, "message": "This invite is closed."}

            signups = self._transaction_signups(event_ref, transaction)
            user_signup = self._find_signup(signups, user_id)
            if user_signup and user_signup.get("status") == "in":
                return {"ok": False, "message": "You're already in."}
            if user_signup and user_signup.get("status") == "waitlist":
                return {"ok": False, "message": "You're already on the waitlist."}

            in_list = _active_sorted(signups, "in")
            if len(in_list) < int(event.get("max_capacity", 0)):
                return {"ok": False, "message": "There are still available slots. Press I'm in! instead."}

            transaction.set(
                event_ref.collection("signups").document(str(user_id)),
                {
                    "user_id": user_id,
                    "username_at_signup": username,
                    "status": "waitlist",
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.update(event_ref, {"updated_at": firestore.SERVER_TIMESTAMP})
            return {"ok": True, "message": "You've been added to the waitlist.", "changed": True}

        return txn(transaction)

    async def leave_event(self, event_id: str, user_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._leave_event_sync, event_id, user_id)

    def _leave_event_sync(self, event_id: str, user_id: int) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any]:
            event_snap = event_ref.get(transaction=transaction)
            if not event_snap.exists or (event_snap.to_dict() or {}).get("is_deleted"):
                return {"ok": False, "message": "This invite is no longer available."}

            event = event_snap.to_dict() or {}
            signups = self._transaction_signups(event_ref, transaction)
            user_signup = self._find_signup(signups, user_id)
            if not user_signup or user_signup.get("status") not in ACTIVE_STATUSES:
                return {"ok": False, "message": "You're not on this invite."}

            transaction.update(
                event_ref.collection("signups").document(str(user_id)),
                {"status": "removed", "updated_at": firestore.SERVER_TIMESTAMP},
            )

            if user_signup.get("status") == "in":
                self._promote_waitlist_if_space(event_ref, transaction, event, signups, removed_user_id=user_id)
                message = "You've been removed from the event."
            else:
                message = "You've been removed from the waitlist."

            transaction.update(event_ref, {"updated_at": firestore.SERVER_TIMESTAMP})
            return {"ok": True, "message": message, "changed": True}

        return txn(transaction)

    async def set_event_open(self, event_id: str, is_open: bool) -> dict[str, Any]:
        return await asyncio.to_thread(self._set_event_open_sync, event_id, is_open)

    def _set_event_open_sync(self, event_id: str, is_open: bool) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        snap = event_ref.get()
        if not snap.exists or (snap.to_dict() or {}).get("is_deleted"):
            return {"ok": False, "message": "Invite not found."}
        event_ref.update({"is_open": is_open, "updated_at": firestore.SERVER_TIMESTAMP})
        return {"ok": True, "changed": True}

    async def update_invite_text(self, event_id: str, invite_text: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._update_invite_text_sync, event_id, invite_text)

    def _update_invite_text_sync(self, event_id: str, invite_text: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        snap = event_ref.get()
        if not snap.exists or (snap.to_dict() or {}).get("is_deleted"):
            return {"ok": False, "message": "Invite not found."}
        event_ref.update({"invite_text": invite_text, "updated_at": firestore.SERVER_TIMESTAMP})
        return {"ok": True, "changed": True}

    async def delete_event(self, event_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._delete_event_sync, event_id)

    def _delete_event_sync(self, event_id: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        if not event_ref.get().exists:
            return {"ok": False, "message": "Invite not found."}
        self._delete_event_document(event_ref)
        return {"ok": True, "changed": True}

    async def end_event(self, event_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._end_event_sync, event_id)

    def _end_event_sync(self, event_id: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        if not event_ref.get().exists:
            return {"ok": False, "message": "Invite not found."}

        self._delete_event_document(event_ref)
        return {"ok": True, "changed": True}

    async def set_capacity(self, event_id: str, new_capacity: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._set_capacity_sync, event_id, new_capacity)

    def _set_capacity_sync(self, event_id: str, new_capacity: int) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any]:
            event_snap = event_ref.get(transaction=transaction)
            if not event_snap.exists or (event_snap.to_dict() or {}).get("is_deleted"):
                return {"ok": False, "message": "Invite not found."}

            signups = self._transaction_signups(event_ref, transaction)
            in_list = _active_sorted(signups, "in")
            waitlist = _active_sorted(signups, "waitlist")

            if new_capacity >= len(in_list):
                for signup in waitlist[: new_capacity - len(in_list)]:
                    transaction.update(
                        event_ref.collection("signups").document(str(signup["user_id"])),
                        {"status": "in", "updated_at": firestore.SERVER_TIMESTAMP},
                    )
            else:
                for signup in in_list[new_capacity:]:
                    transaction.update(
                        event_ref.collection("signups").document(str(signup["user_id"])),
                        {"status": "waitlist", "updated_at": firestore.SERVER_TIMESTAMP},
                    )

            transaction.update(event_ref, {"max_capacity": new_capacity, "updated_at": firestore.SERVER_TIMESTAMP})
            return {"ok": True, "changed": True}

        return txn(transaction)

    async def remove_user_by_username(self, event_id: str, username: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._remove_user_by_username_sync, event_id, username)

    def _remove_user_by_username_sync(self, event_id: str, username: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        transaction = self.client.transaction()
        target = _normalize_username(username)

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any]:
            event_snap = event_ref.get(transaction=transaction)
            if not event_snap.exists or (event_snap.to_dict() or {}).get("is_deleted"):
                return {"ok": False, "message": "Invite not found."}

            event = event_snap.to_dict() or {}
            signups = self._transaction_signups(event_ref, transaction)
            signup = next(
                (
                    item
                    for item in signups
                    if item.get("status") in ACTIVE_STATUSES
                    and _normalize_username(str(item.get("username_at_signup", ""))) == target
                ),
                None,
            )
            if not signup:
                return {"ok": False, "message": "User is not on this invite."}

            transaction.update(
                event_ref.collection("signups").document(str(signup["user_id"])),
                {"status": "removed", "updated_at": firestore.SERVER_TIMESTAMP},
            )
            if signup.get("status") == "in":
                self._promote_waitlist_if_space(event_ref, transaction, event, signups, removed_user_id=signup["user_id"])
            transaction.update(event_ref, {"updated_at": firestore.SERVER_TIMESTAMP})
            return {"ok": True, "changed": True}

        return txn(transaction)

    async def add_known_user_by_username(self, event_id: str, username: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._add_known_user_by_username_sync, event_id, username)

    async def add_user_to_event(self, event_id: str, user_id: int, username: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._add_user_to_event_sync, event_id, user_id, username)

    def _add_user_to_event_sync(self, event_id: str, user_id: int, username: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any]:
            event_snap = event_ref.get(transaction=transaction)
            if not event_snap.exists or (event_snap.to_dict() or {}).get("is_deleted"):
                return {"ok": False, "message": "Invite not found."}

            event = event_snap.to_dict() or {}
            signups = self._transaction_signups(event_ref, transaction)
            existing = self._find_signup(signups, user_id)
            if existing and existing.get("status") in ACTIVE_STATUSES:
                return {"ok": False, "message": "User is already on this invite."}

            in_list = _active_sorted(signups, "in")
            status = "in" if len(in_list) < int(event.get("max_capacity", 0)) else "waitlist"
            transaction.set(
                event_ref.collection("signups").document(str(user_id)),
                {
                    "user_id": user_id,
                    "username_at_signup": username.lstrip("@"),
                    "status": status,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.update(event_ref, {"updated_at": firestore.SERVER_TIMESTAMP})
            return {"ok": True, "changed": True}

        return txn(transaction)

    def _add_known_user_by_username_sync(self, event_id: str, username: str) -> dict[str, Any]:
        event_ref = self.client.collection("events").document(event_id)
        transaction = self.client.transaction()
        target = _normalize_username(username)

        @firestore.transactional
        def txn(transaction: firestore.Transaction) -> dict[str, Any]:
            event_snap = event_ref.get(transaction=transaction)
            if not event_snap.exists or (event_snap.to_dict() or {}).get("is_deleted"):
                return {"ok": False, "message": "Invite not found."}

            event = event_snap.to_dict() or {}
            signups = self._transaction_signups(event_ref, transaction)
            matching = [
                item for item in signups if _normalize_username(str(item.get("username_at_signup", ""))) == target
            ]
            if not matching:
                return {"ok": False, "message": "I only know users who previously joined this invite."}

            signup = matching[0]
            if signup.get("status") in ACTIVE_STATUSES:
                return {"ok": False, "message": "User is already on this invite."}

            in_list = _active_sorted(signups, "in")
            status = "in" if len(in_list) < int(event.get("max_capacity", 0)) else "waitlist"
            transaction.set(
                event_ref.collection("signups").document(str(signup["user_id"])),
                {
                    "user_id": signup["user_id"],
                    "username_at_signup": signup["username_at_signup"],
                    "status": status,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.update(event_ref, {"updated_at": firestore.SERVER_TIMESTAMP})
            return {"ok": True, "changed": True}

        return txn(transaction)

    async def firestore_smoke_test(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._firestore_smoke_test_sync)

    def _firestore_smoke_test_sync(self) -> dict[str, Any]:
        ref = self.client.collection("debug").document("firestore-test")
        ref.set({"ok": True, "updated_at": firestore.SERVER_TIMESTAMP})
        snap = ref.get()
        return snap.to_dict() or {}

    def _transaction_signups(
        self, event_ref: firestore.DocumentReference, transaction: firestore.Transaction
    ) -> list[dict[str, Any]]:
        try:
            snaps = event_ref.collection("signups").stream(transaction=transaction)
            signups = []
            for snap in snaps:
                data = snap.to_dict() or {}
                data["id"] = snap.id
                signups.append(data)
            return sorted(signups, key=_sort_key)
        except GoogleAPICallError:
            logger.exception("Firestore transaction failed while reading signups")
            raise

    def _delete_collection(self, collection_ref: firestore.CollectionReference, batch_size: int = 450) -> None:
        while True:
            docs = list(collection_ref.limit(batch_size).stream())
            if not docs:
                return

            batch = self.client.batch()
            for doc in docs:
                batch.delete(doc.reference)
            batch.commit()

    def _delete_event_document(self, event_ref: firestore.DocumentReference) -> None:
        self._delete_collection(event_ref.collection("signups"))
        event_ref.delete()

    def _find_signup(self, signups: list[dict[str, Any]], user_id: int) -> dict[str, Any] | None:
        for signup in signups:
            if int(signup.get("user_id", 0)) == user_id:
                return signup
        return None

    def _promote_waitlist_if_space(
        self,
        event_ref: firestore.DocumentReference,
        transaction: firestore.Transaction,
        event: dict[str, Any],
        signups: list[dict[str, Any]],
        *,
        removed_user_id: int,
    ) -> None:
        in_count = len(
            [
                signup
                for signup in signups
                if signup.get("status") == "in" and int(signup.get("user_id", 0)) != removed_user_id
            ]
        )
        max_capacity = int(event.get("max_capacity", 0))
        if in_count >= max_capacity:
            return

        waitlist = [
            signup for signup in _active_sorted(signups, "waitlist") if int(signup.get("user_id", 0)) != removed_user_id
        ]
        if not waitlist:
            return

        promoted = waitlist[0]
        transaction.update(
            event_ref.collection("signups").document(str(promoted["user_id"])),
            {"status": "in", "updated_at": firestore.SERVER_TIMESTAMP},
        )

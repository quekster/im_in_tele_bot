from app.config import get_settings
from app.firestore_db import FirestoreDB


def main() -> None:
    settings = get_settings()
    db = FirestoreDB(settings.google_cloud_project, settings.firestore_database)
    query = db.client.collection("events").where("is_deleted", "==", True)
    deleted_count = 0

    for snap in query.stream():
        db._delete_event_document(snap.reference)
        deleted_count += 1

    print(f"Deleted {deleted_count} soft-deleted event document(s).")


if __name__ == "__main__":
    main()

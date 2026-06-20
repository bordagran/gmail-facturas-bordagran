"""
setup_labels.py — Bordagran Fiscal
Crea los labels necesarios en Gmail si no existen.

Uso:
    python scripts/setup_labels.py --skill-dir /ruta/skill
"""
import argparse
import json
import pickle
import sys
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", required=True)
    args = parser.parse_args()
    skill_dir = Path(args.skill_dir)

    with open(skill_dir / "config.json") as f:
        config = json.load(f)

    with open(skill_dir / "token.pickle", "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build("gmail", "v1", credentials=creds)

    labels_requeridos = [
        config["LABEL_PROCESADAS"],
        config["LABEL_PENDIENTE"],
    ]

    # Obtener labels existentes
    existing = {l["name"]: l["id"] for l in
                service.users().labels().list(userId="me").execute().get("labels", [])}

    for label_name in labels_requeridos:
        if label_name in existing:
            print(f"✅ Ya existe: {label_name} (id: {existing[label_name]})")
        else:
            nuevo = service.users().labels().create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                }
            ).execute()
            print(f"✅ Creado: {label_name} (id: {nuevo['id']})")


if __name__ == "__main__":
    main()
